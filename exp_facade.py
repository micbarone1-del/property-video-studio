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

Round 2 (2026-11-04, after the blind judgement of run 1104_144423: G 5 clearly bad, B 9 good / 2 bad / 3 partial, S not really still and people/cars invented):
  D1  the director with the ORIGINAL facade rule (PVS_DIRECTOR_NEAR=0: toward the building, Michele's 2026-10-25 rule), a MINIMAL move (end view scale 1.05 instead of 1.12, a sentence
      without metres: the anchor ends only slightly larger in the frame) and the outdoor FROZEN-SCENE rule (buildings, vehicles, trees, signs and any figure fixed in place)
  D2  the same director and the same frozen-scene rule, but the normal move of today (scale 1.12, the old sentence): separates the effect of the rule from the effect of the small move
Round 3 (2026-11-04, Michele: "dobbiamo usare tutte le raccomandazioni"): L = the camera-only prompt Luma's support recommended (one sentence, no room description, no metres, no rules, no
  move/movement/down words, no names of things that can move, no rotation: a static plan becomes "Stationary view of the [room]. Locked off camera."), P = the production prompt of today.
  The anchor stays what the director chooses for each scene (not one fixed target). Compare with the G/B/S judgements already given.

  python3 exp_facade.py plan   JOB1,JOB2,... [--set d]            free: lists the facade scenes found ('exterior' scenes)
  python3 exp_facade.py run    JOB1,JOB2,... [--set d] [--reps 2] [--cap 4.5] [--max-scenes 12] --go     --set d = round 2 (D1, D2); --set l [--per-cat 2] = round 3 (P production vs L Luma-recommended, scenes of ALL categories); default = round 1 (G, B, S)
  python3 exp_facade.py reveal RUN_ID
  PVS_JOBS_DIR = where the drafts are (test instance: /var/www/pvs_test_jobs); PVS_VOLUME_SCRATCH = where the videos go (production scratch, served on port 8000)
"""
import json
import os
import random
import re
import string
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import exp_volume as ev

OUT = ev.SCRATCH / "facade"
BUILDING_TARGET = "the base of the front wall of the building"
VARIANTS = ("G", "B", "S")
VARIANTS_D = ("D1", "D2")
VARIANTS_L = ("P", "L")      # round 3: P = production prompt as it is today, L = the prompt Luma's support recommended (camera only)
ROOM_LABEL = {"living": "living room", "kitchen": "kitchen", "bedrooms": "bedroom", "bathrooms": "bathroom", "exterior": "building facade", "outdoor": "terrace"}
FORBIDDEN = re.compile(r"\b(move|moves|moving|moved|movement|movements|down)\b", re.I)                      # Luma support 2026-11-04: the model assigns these to the camera / pulls things into motion
MOVABLE = re.compile(r"\b(curtains?|plants?|water|trees?|flags?|vehicles?|cars?|people|persons?|figures?|wind)\b", re.I)   # Luma support: do not name things that can move
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


FROZEN_OUTDOOR = ("frozen photograph of a still outdoor scene: every building, wall, balcony, window, door, gate, parked vehicle, tree, sign, flag, shadow and every figure present "
                  "is fixed in its place and keeps exactly the same")
_FROZEN_RE = re.compile(r"frozen photograph of [^:]*:\s*every .*?keeps exactly the same", re.S | re.I)


def frozen_outdoor(prompt: str) -> tuple:
    """(prompt with the interior list of fixed things replaced by the outdoor one, 1 if the clause was NOT found). Positive wording only: nothing says 'no people'."""
    new, n = _FROZEN_RE.subn(FROZEN_OUTDOOR, prompt, count=1)
    return new, (0 if n else 1)


def minimal_sentence(target: str) -> str:
    """Round 2 move sentence: no metres (Luma does not measure them), the goal is a framing: the anchor ends only slightly larger than at the start."""
    import movement_director as md
    return (f"Extremely slow, barely perceptible straight forward camera push-in toward {target}, the camera keeps the same height and direction, "
            f"{target} ends only slightly larger in the frame than at the start, {md.TAIL}")


def minimal_plan(plan: dict) -> dict:
    """D1: when the director chose a forward move, keep ITS anchor and make the move minimal (end view scale 1.05); any other plan is left as it is."""
    import movement_director as md
    p = dict(plan)
    if p.get("move") == "forward" and p.get("target"):
        p.update(slow=True, travel="short", scale=md.STATIC_SCALE, sentence=minimal_sentence(p["target"]))
    return p


class _env:
    def __init__(self, **kw):
        self.kw = kw
    def __enter__(self):
        self.old = {k: os.environ.get(k) for k in self.kw}
        os.environ.update(self.kw)
    def __exit__(self, *a):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def lint(prompt: str) -> dict:
    """{'forbidden': [...], 'movable': [...]}: the words Luma's support advised against, found in a prompt (deterministic, free)."""
    return {"forbidden": sorted({m.group(0).lower() for m in FORBIDDEN.finditer(prompt)}), "movable": sorted({m.group(0).lower() for m in MOVABLE.finditer(prompt)})}


