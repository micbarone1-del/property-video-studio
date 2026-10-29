"""Luma fidelity experiments (2026-10-26). Michele's budget: EUR 10 MAX in total. Spends real money ONLY with --go, and refuses any run
that would take the running total (jobs/_test_scratch/exp_spend.json) above the cap. Writes ONLY into jobs/_test_scratch/ (never into a job).

  python3 exp_luma.py list  JOB                     scenes of a job: index, movement, QC remarks, which picture would be used (free)
  python3 exp_luma.py run   JOB INDEX VARIANT       shows the cost and stops (free)
  python3 exp_luma.py run   JOB INDEX VARIANT --go  generates ONE clip (~EUR 1.10) and prints light + full links
VARIANT: base (today's prompt) | strict (stricter prompt, no end frame) | straight (strict + no rotation, short straight travel) | subtle (strict + subtle_rotate) | target (strict + straight push-in toward the centre, no sideways) | anchor (strict + straight approach toward the thing Claude names at the centre of the photo, for ANY movement) | anchormove (strict + the scene's OWN movement expressed relative to the anchor: push-in, turn toward it, or arc around it) | pair (strict + first AND last frame = two equal crops of the photo; only for sideways/rotating movements)
"""
import json
import os
import sys
import time
from pathlib import Path

CAP_EUR = 12.2   # 2026-10-29: +2.2 EUR approved by Michele to confirm the root cause of the exterior defect
HERE = Path(__file__).resolve().parent
JOBS_DIR = Path(os.environ.get("PVS_JOBS_DIR") or (HERE / "jobs"))
SCRATCH = JOBS_DIR / "_test_scratch"
SPEND = SCRATCH / "exp_spend.json"
STRAIGHT_ADD = (", camera moves strictly along a single forward axis, no lateral drift, no panning, no pivoting, no rotation, "
                "the field of view stays fixed and centered throughout the shot, the camera advances less than one meter in total")   # = the portrait anti-drift text of assemble_pov_prompt + a short travel
import camera_plan
TARGET_MOTION = camera_plan.CENTRE_MOTION
STILL_ADD = ("plants, foliage, curtains and every other object in the room stay perfectly still and never appear, grow, move or sway, only the camera moves, the foreground of the last frame contains exactly what the photo contains")
STRICT_ADD = camera_plan.ANCHOR_STRICT   # the same first-frame text production adds in anchor mode
ANCHOR_MOTION = camera_plan.ANCHOR_MOTION   # one text, shared with production
VARIANTS = ("base", "still", "strict", "straight", "pair", "subtle", "target", "anchor", "anchormove", "plain", "plainsubtle", "orig")
# ONE implementation of the anchor texts and parsing: camera_plan (production reads the same functions)
import camera_plan as _cp
parse_anchor_side = _cp.parse_anchor_answer
anchor_motion_for = _cp.anchor_motion_for


def _production_answer(image_path):
    """'anchor | side' from the PRODUCTION photo analysis (vision_analysis.analyse_input with the switch on): the experiments use the very same
    prompt, rules and filters as the app, never a private copy. None when Claude names no usable anchor."""
    import vision_analysis
    old = os.environ.get("PVS_ANCHOR")
    os.environ["PVS_ANCHOR"] = "1"
    try:
        r = vision_analysis.analyse_input(str(image_path))
    finally:
        if old is None:
            os.environ.pop("PVS_ANCHOR", None)
        else:
            os.environ["PVS_ANCHOR"] = old
    a = r.get("anchor") or ""
    return f"{a} | {r.get('anchor_side') or 'center'}" if a else None


def anchor_side_of(image_path, ask=None):
    """(anchor, side) or ('', '')."""
    try:
        return parse_anchor_side((ask or _production_answer)(image_path))
    except Exception:
        return "", ""


def anchor_phrase(image_path, ask=None) -> str:
    return anchor_side_of(image_path, ask)[0]


def est_eur() -> float:
    import cost_tracker as ct
    return round(ct.LUMA_DIRECT_USD_PER_CLIP * ct.USD_TO_EUR, 2)


def spent() -> float:
    try:
        return float(json.loads(SPEND.read_text()).get("total_eur", 0.0))
    except Exception:
        return 0.0


