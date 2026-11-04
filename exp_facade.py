"""exp_facade.py - blind study of the FACADE clip on the 360p draft tier (2026-11-04, Michele: "analizziamo facciate").

Why: in the volume check (drafts 3cfaa75f, c9e60007) the facade clips were wrong: 3cfaa75f scene 0 ran fast and NOT toward the building (the near-target rule written on
2026-11-04 says "aim at the ground in front of the building", the opposite of Michele's 2026-10-25 rule: the facade clip approaches the building); c9e60007 scene 0
had the plan 'static' and the facade still slid sideways fast over the cornice. Three variants on the SAME facade photos, 2 repetitions each, blind codes:
  G  ground    the production prompt as it is today (director near-target text: aim at the ground / drive in front of the building)
  B  building  the same chain, but the director's plan is overridden AFTER it answers: always a very slow forward push-in toward "the base of the front wall of the building"
               (still near, so it can be reached calmly within five seconds, but it is the BUILDING that is approached). The first attempt, changing the director's facade
               sentence, was stopped: the director kept choosing the road / the ground (3cfaa75f) or 'static' (c9e60007), so B would have been the same prompt as G
  S  still     the production prompt of G turned into the locked-off version (exp_prompt_ab.lock: "Stationary view, locked off camera ...")
The prompts of G and B are the REAL production prompts: video_generation.generate_video_single runs unchanged, only the final Luma call is intercepted (its prompt is
captured, nothing is sent, nothing is spent there; the director and the description cost a few cents of Claude). The clips are then generated at 360p with the same
Luma call exp_prompt_ab uses. Drafts are only read. Own spend cap (every started clip counts).

  python3 exp_facade.py plan   JOB1,JOB2,...                       free: lists the facade scenes found ('exterior' scenes)
  python3 exp_facade.py run    JOB1,JOB2,... [--reps 2] [--cap 4.5] [--max-scenes 12] --go
  python3 exp_facade.py reveal RUN_ID
  PVS_JOBS_DIR = where the drafts are (test instance: /var/www/pvs_test_jobs); PVS_VOLUME_SCRATCH = where the videos go (production scratch, served on port 8000)
"""
import json
import os
import random
import string
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import exp_volume as ev

OUT = ev.SCRATCH / "facade"
BUILDING_TARGET = "the base of the front wall of the building"
VARIANTS = ("G", "B", "S")
CATEGORY = "exterior"


def facade_scenes(job_ids) -> list:
    """[(job, scene_index)] of the 'exterior' scenes of the drafts."""
    out = []
    for jid in job_ids:
        try:
            meta = json.loads((ev.JOBS_DIR / jid / "job_meta.json").read_text())
        except Exception:
            continue
        for i, sc in enumerate(meta.get("scenes_config") or []):
            if str(sc.get("category") or sc.get("room") or "").lower() == CATEGORY:
                out.append((jid, i))
    return out


def building_plan(plan: dict) -> dict:
    """The director's plan with its move and target replaced: a very slow forward push-in toward the base of the front wall (travel short, scale of a short travel)."""
    import movement_director as md
    p = dict(plan)
    p.update(move="forward", target=BUILDING_TARGET, travel="short", slow=True, scale=md._clip_scale("short"), sentence=md.forward_sentence(BUILDING_TARGET, True))
    return p


def capture_prompt(job: str, i: int, force_building: bool = False):
    """(prompt, plan text) the production chain would send to Luma for this scene. The Luma call is replaced by a function that only records the prompt."""
    import movement_director as md
    import video_generation as vg
    if not vg.LUMA_DIRECT:
        raise SystemExit("LUMA_DIRECT is off: refusing (the fal.ai path would spend and is not the production path)")
    img, kw, _ = ev.scene_args(job, i)
    got = []
    saved = (vg._generate_luma_direct, vg._generate_luma, vg._generate_veo, vg.FAL_FALLBACK_ENABLED, md.plan)
    vg._generate_luma_direct = lambda image_url, prompt, *a, **k: (got.append(prompt), None)[1]
    vg._generate_luma = vg._generate_veo = lambda *a, **k: None
    vg.FAL_FALLBACK_ENABLED = False
    if force_building:
        real_plan = md.plan
        md.plan = lambda *a, **k: (lambda p: building_plan(p) if p else p)(real_plan(*a, **k))
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / f"cap_{job}_{i}_{''.join(random.choice(string.ascii_lowercase) for _ in range(5))}.mp4"
    try:
        vg.generate_video_single(str(img), 5, str(tmp), **kw)
    finally:
        vg._generate_luma_direct, vg._generate_luma, vg._generate_veo, vg.FAL_FALLBACK_ENABLED, md.plan = saved
    return (got[0] if got else None), ev.plan_text(tmp), img