def l_prompt(plan: dict, category: str) -> tuple:
    """(prompt L, 1 if the director's move was not a plain forward one and became a locked-off shot). Camera only; no room description, no metres, no rules, no negations.
    Rotation and sideways glides are avoided (Luma support), so they become the 'Stationary view ... Locked off camera' recipe."""
    room = ROOM_LABEL.get(str(category or "").lower(), "room")
    if plan and plan.get("move") == "forward" and plan.get("target"):
        return f"Slow steady forward push-in toward {plan['target']}.", 0
    return f"Stationary view of the {room}. Locked off camera.", 1


def pick_scenes(job_ids, per_cat: int) -> list:
    """[(job, scene, category)]: up to per_cat scenes of EACH category over the drafts, in draft order."""
    seen, out = {}, []
    for jid in job_ids:
        try:
            meta = json.loads((ev.JOBS_DIR / jid / "job_meta.json").read_text())
        except Exception:
            continue
        for i, sc in enumerate(meta.get("scenes_config") or []):
            cat = str(sc.get("category") or sc.get("room") or "").lower()
            if cat and seen.get(cat, 0) < per_cat:
                seen[cat] = seen.get(cat, 0) + 1
                out.append((jid, i, cat))
    return out


def capture_prompt(job: str, i: int, force_building: bool = False, transform=None):
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
    used = []      # the plan the chain REALLY used (the director's history file holds its own answer, before any override)
    real_plan = md.plan

    def recording_plan(*a, **k):
        p = real_plan(*a, **k)
        if p and force_building:
            p = building_plan(p)
        elif p and transform:
            p = transform(p)
        used.append(p)
        return p
    md.plan = recording_plan
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / f"cap_{job}_{i}_{''.join(random.choice(string.ascii_lowercase) for _ in range(5))}.mp4"
    try:
        vg.generate_video_single(str(img), 5, str(tmp), **kw)
    finally:
        vg._generate_luma_direct, vg._generate_luma, vg._generate_veo, vg.FAL_FALLBACK_ENABLED, md.plan = saved
    pl = used[-1] if used else None
    capture_prompt.last_plan = pl          # the plan dict itself (round 3 builds prompt L from it)
    return (got[0] if got else None), (f"{pl.get('move')} -> {pl.get('target')}" if pl else "?"), img


def build_cases_l(scenes):
    """Round 3: P (production prompt of today) and L (camera-only) for each scene. Exterior scenes use the director with the ORIGINAL facade rule (PVS_DIRECTOR_NEAR=0) for BOTH."""
    cases = []
    for job, i, cat in scenes:
        env = {"PVS_DIRECTOR_NEAR": "0"} if cat in ("exterior", "outdoor") else {}
        with _env(**env):
            pp, pplan, img = capture_prompt(job, i)
        plan = getattr(capture_prompt, "last_plan", None)
        if not pp or not plan:
            ev.say(f"{job}:{i} no production prompt captured: skipped"); continue
        lp, became_static = l_prompt(plan, cat)
        ev.say(f"{job}:{i} [{cat}] plan: {pplan}{' -> L locked off' if became_static else ''}\n    L: {lp}\n    lint P {lint(pp)} | lint L {lint(lp)}")
        cases.append({"job": job, "scene": i, "img": str(img), "prompts": {"P": pp, "L": lp}, "plans": {"P": pplan, "L": "locked off" if became_static else pplan}})
    return cases