def add_spend(eur: float, note: str):
    SCRATCH.mkdir(parents=True, exist_ok=True)
    try:
        d = json.loads(SPEND.read_text())
    except Exception:
        d = {"total_eur": 0.0, "runs": []}
    d["total_eur"] = round(d["total_eur"] + eur, 2)
    d["runs"].append({"eur": eur, "note": note, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    SPEND.write_text(json.dumps(d, indent=1))


def can_spend(eur: float):
    """(ok, message). The cap is checked BEFORE every generation."""
    now = spent()
    if now + eur > CAP_EUR + 1e-9:
        return False, f"STOP: speso {now:.2f} + {eur:.2f} supererebbe il tetto di {CAP_EUR:.2f} EUR"
    return True, f"speso finora {now:.2f} EUR, questa prova ~{eur:.2f} EUR, dopo ~{now + eur:.2f} di {CAP_EUR:.2f}"


def load_scene(job: str, index: int) -> dict:
    meta = json.loads((JOBS_DIR / job / "job_meta.json").read_text())
    cfg = meta.get("scenes_config") or []
    sc = cfg[index]
    sid = sc.get("scene_id")
    jd = JOBS_DIR / job
    cands = [jd / "enhanced" / f"scene_{index:03d}_enhanced_lit.jpg", jd / "enhanced" / f"scene_{index:03d}_enhanced.jpg"]
    cands += [jd / "images" / f"{sid}{e}" for e in (".jpg", ".jpeg", ".png", ".webp")] if sid else []
    cands += [jd / "images" / f"scene_{index:03d}{e}" for e in (".jpg", ".jpeg", ".png", ".webp")]
    img = next((c for c in cands if c.exists()), None)
    qc = [q for q in (meta.get("qc_results") or []) if q.get("scene") == index and q.get("type") == "video"]
    return {"scene": sc, "image": img, "qc": qc, "meta": meta}


def plain_image(job: str, index: int, raw: bool = False):
    """2026-10-29 (variant plain): the photo AFTER watermark removal but WITHOUT the lighting correction and WITHOUT the aura-sr 4x upscale,
    only a plain Lanczos resize to 1920 px wide. Written in the scratch folder. None if neither file exists."""
    from PIL import Image
    jd = JOBS_DIR / job
    meta = json.loads((jd / "job_meta.json").read_text())
    sid = (meta.get("scenes_config") or [])[index].get("scene_id")
    cands = ([] if raw else [jd / "enhanced" / f"scene_{index:03d}_dewatermarked.jpg"]) + [jd / "images" / f"{sid}{e}" for e in (".jpg", ".jpeg", ".png")] \
        + [jd / "images" / f"scene_{index:03d}.jpg"]
    src = next((c for c in cands if c.exists()), None)
    if not src:
        return None
    im = Image.open(src).convert("RGB")
    w, h = im.size
    if w < 1920:
        im = im.resize((1920, round(h * 1920 / w)), Image.LANCZOS)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    out = SCRATCH / f"{'orig' if raw else 'plain'}_{job}_{index}.jpg"
    im.save(out, quality=95)
    print(f"foto usata: {src.name} {w}x{h} -> {out.name} {im.size[0]}x{im.size[1]} (nessuna correzione luce, nessun aura-sr)")
    return out


def cmd_list(job: str):
    meta = json.loads((JOBS_DIR / job / "job_meta.json").read_text())
    for i, sc in enumerate(meta.get("scenes_config") or []):
        s = load_scene(job, i)
        issues = "; ".join(x for q in s["qc"] for x in (q.get("issues") or [])) or "-"
        print(f"scena {i}: {sc.get('pov_movement')} / {sc.get('space_type')} | {(sc.get('caption') or '')[:30]} | QC: {issues[:110]} | foto: {s['image'].name if s['image'] else 'NON TROVATA'}")
    print(f"speso nelle prove finora: {spent():.2f} EUR (tetto {CAP_EUR:.2f})")


def cmd_run(job: str, index: int, variant: str, go: bool, generate=None, anchor_ask=None):
    if variant not in VARIANTS:
        print("variante non valida:", variant, VARIANTS); return 2
    s = load_scene(job, index)
    if variant in ("plain", "plainsubtle", "orig"):
        s["image"] = plain_image(job, index, raw=(variant == "orig"))
    if not s["image"]:
        print("foto non trovata"); return 2
    if variant == "pair":
        import camera_plan
        mv = s["scene"].get("pov_movement", "walk_in_explore")
        if mv not in camera_plan.FRAME_PAIR:
            print(f"La scena usa '{mv}': un movimento in avanti, senza coppia di fotogrammi. Nessuna generazione, nessuna spesa. Movimenti con coppia: {', '.join(camera_plan.FRAME_PAIR)}")
            return 4
    eur = est_eur()
    ok, msg = can_spend(eur)
    print(msg)
    if not ok:
        return 3
    if not go:
        print("Nessuna generazione (manca --go). Per generare aggiungi --go in fondo.")
        return 0
    import video_generation as vg
    if variant == "still":
        vg._LUMA_RULES = vg._LUMA_RULES + ", " + STILL_ADD
    if variant in ("strict", "straight", "subtle", "target", "pair", "anchor", "anchormove"):
        vg._LUMA_RULES = vg._LUMA_RULES + ", " + STRICT_ADD + (STRAIGHT_ADD if variant in ("straight", "target") else "")
    movement = s["scene"].get("pov_movement", "walk_in_explore")
    if variant in ("subtle", "plainsubtle"):
        movement = "subtle_rotate"          # the almost-static production movement
    if variant == "target":
        vg._LUMA_MOVEMENT_TOKENS["walk_in_explore"] = TARGET_MOTION
        movement = "walk_in_explore"
    if variant == "anchor":
        anchor = anchor_phrase(s["image"], ask=anchor_ask)
        if not anchor:
            print("Claude non ha indicato un punto di riferimento sicuro per questa foto (o non ha risposto): nessuna generazione, nessuna spesa."); return 5
        print("Punto verso cui avanzare, scelto da Claude guardando la foto:", anchor)
        vg._LUMA_MOVEMENT_TOKENS["walk_in_explore"] = ANCHOR_MOTION.format(anchor=anchor)
        movement = "walk_in_explore"      # every movement becomes a straight approach to the anchor (no sideways slide, no rotation)
    if variant == "anchormove":
        anchor, side = anchor_side_of(s["image"], ask=anchor_ask)
        if not anchor:
            print("Claude non ha indicato un punto di riferimento sicuro per questa foto (o non ha risposto): nessuna generazione, nessuna spesa."); return 5
        if movement == "stand_look_around":
            movement = "walk_in_explore"            # same remap as assemble_pov_prompt
        text = anchor_motion_for(movement, anchor, side)
        print(f"Punto di riferimento scelto da Claude: {anchor} (posizione: {side}); movimento della scena: {movement}")
        print("Istruzione di camera:", text[:230])
        vg._LUMA_MOVEMENT_TOKENS[movement] = text
    gen = generate or vg.generate_video_single
    SCRATCH.mkdir(parents=True, exist_ok=True)
    out = SCRATCH / f"exp_{job}_{index}_{variant}_{int(time.time())}.mp4"
    sc = s["scene"]
    done = gen(str(s["image"]), 5, str(out), space_type=sc.get("space_type", "large"), pov_movement=movement,
               model_tier="luma", end_frame=(variant == "pair"))
    used = None
    try:
        import clip_provenance
        used = clip_provenance.used_model_of(out)
    except Exception:
        pass
    if done and out.exists():
        import cost_tracker as ct
        real = ct.video_cost_for_clip("luma", 5, used)
        add_spend(round(real, 2), f"{job} scene {index} {variant} model={used}")
        print(f"FATTO. costo reale ~{real:.2f} EUR (modello {used}); totale speso {spent():.2f} di {CAP_EUR:.2f} EUR")
        import preview_proxy
        light = preview_proxy.light_copy(out, SCRATCH)
        print("video leggero:", f"http://187.77.196.94:8000/test-scratch/{light.name}")
        print("video pieno:  ", f"http://187.77.196.94:8000/test-scratch/{out.name}")
        return 0
    # a failed call may still have been billed: count it as spent so the cap stays safe
    add_spend(eur, f"{job} scene {index} {variant} FAILED (counted as spent, to be safe)")
    print("generazione NON riuscita (contata come spesa per sicurezza). Vedi il log del server/terminale.")
    return 1


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(HERE / ".env")
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "list":
        cmd_list(a[1])
    elif len(a) >= 4 and a[0] == "run":
        sys.exit(cmd_run(a[1], int(a[2]), a[3], "--go" in a))
    else:
        print(__doc__)
