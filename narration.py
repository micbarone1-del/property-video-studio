"""
narration.py
─────────────
Single continuous narration system — replaces per-scene TTS coupling.

Key design (agreed):
  - ONE narration script for the whole property, not per-scene text
  - Generated as sentence-split TTS calls, concatenated with explicit
    silence gaps — this FIXES ElevenLabs' Italian full-stop pause bug
    (periods don't reliably produce natural pauses in the Italian voice;
    splitting per-sentence and inserting real silence sidesteps this
    entirely rather than depending on ElevenLabs' internal handling)
  - Duration is measured from ACTUAL generated audio, then scene
    durations are calculated and shown to the user BEFORE any video
    generation — never regenerate video to fix a duration mismatch,
    always get it right before the expensive step runs
"""

import os
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Silence gap inserted between sentences (milliseconds).
# This is what actually creates natural pacing — NOT the period itself,
# since ElevenLabs' Italian voice does not reliably pause at "." alone.
SENTENCE_PAUSE_MS = 380

# Unified padding constants (2026-07-17 fix): these are the SAME values
# _overlay_narration_audio() in api_server.py uses for its real lead-in/
# trail-out blank padding at assembly time. Previously this file had its
# own separate END_BUFFER_SECS=2.5 for the scene-duration target
# calculation, disconnected from the real 1.5s (0.75+0.75) padding
# actually applied later -- meaning scenes could be generated (and paid
# for) slightly longer than genuinely needed, and the "video will be
# extended to Xs" message shown to the user didn't match the real final
# video length. Both stages now read from these same two numbers.
LEAD_SECS  = 1.0    # blank before narration starts (2026-07-21: was 0.75 -- WhatsApp confirmed cutting the first ~1s off video previews, eating into real speech; wider buffer absorbs that trim instead of clipping actual narration)
TRAIL_SECS = 1.0    # blank after narration ends (2026-07-21: same reasoning, protects the outro from the same class of platform-side trimming)
NARRATION_PADDING_SECS = LEAD_SECS + TRAIL_SECS   # = 2.0s total (2026-07-21: was 1.5s before the WhatsApp-trimming buffer increase)

# Threshold below which narration is considered "too short" for the
# current total video duration, triggering the red warning + fix options.
TOO_SHORT_THRESHOLD_SECS = 4.0

# 2026-10-15 (Michele): predictable, synchronised narration for tiers whose
# scenes have ONE fixed length (Luma: 5 s only -- 9 s clips are not used, they
# risk hallucinations). The scene lengths never change; instead the pauses in
# the speech are adjusted so a sentence starts when "its" scene starts.
FIXED_SCENE_SECS_BY_TIER = {"luma": 5}
SYNC_SNAP_WINDOW_SECS = 2.0   # a sentence that would start up to this long BEFORE a scene cut is delayed to the cut
MAX_OVERFLOW_SECS     = 2.0   # speech may run this long past the end of the scenes (absorbed by the trailing blank buffer)
SYNC_SPILL_WARN_SECS  = 2.0   # warn when a sentence that opens a scene runs this long into the next scene
WORDS_PER_SEC         = 2.4   # only used to turn "cut N seconds" into a rough word count (measured ~0.35-0.55 s/word on Leda)


def split_into_sentences(text: str) -> list[str]:
    """
    Splits narration text into sentences for individual TTS generation.
    Handles Italian punctuation (. ! ? and combinations), preserves
    reasonable sentence boundaries without over-splitting on abbreviations
    like "n." or numbers with decimal points.
    """
    import re
    text = text.strip()
    if not text:
        return []

    # Split on sentence-ending punctuation followed by space/end, but
    # avoid splitting on decimal numbers (e.g. "3.5 milioni") or common
    # abbreviations. This is a pragmatic heuristic, not perfect NLP.
    raw_sentences = re.split(r'(?<=[.!?])\s+(?=[A-ZÀ-Ü])', text)

    sentences = []
    for s in raw_sentences:
        s = s.strip()
        if s:
            sentences.append(s)

    return sentences if sentences else [text]


