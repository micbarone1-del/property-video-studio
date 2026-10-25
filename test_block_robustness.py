"""Robustness of the block fit across MANY plausible texts (Patch R5, 2026-10-25). No network, no cost.
Generates plausible sentence lengths (what Claude + the voice could produce under the prompt rules: 5-13 words per sentence, 12-23 per block,
the last sentence = fact + 0.6 s pause + 'contatta <agency>', agency names of 2-5 words, voice 2.0-2.4 words/s, +-8..15% noise) and counts how many
the planner can fit on the FIRST attempt. The thresholds are the evidence that the design works in general, not for one draft.
The model is an ASSUMPTION about real texts: the real distribution is measured with the URL battery (test plan level B) and this file is then re-tuned.
Slow (about a minute): run it on its own."""
import math, random, sys
import scene_timing as st
import scene_script as ss

ok_n, fails = 0, []


def check(name, cond, extra=""):
    global ok_n
    if cond:
        ok_n += 1
        print(f"PASS {name}")
    else:
        fails.append(name)
        print(f"FAIL {name} {extra}")


def clip(x, a, b):
    return max(a, min(b, x))


CLOSE_PAUSE = st.CLOSING_PAUSE_SECS


def sample(rng, wps, noise, agency_words=None):
    while True:
        w = [[clip(round(rng.gauss(8.5, 2.0)), 5, 13) for _ in range(2)] for _ in range(3)]
        if all(12 <= sum(b) <= 23 for b in w):
            break
    ag = agency_words or rng.choices([2, 3, 4, 5], [50, 30, 15, 5])[0]
    cb = ss.closing_budget(" ".join(["x"] * ag))              # the budget the prompt gives for this agency name
    c = clip(round(rng.gauss(cb["fact"] - 1.5, 1.5)), ss.LAST_SENTENCE_MIN_FACT_WORDS, cb["fact"])
    nz = lambda: math.exp(rng.gauss(0, noise))
    s = [[w[b][k] / wps * nz() for k in range(2)] for b in range(3)]
    s[2][1] = c / wps * nz() + CLOSE_PAUSE + cb["invitation"] / wps * nz()
    return s


OFF = st.second_sentence_offsets(6)


def old_planner_ok(s):
    rates = [1.0] * 3
    p = None
    for _ in range(4):
        d = [s[b][0] + st.sentence_pause_pre(s[b][0], rates[b], offset=OFF[b]) + s[b][1] for b in range(3)]
        p = st.plan_blocks(d, 6)
        if max(abs(a - b) for a, b in zip(p["rates"], rates)) < 0.006:
            break
        rates = p["rates"]
    if not p["ok"]:
        return False
    so = [(s[b][0] + st.sentence_pause_pre(s[b][0], p["rates"][b], offset=OFF[b])) / p["rates"][b] for b in range(3)]
    return st.plan_from_anchors(st.sentence_anchor_times(p["starts"], so, 6, 2), p["speech_end"], [5.0] * 6)["ok"]


def rate(n, wps, noise, seed):
    rng = random.Random(seed)
    new = old = 0
    for _ in range(n):
        s = sample(rng, wps, noise)
        new += st.plan_blocks_joint(s)["ok"]
        old += old_planner_ok(s)
    return 100.0 * new / n, 100.0 * old / n


N = 50
n1, o1 = rate(N, 2.2, 0.08, 1)
check(f"R1 typical voice (2.2 words/s, +-8%): the joint planner fits >= 95% of first attempts (got {n1:.0f}%, the old pre-filter {o1:.0f}%)", n1 >= 95.0)
check("R2 and it is clearly better than the old pre-filter on the same texts (>= +15 points)", n1 - o1 >= 15.0, (n1, o1))
n2, o2 = rate(N, 2.0, 0.15, 2)
check(f"R3 slow voice and imprecise text (2.0 words/s, +-15%): still >= 80% (got {n2:.0f}%, old {o2:.0f}%)", n2 >= 80.0)
n3, o3 = rate(N, 2.4, 0.08, 3)
check(f"R4 fast voice (2.4 words/s): >= 95% (got {n3:.0f}%, old {o3:.0f}%)", n3 >= 95.0)
n4, _ = rate(N // 2, 2.2, 0.08, 4)
rng = random.Random(5)
long_ag = sum(st.plan_blocks_joint(sample(rng, 2.2, 0.08, agency_words=6))["ok"] for _ in range(N // 2)) * 100.0 / (N // 2)
check(f"R5 a very long agency name (6 words) is still fitted by the word budget (>= 80%, got {long_ag:.0f}%)", long_ag >= 80.0)
print(f"\n{ok_n}/{ok_n + len(fails)} PASS")
sys.exit(1 if fails else 0)
