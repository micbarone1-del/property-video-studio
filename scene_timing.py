"""The ONE place that turns the MEASURED voice into the video timeline (2026-10-23, backlog 82).

Why this module exists
----------------------
Until now the URL/Relinx standard video worked the other way round: six clips of a fixed 5 s, and the voice had to
fit them (narration.plan_sentence_sync snaps sentences to a 0/5/10/... grid). Two real problems, both found in the
live tests of 2026-10-22:
  1. The grid ignores the 0.5 s cross-fade that video_assembly puts between clips (they overlap), so scene k really
     starts k * 0.5 s earlier than the grid says: the voice trails the pictures by up to 2.5 s on scene 6.
  2. A natural sentence is 4-6 s, not 5.0 s, so every sentence that ran long pushed the next one onto the wrong scene
     (kitchen text over the bedroom clip).

The rule here (Michele, 2026-10-23): the SENTENCE decides how long its scene is. One sentence per scene, or one
sentence over two consecutive scenes. Each clip (generated once, ~5 s) is slowed down / sped up to its slot:
  speed = source seconds / clip seconds, allowed 0.8-1.25 (Michele watched 0.8x and judged it imperceptible).
Nothing is cut (a hard cut at 4 s showed a flash for Michele) and no clip is thrown away.

Timeline model (must match video_assembly's cross-fade concatenation, padding = -TRANSITION_SECS):
  clip i starts at s_i, lasts D_i, clip i+1 starts at s_i + D_i - TRANSITION_SECS.
  The CUT between clips i and i+1 is the middle of the overlap. A sentence starts exactly on the cut of its first
  scene, so   D_i = visible_i + (TRANSITION/2 on each side that has a neighbour).
  The voice may run into the cross-fade (nobody sees the difference), so the pause between sentences can shrink from
  PAUSE to MIN_PAUSE when a sentence is near the limit.

Pure functions only: no audio, no network, no moviepy. api_server / video_assembly / the scraper call it.
"""

TRANSITION_SECS = 0.5      # cross-fade overlap between clips: SAME value video_assembly.TRANSITION_DURATION
SPEED_MIN = 0.8            # slowest allowed (approved by Michele 2026-10-23)
SPEED_MAX = 1.25           # fastest allowed
PAUSE_MS = 380             # normal gap between two sentences: SAME value as narration.SENTENCE_PAUSE_MS
MIN_PAUSE_MS = 100         # shortest gap used when a sentence is near the slow-down limit
LAST_TAIL_SECS = 0.2       # picture kept after the last word (the 1 s blank trail is added later by assembly)
DEFAULT_SRC_SECS = 5.0     # a Luma clip

_EPS = 1e-6