def build_cases(job_ids, max_scenes, variants=VARIANTS, per_cat=2):
    import exp_prompt_ab as ab
    cases = []
    if variants == VARIANTS_L:
        return build_cases_l(pick_scenes(job_ids, per_cat)[:max_scenes])
    for job, i in facade_scenes(job_ids)[:max_scenes]:
        if variants == VARIANTS_D:
            with _env(PVS_DIRECTOR_NEAR="0"):        # the original facade rule: toward the building (Michele 2026-10-25)
                d2, d2plan, img = capture_prompt(job, i)
                d1, d1plan, _ = capture_prompt(job, i, transform=minimal_plan)
            if not d1 or not d2:
                ev.say(f"{job}:{i} no production prompt captured: skipped"); continue
            d1, m1 = frozen_outdoor(d1); d2, m2 = frozen_outdoor(d2)
            ev.say(f"{job}:{i} D1 plan used: {d1plan}\n    D1 prompt starts: {d1[:170]}\n{job}:{i} D2 plan used: {d2plan}\n    frozen clause not found: D1 {m1} D2 {m2}")
            cases.append({"job": job, "scene": i, "img": str(img), "prompts": {"D1": d1, "D2": d2}, "plans": {"D1": d1plan, "D2": d2plan}})
            continue
        g, gplan, img = capture_prompt(job, i)
        b, bplan, _ = capture_prompt(job, i, True)
        if not g or not b:
            ev.say(f"{job}:{i} no production prompt captured: skipped"); continue
        s, miss = ab.lock(g)
        ev.say(f"{job}:{i} G plan used: {gplan}\n    G prompt starts: {g[:150]}\n{job}:{i} B plan used: {bplan}\n    B prompt starts: {b[:150]}\n{job}:{i} S clauses not found: {miss}")
        cases.append({"job": job, "scene": i, "img": str(img), "prompts": {"G": g, "B": b, "S": s}, "plans": {"G": gplan, "B": bplan, "S": "locked off"}})
    return cases


def run(job_ids, reps, cap, max_scenes, go, variants=VARIANTS, per_cat=2):
    scenes = pick_scenes(job_ids, per_cat) if variants == VARIANTS_L else facade_scenes(job_ids)
    ev.say(f"{len(scenes)} facade scene(s): {scenes}")
    n_clips = min(len(scenes), max_scenes) * len(variants) * reps
    ev.say(f"{n_clips} clips x {ev.CLIP_USD} = {round(n_clips * ev.CLIP_USD, 2)} USD (cap {cap})")
    if not go:
        ev.say("Nothing done (no --go)."); return 0
    from dotenv import load_dotenv
    load_dotenv(ev.HERE / ".env")
    ev.OUT = OUT; ev.SPEND = OUT / "spend.json"
    import exp_prompt_ab as ab
    cases = build_cases(job_ids, max_scenes, variants, per_cat)
    tasks = []
    for c in cases:
        for v in variants:
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
        name = f"{'lum' if variants == VARIANTS_L else 'facade'}_{run_id}_{c['job']}_{c['scene']}.mp4"
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
        sys.exit(run([x for x in a[1].split(",") if x], int(opt("--reps", "2")), float(opt("--cap", "4.5")), int(opt("--max-scenes", "12")), a[0] == "run" and "--go" in a, {"d": VARIANTS_D, "l": VARIANTS_L}.get(opt("--set", ""), VARIANTS), int(opt("--per-cat", "2"))))
    elif len(a) >= 2 and a[0] == "reveal":
        sys.exit(reveal(a[1]))
    print(__doc__)