def plan_sentence_sync(
    sentence_ms:       list,
    scene_secs:        list,
    sentence_pause_ms: int = SENTENCE_PAUSE_MS,
) -> dict:
    """
    Pure function (no audio, no network): given the MEASURED length of each
    sentence and the fixed scene lengths, decides how much EXTRA silence to put
    before each sentence so that a sentence which would start just before a scene
    cut starts exactly on the cut instead.

    Timeline: narration time 0 == start of scene 0 (assembly adds the blank lead
    around the video, see _overlay_narration_audio), so the cut between scenes
    k-1 and k is at sum(scene_secs[:k]) seconds of narration time.

    Rules (deterministic):
      - sentence 0 starts at 0.
      - every other sentence starts at previous end + sentence_pause_ms. If the
        next scene cut is at most SYNC_SNAP_WINDOW_SECS later, the sentence is
        delayed to that cut (extra pause = the difference, never more than the
        window). A sentence that already starts after a cut is never moved earlier.
      - nothing is ever cut from the audio.
    """
    cuts = []
    acc = 0.0
    for d in scene_secs:
        cuts.append(acc)
        acc += float(d)
    total_video = acc
    base_pause = sentence_pause_ms / 1000.0

    def scene_of(t):
        k = 0
        for i, c in enumerate(cuts):
            if t + 1e-6 >= c:
                k = i
        return k

    rows = []
    extras_ms = []
    t = 0.0
    for j, dur_ms in enumerate(sentence_ms):
        extra = 0.0
        if j > 0:
            nxt = next((c for c in cuts if c > t + 1e-6), None)
            if nxt is not None and (nxt - t) <= SYNC_SNAP_WINDOW_SECS:
                extra = nxt - t
                t = nxt
        k = scene_of(t)
        end = t + dur_ms / 1000.0
        scene_end = cuts[k] + float(scene_secs[k]) if k < len(scene_secs) else total_video
        rows.append({
            "index": j,
            "scene": k,
            "start_secs": round(t, 2),
            "end_secs": round(end, 2),
            "offset_in_scene_secs": round(t - cuts[k], 2),
            "extra_pause_secs": round(extra, 2),
            "spill_secs": round(max(0.0, end - scene_end), 2),
        })
        extras_ms.append(int(round(extra * 1000)))
        t = end + base_pause

    speech_end = rows[-1]["end_secs"] if rows else 0.0
    overflow = max(0.0, speech_end - total_video)
    warnings = []
    for r in rows:
        if r["offset_in_scene_secs"] <= 0.05 and r["spill_secs"] > SYNC_SPILL_WARN_SECS:
            warnings.append(
                f"La frase {r['index']+1} (scena {r['scene']+1}) supera la scena di {r['spill_secs']:.1f}s: accorciala o spezzala"
            )
    return {
        "rows": rows,
        "extra_pause_ms": extras_ms,
        "speech_end_secs": round(speech_end, 2),
        "total_video_secs": round(total_video, 2),
        "overflow_secs": round(overflow, 2),
        "too_long": overflow > MAX_OVERFLOW_SECS,
        "warnings": warnings,
    }