def plan_timeline(sentence_ms, groups, src_secs=None, *, pause_ms=PAUSE_MS, min_pause_ms=MIN_PAUSE_MS,
                  transition=TRANSITION_SECS, speed_min=SPEED_MIN, speed_max=SPEED_MAX,
                  last_tail_secs=LAST_TAIL_SECS):
    """sentence_ms: measured length of each sentence (ms).
    groups: how many consecutive scenes each sentence covers (1 or 2); sum(groups) = number of clips.
    src_secs: real length of each generated clip (None -> DEFAULT_SRC_SECS each).

    Returns {"sentences": [...], "clips": [...], "gaps_ms": [...], "video_secs", "speech_end_secs", "problems": [...],
    "ok"}. The plan is ALWAYS exact for the given sentences (the voice never moves); when a sentence cannot be shown
    within the speed limits the clip is still given the length it needs and the problem is reported so the caller can
    rewrite the sentence (or add a clip) instead of silently drifting.
    """
    n = len(sentence_ms)
    if n == 0 or len(groups) != n or any(g < 1 for g in groups):
        raise ValueError("sentence_ms and groups must be non-empty and the same length, groups >= 1")
    n_clips = sum(groups)
    if src_secs is None:
        src_secs = [DEFAULT_SRC_SECS] * n_clips
    if len(src_secs) != n_clips:
        raise ValueError(f"src_secs has {len(src_secs)} values for {n_clips} clips")

    half = transition / 2.0

    def edges(i):
        return (half if i > 0 else 0.0) + (half if i < n_clips - 1 else 0.0)

    sentences, clips, gaps_ms, problems = [], [], [0], []
    voice_t = 0.0          # start of the current sentence (= its first cut), narration time
    c0 = 0
    for j in range(n):
        speech = sentence_ms[j] / 1000.0
        g = groups[j]
        idx = list(range(c0, c0 + g))
        last_sentence = (j == n - 1)
        minimal = speech + (last_tail_secs if last_sentence else min_pause_ms / 1000.0)
        wanted = speech + (last_tail_secs if last_sentence else pause_ms / 1000.0)
        d_min = [src_secs[i] / speed_max for i in idx]
        d_max = [src_secs[i] / speed_min for i in idx]
        lo = g * max(d_min[k] - edges(i) for k, i in enumerate(idx))   # visible time the fastest allowed speed needs
        hi = g * min(d_max[k] - edges(i) for k, i in enumerate(idx))   # visible time the slowest allowed speed covers
        visible = max(minimal, min(wanted, hi))     # as close to the normal pause as the slow-down limit allows
        if visible < lo:
            visible = lo                            # short sentence: extra silence so the clip is not sped up too much
        pause = visible - speech
        per_clip = visible / g

        first_cut = voice_t
        sentences.append({
            "index": j, "clips": idx, "voice_start": round(voice_t, 3), "voice_end": round(voice_t + speech, 3),
            "pause_after_secs": round(pause, 3), "visible_secs": round(visible, 3),
        })
        for k, i in enumerate(idx):
            d = per_clip + edges(i)
            speed = src_secs[i] / d
            in_range = (speed_min - 1e-3) <= speed <= (speed_max + 1e-3)
            cut = first_cut + k * per_clip              # the cut where this clip becomes the picture
            clips.append({
                "index": i, "sentence": j, "start": round(cut - (half if i > 0 else 0.0), 3),
                "duration": round(d, 3), "speed": round(speed, 4), "in_range": in_range,
                "src_secs": src_secs[i],
            })
            if not in_range:
                problems.append({"sentence": j, "clip": i, "speed": round(speed, 3),
                                 "kind": "too_slow" if speed < speed_min else "too_fast",
                                 "seconds_over": round(max(0.0, d - d_max[k]) if speed < speed_min else max(0.0, d_min[k] - d), 3)})
        gaps_ms.append(int(round(pause * 1000)))
        voice_t += visible
        c0 += g
    gaps_ms = gaps_ms[:n]                               # gaps_ms[j] = silence BEFORE sentence j (0 for the first)

    video_secs = sum(c["duration"] for c in clips) - (n_clips - 1) * transition
    return {
        "sentences": sentences, "clips": clips, "gaps_ms": gaps_ms,
        "video_secs": round(video_secs, 3), "speech_end_secs": sentences[-1]["voice_end"],
        "problems": problems, "ok": not problems,
    }


# ── Anchor-driven timeline (2026-10-23, backlog 82, Patch J) ─────────────────────────────────────────────────
# Michele's refinement (2026-10-23): the requirement is NOT "one sentence per scene" but "when the voice NAMES a room,
# that room is on screen". The text stays one natural narration; only the moment a room is named (an ANCHOR: the time
# of the first word of the phrase that names it, measured on the real audio) pins that scene's picture. Scenes that are
# not named (there is no time for every room in a standard video) just take the space between their neighbours.
# Same cross-fade model as plan_timeline: the CUT between two clips is the middle of their overlap.

LEAD_BEFORE_WORD = 0.35     # the new picture should be fully visible just before the room word: cut = word start - 0.35
EARLY_MAX = 1.0             # a cut may fall at most this much EARLIER than that preferred moment
LATE_MAX = 0.4              # ... or this much LATER (a picture that arrives after the word is worse than one before it)
END_TAIL_SECS = 0.2         # picture kept after the last word (the 1 s blank trail is added later by assembly)
MAX_EXTRA_END_SECS = 8.0    # the video may run at most this long after the voice ended (a very short text)


