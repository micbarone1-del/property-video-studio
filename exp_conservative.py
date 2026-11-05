"""exp_conservative.py - round 6 (2026-11-05): which prompt is the SAFEST for the scenes we know are risky? (Michele: "per scene rischiose inevitabili dobbiamo avere in partenza un prompt conservativo")
EXPERIMENT TOOL, NOT PRODUCTION. It reuses exp_facade (same capture of the real production prompt, same 360p draft call, same codes, same key_*.json, same spend file); nothing new is invented.

Scenes: the ones above 30% flagged in risk_table (default list below), or --scenes job:i,job:i. Four variants, blind codes, 2 repetitions each:
  R0  production as it is today (eye-level director). Reference.
  R1  the SAME production chain with the plan forced to STATIC: the almost-static micro-parallax token (what the director already uses for shallow rooms).
  R2  Luma support's recipe for a still scene: "Stationary view of the <room>. Locked off camera."
  R3  production chain, forward plans made minimal (end view scale 1.05, no metres); a static plan stays as in R0. For static scenes R3 == R0 on purpose: two identical prompts measure the pure run-to-run randomness.

  python3 exp_conservative.py run [--scenes job:i,...] [--reps 2] [--budget 4.0] [--go]     without --go: prints the clip count and the cost, spends nothing
Environment: PVS_JOBS_DIR = where the drafts are (test instance: /var/www/pvs_test_jobs), PVS_VOLUME_SCRATCH = where the videos go (production scratch).
--budget is the money THIS run may spend (the spend file is cumulative, so the cap handed to exp_facade is: spent so far + budget).
"""
import json
import sys
from pathlib import Path

import exp_facade as ef
import exp_volume as ev

VARIANTS_R = ("R0", "R1", "R2", "R3")
DEFAULT_SCENES = "e21367fe:1,5b09f3ba:1,e21367fe:2,e7f516e3:4,e21367fe:0,e7f516e3:3,e7f516e3:5"   # flagged 33-60% in risk_table (2026-11-04)


def parse_scenes(text: str) -> list:
    """'job:i,job:i' -> [(job, i)]; a bad item is skipped."""
    out = []
    for part in (text or "").split(","):
        job, _, idx = part.strip().partition(":")
        if job and idx.isdigit():
            out.append((job, int(idx)))
    return out


def static_plan(plan: dict) -> dict:
    """R1: whatever the director chose, the plan becomes the proven almost-static token (the one it already uses for shallow rooms)."""
    import movement_director as md
    import video_generation as vg
    p = dict(plan)
    p.update(move="static", sentence=vg._LUMA_MOVEMENT_TOKENS["subtle_rotate"], scale=md.STATIC_SCALE, target="", travel="short", center=(0.5, 0.5), slow=False)
    return p


def luma_still_prompt(category: str) -> str:
    return f"Stationary view of the {ef.ROOM_LABEL.get(str(category or '').lower(), 'room')}. Locked off camera."


def category_of(job: str, i: int) -> str:
    try:
        meta = json.loads((ev.JOBS_DIR / job / "job_meta.json").read_text())
        sc = (meta.get("scenes_config") or [])[i]
        return str(sc.get("category") or sc.get("room") or "").lower()
    except Exception:
        return ""


def build_cases_r(scenes):
    cases = []
    for job, i in scenes:
        cat = category_of(job, i)
        with ef._env(PVS_DIRECTOR_EYE="1"):
            r0, plan_text, img = ef.capture_prompt(job, i)
            plan = getattr(ef.capture_prompt, "last_plan", None)
            r1, plan1, _ = ef.capture_prompt(job, i, transform=static_plan)
            r3, plan3, _ = ef.capture_prompt(job, i, transform=ef.minimal_plan)
        if not (r0 and r1 and r3 and plan):
            ev.say(f"{job}:{i} no production prompt captured: skipped"); continue
        pr = {"R0": r0, "R1": r1, "R2": luma_still_prompt(cat), "R3": r3}
        pl = {"R0": plan_text, "R1": plan1, "R2": "locked off", "R3": plan3}
        ev.say(f"{job}:{i} [{cat}] R0 plan: {plan_text} | R1: {plan1} | R3: {plan3}\n    R2: {pr['R2']}")
        cases.append({"job": job, "scene": i, "img": str(img), "prompts": pr, "plans": pl})
    return cases


def main(argv) -> int:
    def opt(name, default):
        return argv[argv.index(name) + 1] if name in argv else default
    scenes = parse_scenes(opt("--scenes", DEFAULT_SCENES))
    reps = int(opt("--reps", "2"))
    budget = float(opt("--budget", "4.0"))
    go = "--go" in argv
    n = len(scenes) * len(VARIANTS_R) * reps
    ev.say(f"{len(scenes)} scene(s) x {len(VARIANTS_R)} variants x {reps} reps = {n} clips x {ev.CLIP_USD} = {round(n * ev.CLIP_USD, 2)} USD (budget {budget} USD; the director and the description add a few cents of Claude)")
    if n * ev.CLIP_USD > budget:
        ev.say("the clips alone exceed the budget: refusing"); return 1
    if not go:
        ev.say("Nothing done (no --go)."); return 0
    ef.OUT.mkdir(parents=True, exist_ok=True)
    ev.SPEND = ef.OUT / "spend.json"
    cap_total = ev.spent() + budget
    ev.say(f"spent so far {ev.spent():.2f} USD -> cap handed to exp_facade {cap_total:.2f}")
    ef.facade_scenes = lambda job_ids: scenes                       # exp_facade.run takes its scene list from here (only for the count)
    ef.build_cases = lambda job_ids, max_scenes, variants=None, per_cat=2: build_cases_r(scenes)
    return ef.run(sorted({j for j, _ in scenes}), reps, cap_total, len(scenes), True, variants=VARIANTS_R)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] != "run":
        print(__doc__); sys.exit(1)
    sys.exit(main(sys.argv[2:]))