def evaluate_fixed_durations(narration_duration_secs: float, scene_durations: list, sync: dict) -> dict:
    """
    Same return shape as calculate_scene_durations(), for tiers with fixed scene
    lengths: the scene durations are NEVER changed and the video is never
    "extended". Speech running past the scenes is absorbed by the trailing blank
    buffer up to MAX_OVERFLOW_SECS; beyond that the text must be shortened.
    """
    current_total = sum(scene_durations)
    overflow = sync["overflow_secs"]
    too_long = sync["too_long"]
    silence = current_total - narration_duration_secs
    too_short = (not too_long) and narration_duration_secs > 0 and silence > TOO_SHORT_THRESHOLD_SECS
    n_pauses = sum(1 for r in sync["rows"] if r["extra_pause_secs"] > 0.05)
    if too_long:
        cut = overflow - MAX_OVERFLOW_SECS + 0.5
        msg = (f"Narrazione troppo lunga: finisce {overflow:.1f}s dopo l'ultima scena "
               f"(il buffer finale ne assorbe al massimo {MAX_OVERFLOW_SECS:.0f}s). "
               f"Accorcia il testo di circa {cut:.0f}s (circa {max(1, round(cut * WORDS_PER_SEC))} parole)")
    elif too_short:
        msg = (f"Narrazione troppo breve per la durata video attuale — {round(silence)}s di silenzio previsti")
    else:
        msg = (f"Narrazione sincronizzata con le scene ({n_pauses} pause aggiunte per allinearla; "
               f"{overflow:.1f}s oltre l'ultima scena, assorbiti dal buffer)" if overflow > 0.05 else
               f"Narrazione sincronizzata con le scene ({n_pauses} pause aggiunte per allinearla)")
    return {
        "narration_duration_secs": round(narration_duration_secs, 1),
        "target_total_secs":       current_total,
        "current_total_secs":      current_total,
        "new_scene_durations":     list(scene_durations),
        "needs_extension":         False,
        "too_short":               too_short,
        "too_long":                too_long,
        "fixed_durations":         True,
        "max_overflow_secs":       MAX_OVERFLOW_SECS,
        "sync":                    sync,
        "message":                 msg,
    }


def synthesize_sentences(text: str, voice_id: str = None, tmp_parent: str = None) -> dict:
    """
    TTS step only: one real TTS call per sentence, returned as in-memory audio.
    2026-10-15: split out of generate_narration_audio() so the manual workflow and the
    URL/Relinx workflow share ONE voice-generation path, and so the clips can be
    re-assembled (e.g. with a different scene count) without paying for TTS again.
    Returns {"ok", "sentences", "clips", "error"}.
    """
    import tempfile, shutil
    from voice_generation import generate_speech as generate_voice
    from pydub import AudioSegment

    sentences = split_into_sentences(text)
    if not sentences:
        return {"ok": False, "error": "Empty narration text", "sentences": [], "clips": []}

    log.info(f"[Narration] Splitting into {len(sentences)} sentences for TTS generation")
    tmp_dir = Path(tempfile.mkdtemp(prefix="_narration_sentences_", dir=tmp_parent))
    clips = []
    try:
        for i, sentence in enumerate(sentences):
            sentence_path = str(tmp_dir / f"sentence_{i:03d}.mp3")
            ok = generate_voice(sentence, sentence_path, voice_id=voice_id)
            if not ok or not os.path.exists(sentence_path):
                log.error(f"[Narration] Failed to generate sentence {i}: {sentence[:50]}")
                return {"ok": False, "error": f"TTS failed on sentence {i+1}", "sentences": sentences, "clips": []}
            clips.append(AudioSegment.from_file(sentence_path))
        return {"ok": True, "error": None, "sentences": sentences, "clips": clips}
    finally:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)


def assemble_narration(
    sentences:         list,
    clips:             list,
    output_path:       str,
    sentence_pause_ms: int = SENTENCE_PAUSE_MS,
    scene_secs:        list = None,
) -> dict:
    """
    Assembly step (no TTS): concatenates the sentence clips with the plain pause and,
    when scene_secs is given (fixed scene lengths), the extra silence that
    plan_sentence_sync() asks for so each sentence starts on its scene cut.
    """
    from pydub import AudioSegment

    sync = None
    extras_ms = [0] * len(clips)
    if scene_secs:
        sync = plan_sentence_sync([len(c) for c in clips], scene_secs, sentence_pause_ms)
        extras_ms = sync["extra_pause_ms"]

    combined = clips[0]
    sentence_timings = [{"index": 0, "text": sentences[0], "start_ms": 0, "duration_ms": len(clips[0])}]
    offset_ms = len(clips[0])
    for i in range(1, len(clips)):
        gap = sentence_pause_ms + extras_ms[i]
        combined = combined + AudioSegment.silent(duration=gap) + clips[i]
        offset_ms += gap
        sentence_timings.append({"index": i, "text": sentences[i], "start_ms": offset_ms, "duration_ms": len(clips[i])})
        offset_ms += len(clips[i])

    combined.export(output_path, format="mp3")
    total_duration_secs = len(combined) / 1000.0
    log.info(f"[Narration] Generated {len(sentences)} sentences, "
             f"total duration {total_duration_secs:.1f}s -> {output_path}")
    return {
        "ok": True,
        "duration_secs": total_duration_secs,
        "sentence_count": len(sentences),
        "sentence_timings": sentence_timings,
        "sync": sync,
        "output_path": output_path,
    }