def plan_from_anchors(anchor_times, speech_end_secs, src_secs=None, *, transition=TRANSITION_SECS,
                      speed_min=SPEED_MIN, speed_max=SPEED_MAX, lead_before=LEAD_BEFORE_WORD,
                      early=EARLY_MAX, late=LATE_MAX, tail=END_TAIL_SECS, max_extra_end=MAX_EXTRA_END_SECS):
    """anchor_times: one entry per scene/clip, None = not named (or scene 0, which always starts at 0); otherwise the time
    (seconds on the narration) at which the phrase that names the room starts.
    speech_end_secs: when the voice ends. src_secs: real length of each generated clip (None -> 5 s each).

    Picks the cuts closest to the preferred moments that keep EVERY clip inside the speed limits, by interval
    propagation along the chain of cuts (exact, no search). Returns
    {"ok", "feasible", "cuts", "clips", "targets", "video_secs", "speech_end_secs", "anchors", "problems"}.
    When no plan can keep every speed inside the limits, ok=False and the closest plan is still returned with the
    problems listed (clip, speed, kind, seconds_over), so the caller can rewrite the text instead of drifting."""
    n = len(anchor_times)
    if n < 1 or speech_end_secs is None or speech_end_secs <= 0:
        raise ValueError("anchor_times must not be empty and speech_end_secs must be > 0")
    if src_secs is None:
        src_secs = [DEFAULT_SRC_SECS] * n
    if len(src_secs) != n:
        raise ValueError(f"src_secs has {len(src_secs)} values for {n} clips")
    half = transition / 2.0

    def edges(i):
        return (half if i > 0 else 0.0) + (half if i < n - 1 else 0.0)

    vis_lo = [src_secs[i] / speed_max - edges(i) for i in range(n)]    # shortest visible time (fastest allowed speed)
    vis_hi = [src_secs[i] / speed_min - edges(i) for i in range(n)]    # longest visible time (slowest allowed speed)

    # preferred cuts: c_0 = 0, c_n = speech end + tail, named scenes just before their word, the others spread evenly
    pref = [None] * (n + 1)
    pref[0] = 0.0
    pref[n] = float(speech_end_secs) + tail
    for i in range(1, n):
        if anchor_times[i] is not None:
            pref[i] = max(0.0, float(anchor_times[i]) - lead_before)
    known = [i for i in range(n + 1) if pref[i] is not None]
    for a, b in zip(known, known[1:]):
        for i in range(a + 1, b):
            pref[i] = pref[a] + (pref[b] - pref[a]) * (i - a) / (b - a)

    INF = float("inf")
    win = [(0.0, 0.0)] + [((pref[i] - early, pref[i] + late) if (i < n and anchor_times[i] is not None) else (-INF, INF))
                          for i in range(1, n)] + [(pref[n], pref[n] + max_extra_end)]

    # backward pass: the interval each cut can take so that every later clip can still be inside its limits
    R = [None] * (n + 1)
    R[n] = win[n]
    feasible = True
    for i in range(n - 1, -1, -1):
        lo = max(win[i][0], R[i + 1][0] - vis_hi[i])
        hi = min(win[i][1], R[i + 1][1] - vis_lo[i])
        if lo > hi + 1e-9:
            feasible = False
            break
        R[i] = (lo, hi)

    cuts = [0.0] * (n + 1)
    if feasible:
        for i in range(1, n + 1):
            lo = max(R[i][0], cuts[i - 1] + vis_lo[i - 1])
            hi = min(R[i][1], cuts[i - 1] + vis_hi[i - 1])
            if lo > hi + 1e-9:          # cannot happen when the backward pass succeeded; kept as a safety net
                feasible = False
                break
            cuts[i] = min(max(pref[i], lo), hi)
    if not feasible:
        cuts = [0.0] * (n + 1)
        for i in range(1, n + 1):
            cuts[i] = max(cuts[i - 1] + 0.5, pref[i])      # closest plan: preferred moments, kept in order

    clips, problems = [], []
    for i in range(n):
        visible = cuts[i + 1] - cuts[i]
        d = visible + edges(i)
        speed = src_secs[i] / d
        in_range = (speed_min - 1e-3) <= speed <= (speed_max + 1e-3)
        clips.append({"index": i, "start": round(cuts[i] - (half if i > 0 else 0.0), 3), "duration": round(d, 3),
                      "speed": round(speed, 4), "in_range": in_range, "src_secs": src_secs[i],
                      "visible_secs": round(visible, 3)})
        if not in_range:
            too_slow = speed < speed_min
            problems.append({"clip": i, "speed": round(speed, 3), "kind": "too_slow" if too_slow else "too_fast",
                             "visible_secs": round(visible, 3), "allowed_visible": [round(vis_lo[i], 3), round(vis_hi[i], 3)],
                             "seconds_over": round(visible - vis_hi[i], 3) if too_slow else round(vis_lo[i] - visible, 3)})
    anchors = []
    for i in range(1, n):
        if anchor_times[i] is not None:
            anchors.append({"scene": i, "word_at": round(float(anchor_times[i]), 3), "cut": round(cuts[i], 3),
                            "picture_full_at": round(cuts[i] + half, 3),
                            "offset_secs": round(cuts[i] + half - float(anchor_times[i]), 3)})   # < 0: picture before the word
    return {"ok": not problems, "feasible": feasible, "cuts": [round(c, 3) for c in cuts], "clips": clips,
            "targets": [c["duration"] for c in clips], "video_secs": round(cuts[n], 3),
            "speech_end_secs": round(float(speech_end_secs), 3), "anchors": anchors, "problems": problems}