def build_cases(job_ids, max_scenes):
    import exp_prompt_ab as ab
    cases = []
    for job, i in facade_scenes(job_ids)[:max_scenes]:
        g, gplan, img = capture_prompt(job, i)
        b, bplan, _ = capture_prompt(job, i, True)
        if not g or not b:
            ev.say(f"{job}:{i} no production prompt captured: skipped"); continue
        s, miss = ab.lock(g)
        ev.say(f"{job}:{i} G plan: {gplan}\n{job}:{i} B plan: {bplan}\n{job}:{i} S clauses not found: {miss}")
        cases.append({"job": job, "scene": i, "img": str(img), "prompts": {"G": g, "B": b, "S": s}, "plans": {"G": gplan, "B": bplan, "S": "locked off"}})
    return cases


def run(job_ids, reps, cap, max_scenes, go):
    scenes = facade_scenes(job_ids)
    ev.say(f"{len(scenes)} facade scene(s): {scenes}")
    n_clips = min(len(scenes), max_scenes) * len(VARIANTS) * reps
    ev.say(f"{n_clips} clips x {ev.CLIP_USD} = {round(n_clips * ev.CLIP_USD, 2)} USD (cap {cap})")
    if not go:
        ev.say("Nothing done (no --go)."); return 0
    from dotenv import load_dotenv
    load_dotenv(ev.HERE / ".env")
    ev.OUT = OUT; ev.SPEND = OUT / "spend.json"
    import exp_prompt_ab as ab
    cases = build_cases(job_ids, max_scenes)
    tasks = []
    for c in cases:
        for v in VARIANTS:
            for r in range(reps):
                tasks.append((c, v, r + 1))
    random.shuffle(tasks)
    run_id = time.strftime("%m%d_%H%M%S")
    run_dir = OUT / run_id; run_dir.mkdir(parents=True, exist_ok=True)
    codes, key = set(), []

    def code():
        while True:
            c = "".join(random.choice(string.ascii_lowercase) for _ in range(3))
            if c not in codes:
                codes.add(c); return c
    coded = [(code(), c, v, r) for c, v, r in tasks]

    def one(t):
        cd, c, v, r = t
        if ev.spent() + ev.CLIP_USD > cap:
            return {"code": cd, "case": f"{c['job']}:{c['scene']}", "variant": v, "rep": r, "ok": False, "why": "cap"}
        ev.add_spend(ev.CLIP_USD, f"{c['job']}:{c['scene']} {v}")
        out = run_dir / f"{cd}.mp4"
        ok = ab.generate_luma(Path(c["img"]), c["prompts"][v], out)
        row = {"code": cd, "case": f"{c['job']}:{c['scene']}", "variant": v, "rep": r, "ok": bool(ok and out.exists()), "plan": c["plans"][v], "prompt": c["prompts"][v]}
        if row["ok"]:
            row["speed"] = ev.probe(out)
        ev.say(f"{row['case']} {cd} {'ok' if row['ok'] else 'FAILED'}")
        return row
    with ThreadPoolExecutor(max_workers=3) as ex:
        key = list(ex.map(one, coded))
    (OUT / f"key_{run_id}.json").write_text(json.dumps(key, ensure_ascii=False, indent=1))
    ev.say("=" * 20, "VIDEOS (one per facade scene, codes in yellow; judge each code: hallucination / direction / speed)")
    for c in cases:
        mine = [k for k in key if k["case"] == f"{c['job']}:{c['scene']}" and k["ok"]]
        random.shuffle(mine)
        parts = []
        for k in mine:
            lab = run_dir / f"lab_{k['code']}.mp4"
            if ev.label_clip(run_dir / f"{k['code']}.mp4", lab, k["code"]):
                parts.append(lab)
        name = f"facade_{run_id}_{c['job']}_{c['scene']}.mp4"
        if parts and ev.concat(parts, ev.SCRATCH / name):
            ev.say(f"{c['job']} scena {c['scene']}: {ev.LINK_BASE}/{name}\n   ordine: {' '.join(k['code'] for k in mine)}")
    ev.say(f"RUN {run_id} done. Look at the codes, tell me what you see, THEN: python3 exp_facade.py reveal {run_id}")
    return 0


def reveal(run_id):
    for k in json.loads((OUT / f"key_{run_id}.json").read_text()):
        sp = k.get("speed") or {}
        print(k["code"], k["case"], k["variant"], f"rep{k['rep']}", "ok" if k["ok"] else "FAILED", f"e_all={sp.get('e_all', 0):.2f}", k.get("plan", ""))
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]

    def opt(name, default):
        return a[a.index(name) + 1] if name in a else default
    if len(a) >= 2 and a[0] in ("plan", "run"):
        sys.exit(run([x for x in a[1].split(",") if x], int(opt("--reps", "2")), float(opt("--cap", "4.5")), int(opt("--max-scenes", "12")), a[0] == "run" and "--go" in a))
    elif len(a) >= 2 and a[0] == "reveal":
        sys.exit(reveal(a[1]))
    print(__doc__)