def generate_narration_audio(
    text:            str,
    output_path:     str,
    voice_id:        str = None,
    sentence_pause_ms: int = SENTENCE_PAUSE_MS,
    scene_secs:      list = None,
) -> dict:
    """
    Generates the full narration as sentence-split TTS calls, concatenated
    with explicit silence gaps (synthesize_sentences + assemble_narration).
    Returns a dict with success status, actual measured duration, per-sentence
    timing and, for fixed-length scenes, the sentence/scene sync plan.

    This is the ONLY code path that generates narration audio, for BOTH the manual
    workflow and the URL/Relinx workflow (listing_scraper._measure_tts_duration).
    """
    syn = synthesize_sentences(text, voice_id, tmp_parent=str(Path(output_path).parent))
    if not syn["ok"]:
        return {"ok": False, "error": syn["error"], "duration_secs": 0}
    return assemble_narration(syn["sentences"], syn["clips"], output_path, sentence_pause_ms, scene_secs)


def calculate_scene_durations(
    narration_duration_secs: float,
    scene_count:             int,
    current_durations:       list[int] = None,
    valid_durations:         list[int] = None,
) -> dict:
    """
    Given the ACTUAL measured narration duration, calculates how scene
    durations should be redistributed BEFORE any video generation happens.

    Returns a dict describing:
      - the target total video duration (narration + end buffer)
      - new per-scene durations, redistributed proportionally
      - whether narration is too short (below threshold) — quality warning
      - whether current total needs to increase (narration too long)

    This is called from the UI after narration TTS completes, and again
    any time narration text changes — NEVER after video generation, only
    before it, so video is always generated once at the correct duration.
    """
    if valid_durations is None:
        valid_durations = [4, 5, 6, 8, 9]  # union of Veo (4/6/8) and Luma (5/9) valid values

    # 2026-10-15 (Michele: narration was over-estimated): the lead/trail blank
    # frames are ADDED AROUND the scenes at assembly time (_overlay_narration_audio:
    # lead + video + trail), they are not carved out of the scene time. So the
    # scenes only need to cover the speech itself. The old "speech + 2 s" target
    # counted the buffer twice (once here, once as real blank frames), extended
    # videos that did not need it, and paid for ~2 extra seconds of Luma.
    target_total = narration_duration_secs

    current_total = sum(current_durations) if current_durations else scene_count * 6

    too_short = narration_duration_secs > 0 and (
        current_total - narration_duration_secs > TOO_SHORT_THRESHOLD_SECS
    )
    needs_extension = target_total > current_total

    # Redistribute target_total across scenes, proportional to their
    # current relative durations (so a scene the user made "longer" stays
    # proportionally longer), snapped to valid model durations.
    if current_durations and sum(current_durations) > 0:
        weights = [d / sum(current_durations) for d in current_durations]
    else:
        weights = [1.0 / scene_count] * scene_count

    raw_new_durations = [w * target_total for w in weights]

    def snap(value):
        return min(valid_durations, key=lambda v: abs(v - value))

    new_durations = [snap(d) for d in raw_new_durations]

    # BUG FIXED: snapping happens PER SCENE, so each scene independently
    # rounds to the nearest valid model duration - and the rounding loss is
    # silently multiplied across every scene, with nothing ever re-checking
    # the total. Confirmed via test: narration 27.5s -> target_total 30s was
    # REPORTED to the user, but 5 Luma scenes x snap(6.0)=5s only delivered
    # 25s of actual video, leaving audio running 2.5s past the video end on
    # a frozen final frame. Reported number and real scene math were computed
    # from the same value but never reconciled.
    #
    # Fix: after snapping, recompute the ACTUAL achievable total. If it does
    # not cover the narration, extend (bump scenes to longer valid durations,
    # or add a scene) until it genuinely does. The video is now structurally
    # guaranteed to be at least as long as the narration.
    longest_valid = max(valid_durations)
    actual_total = sum(new_durations)

    while actual_total < target_total and len(new_durations) <= 20:
        bumped = False
        # 2026-10-15: bump the LAST scene first (it used to be the FIRST), so
        # the extra seconds land at the end and every earlier scene keeps its
        # position: bumping scene 1 shifted all later pictures by the extra
        # time and desynchronised them from the narration (seen on the villa
        # test: bathroom spoken at 49 s but shown from 54 s).
        for i in range(len(new_durations) - 1, -1, -1):
            d = new_durations[i]
            larger = [v for v in valid_durations if v > d]
            if larger:
                new_durations[i] = min(larger)
                actual_total = sum(new_durations)
                bumped = True
                break
        if not bumped:
            new_durations.append(longest_valid)
            actual_total = sum(new_durations)

    # Report the TRUTH, not the pre-snapping target.
    target_total = actual_total

    return {
        "narration_duration_secs": round(narration_duration_secs, 1),
        "target_total_secs":       round(target_total, 1),
        "current_total_secs":      current_total,
        "new_scene_durations":     new_durations,
        "needs_extension":         needs_extension,
        "too_short":               too_short,
        "message": (
            f"Il video verrà esteso a {round(target_total)}s per adattarsi alla narrazione "
            f"(durata attuale: {current_total}s)" if needs_extension else
            f"Narrazione troppo breve per la durata video attuale — "
            f"{round(current_total - narration_duration_secs)}s di silenzio previsti" if too_short else
            "Durata narrazione e video compatibili"
        ),
    }