# ── Block narration (2026-10-24, Patch Q) ──────────────────────────────────────────────────────────────────
# The VIDEO leads (6 Luma clips of 5 s, as in automatic dubbing the picture timing is the target). The voice is written and
# recorded in BLOCKS of two scenes; each block is measured on its own, then fitted to its slot with the levers a dubbing
# pipeline uses: the pause between blocks, a small tempo change of the block (pitch preserved) and, last, the speed of the
# single clips (plan_from_anchors, unchanged, which also gives the cut points).
BLOCK_SCENES = 2              # scenes per block
BLOCK_RATE_MIN = 0.92         # slowest tempo of a block (voice slightly slower)
BLOCK_RATE_MAX = 1.10         # fastest tempo of a block (barely audible)
BLOCK_MIN_GAP_SECS = 0.30     # shortest silence between two blocks
BLOCK_MAX_GAP_SECS = 1.60     # longest silence between two blocks (more would be dead air)
END_EARLY_SECS = 2.5          # the voice may end this long before the picture ends at normal speed
END_LATE_SECS = 0.8           # ... or this long after it (the last clips are slowed a little)


def block_nominal_starts(n_scenes=6, per_block=BLOCK_SCENES, src=DEFAULT_SRC_SECS, transition=TRANSITION_SECS,
                         lead_before=LEAD_BEFORE_WORD):
    """Where each block should start (narration time, 0 = start of scene 1) when every clip runs at normal speed, and when
    the picture ends. A block after the first starts just after the cut of its first scene (same lead as the room words)."""
    half = transition / 2.0
    cuts = [0.0]
    for i in range(n_scenes):
        cuts.append(cuts[-1] + src - (half if i > 0 else 0.0) - (half if i < n_scenes - 1 else 0.0))
    n_blocks = n_scenes // per_block
    starts = [0.0] + [cuts[b * per_block] + lead_before for b in range(1, n_blocks)]
    return starts, cuts[-1]


def plan_blocks(durations, n_scenes=6, per_block=BLOCK_SCENES, rate_min=BLOCK_RATE_MIN, rate_max=BLOCK_RATE_MAX,
                min_gap=BLOCK_MIN_GAP_SECS, max_gap=BLOCK_MAX_GAP_SECS, early=EARLY_MAX, late=LATE_MAX,
                end_early=END_EARLY_SECS, end_late=END_LATE_SECS):
    """durations: the measured length (seconds, normal tempo) of each block's audio. Chooses, block after block, a tempo
    inside [rate_min, rate_max] (as close to 1.0 as the slot allows) and the start of the next block (as close as possible to
    its nominal start, inside the same early/late window the cuts use), with a silence between blocks of min_gap..max_gap.
    Returns {"ok", "starts", "rates", "ends", "speech_end", "problems"}; a problem is
    {"block": j (0-based), "kind": "too_long" | "too_short", "seconds_over": float} = how many seconds of audio (at the fastest /
    slowest allowed tempo) the block is outside its slot, so the text can be rewritten by a known amount."""
    nominal, video_end = block_nominal_starts(n_scenes, per_block)
    nb = len(nominal)
    if len(durations) != nb:
        raise ValueError(f"{len(durations)} durations for {nb} blocks")
    starts, rates, ends, problems = [0.0], [], [], []
    for j in range(nb):
        d, s = float(durations[j]), starts[j]
        if j < nb - 1:
            lo_s, hi_s = nominal[j + 1] - early, nominal[j + 1] + late
            r_lo = d / (hi_s - min_gap - s) if hi_s - min_gap - s > _EPS else float("inf")        # at least this tempo to end in time
            r_hi = d / (lo_s - max_gap - s) if lo_s - max_gap - s > _EPS else float("inf")        # at most this tempo to not leave dead air
        else:
            lo_e, hi_e = video_end - end_early, video_end + end_late
            r_lo = d / (hi_e - s) if hi_e - s > _EPS else float("inf")
            r_hi = d / (lo_e - s) if lo_e - s > _EPS else float("inf")
        lower, upper = max(rate_min, r_lo), min(rate_max, r_hi)
        if lower > upper + 1e-9:
            if r_lo > rate_max:      # even at the fastest tempo it ends too late
                over = d / rate_max - (d / r_lo)
                problems.append({"block": j, "kind": "too_long", "seconds_over": round(over, 3)})
                rate = rate_max
            else:                    # even at the slowest tempo it ends too early
                over = d / r_hi - d / rate_min
                problems.append({"block": j, "kind": "too_short", "seconds_over": round(over, 3)})
                rate = rate_min
        else:
            rate = min(max(1.0, lower), upper)
        if abs(rate - 1.0) < 0.005:
            rate = 1.0
        rates.append(round(rate, 4))
        end = s + d / rate
        ends.append(end)
        if j < nb - 1:
            a, b = max(end + min_gap, lo_s), min(end + max_gap, hi_s)
            blocked = problems and problems[-1]["block"] == j
            starts.append(nominal[j + 1] if (blocked or a > b) else min(max(nominal[j + 1], a), b))
    return {"ok": not problems, "starts": [round(x, 4) for x in starts], "rates": rates, "ends": [round(x, 4) for x in ends],
            "speech_end": round(ends[-1], 4), "problems": problems}


