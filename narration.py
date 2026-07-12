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

# Buffer after narration ends before video ends (seconds) — matches the
# "TTS finishes a couple of seconds before video ends" requirement.
END_BUFFER_SECS = 2.5

# Threshold below which narration is considered "too short" for the
# current total video duration, triggering the red warning + fix options.
TOO_SHORT_THRESHOLD_SECS = 4.0


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


def generate_narration_audio(
    text:            str,
    output_path:     str,
    voice_id:        str = None,
    sentence_pause_ms: int = SENTENCE_PAUSE_MS,
) -> dict:
    """
    Generates the full narration as sentence-split TTS calls, concatenated
    with explicit silence gaps. Returns a dict with success status,
    actual measured duration, and per-sentence timing (useful for
    debugging or future features like highlighting the active sentence).

    This is the ONLY function that should generate narration audio —
    it replaces the old per-scene voiceover generation entirely.
    """
    from voice_generation import generate_speech as generate_voice
    from pydub import AudioSegment

    sentences = split_into_sentences(text)
    if not sentences:
        return {"ok": False, "error": "Empty narration text", "duration_secs": 0}

    log.info(f"[Narration] Splitting into {len(sentences)} sentences for TTS generation")

    tmp_dir = Path(output_path).parent / "_narration_sentences"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    sentence_clips = []
    sentence_timings = []
    current_offset_ms = 0

    try:
        for i, sentence in enumerate(sentences):
            sentence_path = str(tmp_dir / f"sentence_{i:03d}.mp3")
            ok = generate_voice(sentence, sentence_path, voice_id=voice_id)
            if not ok or not os.path.exists(sentence_path):
                log.error(f"[Narration] Failed to generate sentence {i}: {sentence[:50]}")
                return {"ok": False, "error": f"TTS failed on sentence {i+1}", "duration_secs": 0}

            clip = AudioSegment.from_file(sentence_path)
            sentence_clips.append(clip)
            sentence_timings.append({
                "index": i,
                "text": sentence,
                "start_ms": current_offset_ms,
                "duration_ms": len(clip),
            })
            current_offset_ms += len(clip) + sentence_pause_ms

        # Concatenate all sentences with silence gaps between them
        silence = AudioSegment.silent(duration=sentence_pause_ms)
        combined = sentence_clips[0]
        for clip in sentence_clips[1:]:
            combined = combined + silence + clip

        combined.export(output_path, format="mp3")
        total_duration_secs = len(combined) / 1000.0

        log.info(f"[Narration] Generated {len(sentences)} sentences, "
                 f"total duration {total_duration_secs:.1f}s → {output_path}")

        return {
            "ok": True,
            "duration_secs": total_duration_secs,
            "sentence_count": len(sentences),
            "sentence_timings": sentence_timings,
            "output_path": output_path,
        }

    finally:
        # Cleanup individual sentence files — only the combined output matters
        for f in tmp_dir.glob("sentence_*.mp3"):
            try:
                f.unlink()
            except Exception:
                pass
        try:
            tmp_dir.rmdir()
        except Exception:
            pass


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

    target_total = narration_duration_secs + END_BUFFER_SECS

    current_total = sum(current_durations) if current_durations else scene_count * 6

    too_short = narration_duration_secs > 0 and (
        current_total - narration_duration_secs > TOO_SHORT_THRESHOLD_SECS + END_BUFFER_SECS
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
        for i, d in enumerate(new_durations):
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
