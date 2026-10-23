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