# ── Sentence level inside a block (2026-10-24, Patch R) ───────────────────────────────────────────────────────
# Each block has exactly two sentences: the first is heard while the block's first scene is shown, the second while the
# second scene is shown. The silence between the two sentences is the lever that puts the second sentence on the cut of its
# scene: it starts SECOND_OFFSET seconds after the block starts (= one clip minus one cross-fade, the distance between two cuts).
SECOND_OFFSET_SECS = DEFAULT_SRC_SECS - TRANSITION_SECS       # 4.5
SENT_PAUSE_MIN_SECS = 0.25                                    # shortest silence between the two sentences of a block
CLOSING_PAUSE_SECS = 0.60      # Patch R4 (Michele 2026-10-25): the closing invitation ("Contatta <agency>") is its own sentence after this silence
SENT_PAUSE_MAX_SECS = 1.60                                    # longest (more would be dead air)


def second_sentence_offsets(n_scenes=6, per_block=BLOCK_SCENES, src=DEFAULT_SRC_SECS, transition=TRANSITION_SECS, lead_before=LEAD_BEFORE_WORD):
    """Where the second sentence of each block should start, relative to its block start, so that it falls just after the cut
    of the block's second scene: 5.1 s for the first block (the first clip has no cross-fade on its left, so it is longer),
    4.5 s for the others."""
    starts, _ = block_nominal_starts(n_scenes, per_block, src, transition, lead_before)
    half = transition / 2.0
    cuts = [0.0]
    for i in range(n_scenes):
        cuts.append(cuts[-1] + src - (half if i > 0 else 0.0) - (half if i < n_scenes - 1 else 0.0))
    return [round(cuts[b * per_block + 1] + lead_before - starts[b], 4) for b in range(len(starts))]


def sentence_pause(first_secs, rate, offset=SECOND_OFFSET_SECS, lo=SENT_PAUSE_MIN_SECS, hi=SENT_PAUSE_MAX_SECS):
    """The silence (seconds, AFTER the tempo change) that makes the second sentence start `offset` s after the block
    starts, given the length of the first sentence at normal tempo and the block's tempo. Clamped to lo..hi."""
    return min(max(float(offset) - float(first_secs) / float(rate), lo), hi)


def sentence_pause_pre(first_secs, rate, **kw):
    """The same silence as it must be written BEFORE the tempo change (the block is stretched as a whole, silence included)."""
    return sentence_pause(first_secs, rate, **kw) * float(rate)


def sentence_anchor_times(starts, second_offsets, n_scenes=6, per_block=BLOCK_SCENES):
    """Anchor list for plan_from_anchors: every scene except the first is tied to the sentence that talks about it.
    starts: start of each block (narration time); second_offsets: where the second sentence of each block starts, relative
    to its block start. Scene index b*per_block is the block start, b*per_block+1 the second sentence."""
    out = [None] * n_scenes
    for b, s in enumerate(starts):
        if b > 0:
            out[b * per_block] = float(s)
        out[b * per_block + 1] = float(s) + float(second_offsets[b])
    return out