def suggest_pause_padding(
    text: str,
    extra_secs_needed: float,
    sentence_pause_ms: int = SENTENCE_PAUSE_MS,
) -> int:
    """
    Option (b) for the 'narration too short' case: calculates how much
    extra pause time to insert between sentences to fill the gap, rather
    than requiring the user to write more text.

    Returns the new per-sentence pause duration in milliseconds needed
    to consume the extra time, distributed evenly across sentence gaps.
    """
    sentences = split_into_sentences(text)
    n_gaps = max(1, len(sentences) - 1)
    extra_ms_per_gap = int((extra_secs_needed * 1000) / n_gaps)
    return sentence_pause_ms + extra_ms_per_gap


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: python3 narration.py <text_or_'test'>")
        sys.exit(1)

    if sys.argv[1] == "test":
        # Quick logic test without calling real TTS
        sample_text = (
            "Questa splendida villa unifamiliare si trova in una posizione tranquilla. "
            "Dispone di un ampio soggiorno luminoso e una cucina moderna completamente attrezzata. "
            "Al piano superiore troviamo tre camere da letto spaziose. "
            "Il giardino privato offre uno spazio ideale per rilassarsi all'aperto."
        )
        sentences = split_into_sentences(sample_text)
        print(f"Split into {len(sentences)} sentences:")
        for i, s in enumerate(sentences):
            print(f"  {i}: {s}")

        print()
        result = calculate_scene_durations(
            narration_duration_secs=22.0,
            scene_count=5,
            current_durations=[6, 6, 6, 6, 6],
        )
        print("Duration calculation test:")
        for k, v in result.items():
            print(f"  {k}: {v}")
    else:
        text = sys.argv[1]
        sentences = split_into_sentences(text)
        for i, s in enumerate(sentences):
            print(f"{i}: {s}")
