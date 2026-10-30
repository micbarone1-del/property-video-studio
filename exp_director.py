"""
exp_director.py -- EXPERIMENT TOOL, NOT PRODUCTION (2026-10-30).

"Claude as director" for ONE scene, stills only (no Luma video is generated, so the cost is a few cents):
  1. Claude looks at the START frame (the file Luma really receives: enhanced_lit > enhanced > original, same order as exp_luma.load_scene)
     and decides, from the depth and character of the room, WHERE the camera ends: which fixed, far, interesting target it walks toward
     and how much larger that target must appear, keeping the view inside what the start frame already shows (a forward move only lets
     things leave the frame at the edges; nothing new should enter). Claude writes the prompt for the image model.
  2. Nano Banana 2 (fal-ai/nano-banana-2/edit) draws the END frame (one implementation: exp_endframe.run_fal / match_colour / compare_sheet).
  3. Claude compares start and end and gives a verdict (same room, nothing new, same light, camera really moved, target larger).
     If it fails, ONE more attempt with the reasons added to the prompt.
Outputs go to jobs/_test_scratch (never into a job): endd_<job>_s<scene>_a<attempt>.jpg (+ _m colour-aligned), a comparison sheet and a log json.

  python3 exp_director.py JOB SCENE [--jobs-dir DIR]          plan only (nothing spent)
  python3 exp_director.py JOB SCENE [--jobs-dir DIR] --go     Claude + Nano Banana 2, at most 2 attempts (about USD 0.30 per scene at most)
"""
import argparse
import base64
import json
import os
import sys
import time
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import exp_endframe as ef                      # one implementation of the generation / colour match / comparison sheet
import exp_geometry as geo                     # one implementation of the geometric measurement (free, local)

MODEL = os.environ.get("PVS_DIRECTOR_MODEL", "claude-sonnet-5-5")   # same model production uses for the clip QC
PRICE_IN, PRICE_OUT = 2.00, 10.00                                    # per million tokens (same table as listing_scraper), only for the printed estimate
MAX_ATTEMPTS = 3
# Geometric gate on the END frame (PROPOSED values, from the first measurements of 2026-10-30; to be tuned on the validation batch)
MIN_SCALE = 1.2        # smaller = the viewer sees no advance (the 1 m / 0.5 m end frames measured 1.006 / 1.048)
MAX_FOE = 0.2          # expansion point further from the centre than this (fraction of the picture size) = looks like a sideways slide
MAX_ROT = 2.5          # degrees: the camera must not turn
MIN_INSIDE = 0.97      # share of the end view that is already inside the start view
FAL_MODEL = "fal-ai/nano-banana-2/edit"
FAL_MODELS = (FAL_MODEL, FAL_MODEL, "fal-ai/nano-banana-pro/edit")   # attempt 3 switches to the Pro model (about twice the price; untested as a fallback)
SCALE_LADDER = (None, 1.35, 1.25)    # attempt 1 = the director's scale; a failed attempt is followed by a gentler move (2026-10-30: the 1.45 end frame of scene 1
                                     # invented a bowl; the earlier 1.25-1.30 one passed). A larger move gives the image model more to invent.

DIRECTOR_PROMPT = """You are the director of a short real-estate video. A single photo of a room is the FIRST frame of a 5 second clip in which the camera moves slowly FORWARD. You decide where the camera ends, and you write the instruction for an image model that will draw the LAST frame (the same room seen from the new position).

Look at the photo and judge the depth and character of the room (small, medium or deep; what is far away; what is worth looking at).

Rules for the end position:
- The camera moves only straight forward along the direction it already looks. Same height, same direction, same lens: no turning, no tilt, no sideways move, no zoom of the picture.
- Choose ONE target: a FIXED, FAR feature in the MIDDLE THIRD of the photo (horizontally and vertically: the camera does not turn, so a target far to one side would make the move look like a sideways slide) that is worth showing (a far wall feature, an architectural detail, a view, a piece of furniture at the far end). Never a door of any kind, a curtain, a mirror or reflective surface, a screen, a person, a plant, water, or a utilitarian fixture (sink, toilet, bath, radiator, stove).
- The move must be clearly VISIBLE (a viewer must see the room come closer) but the end frame must stay INSIDE what the photo already shows: moving forward only lets things at the edges leave the frame, nothing new may enter it. Never choose a position so close that the view would have to be invented.
- Say how much larger the target appears in the end frame compared with the photo (linear size, a number). Take it from the room: a small or shallow room allows a modest change (about 1.2 to 1.35), a medium room about 1.35 to 1.55, a deep room about 1.5 to 1.8. Where the camera ends is expressed with landmarks of the photo (for example "about halfway between the sofa and the far window"), never with a number of metres.
- Everything else stays exactly as in the photo: same objects, same colours, same positions, same state of doors and windows, same light and white balance.

Write the image-model instruction ("end_frame_prompt") in plain positive sentences (say what the picture shows, not what to avoid). It must state: it is the same room photographed with the same camera, lens, height, exposure and white balance; the camera has moved straight forward to <where, with landmarks>; the target now appears about {SCALE} times larger (write the literal token {SCALE} instead of the number) and stays near the centre; objects near the left, right, top and bottom edges of the original have moved out of the frame; everything visible is exactly as in the original; the picture is completely still.

Answer with JSON only, no other text:
{"room": "...", "depth": "shallow|medium|deep", "target": "name of the target ONLY, at most 6 words, no landmarks", "target_where": "where it is in the photo, with landmarks", "target_scale": 1.4, "end_position": "where the camera ends, with landmarks", "leaves_the_frame": "what leaves the frame at the edges", "reasoning": "two sentences", "end_frame_prompt": "..."}"""

QC_PROMPT = """Image 1 is the START photo of a real-estate clip. Image 2 is a generated END frame: the same room after the camera moved straight forward. The intention was: {intent}

Check strictly, as a quality controller for a listing video where nothing may be shown that is not in the room:
1. same_room: is it clearly the same room, with the same furniture, finishes, colours and layout?
2. invented_or_changed: list every object or feature visible in image 2 where image 1 shows something DIFFERENT or NOTHING in the same place (an object added on a surface, a piece of furniture missing, moved or replaced, a changed colour, shape or pattern, a different window or door state, an extra fixture, a curtain that was not there). Elements that merely left the frame at the edges are fine.
2b. revealed: ordinary things that became visible only because the new viewpoint shows what was hidden behind something in image 1 (acceptable; list them for information only, they do NOT count against the verdict).
3. light_consistent: same light, exposure and white balance?
4. camera_moved_forward: does image 2 look like the same camera moved straight forward (same height and direction)? Or is it just a zoomed crop, or turned, or moved sideways?
5. target_scale_estimate: how many times larger does the target ({target}) look in image 2 than in image 1 (number)?
Verdict "pass" only if same_room is true, invented_or_changed is empty, light_consistent is true, camera_moved_forward is true and the target is clearly larger. Otherwise "fail".

Answer with JSON only: {{"same_room": true, "invented_or_changed": [], "revealed": [], "light_consistent": true, "camera_moved_forward": true, "target_scale_estimate": 1.4, "verdict": "pass", "reasons": ["short sentence"]}}"""


def _b64(path_or_img, max_side=1568) -> str:
    from PIL import Image
    im = path_or_img if hasattr(path_or_img, "size") else Image.open(path_or_img)
    im = im.convert("RGB")
    if max(im.size) > max_side:
        k = max_side / max(im.size)
        im = im.resize((round(im.width * k), round(im.height * k)))
    buf = BytesIO()
    im.save(buf, "JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode()


def _json_of(text: str) -> dict:
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b < a:
        raise ValueError("no JSON in the answer: " + text[:200])
    return json.loads(text[a:b + 1])


def ask_claude(prompt: str, images: list, usage: dict) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _b64(i)}} for i in images]
    content.append({"type": "text", "text": prompt})
    last = ""
    for _ in range(2):                    # one more try when the answer is cut or not valid JSON (seen on the first real run: scene 1 QC)
        r = client.messages.create(model=MODEL, max_tokens=3000, messages=[{"role": "user", "content": content}])
        usage["in"] = usage.get("in", 0) + r.usage.input_tokens
        usage["out"] = usage.get("out", 0) + r.usage.output_tokens
        text = "".join(b.text for b in r.content if getattr(b, "text", ""))
        try:
            return _json_of(text)
        except Exception as e:
            last = f"{e} | stop_reason={getattr(r, 'stop_reason', None)} | text={text[:600]}"
    raise ValueError(last)


def start_frame(jobs_dir: str, job: str, scene: int) -> Path:
    os.environ["PVS_JOBS_DIR"] = jobs_dir          # exp_luma reads it at import: the ONE place that decides which photo Luma receives
    import exp_luma
    img = exp_luma.load_scene(job, scene)["image"]
    if not img:
        raise SystemExit("start frame not found")
    return Path(img)


def prompt_for(plan: dict, n: int):
    """The image-model prompt of attempt n and the scale it asks for (a failed attempt is followed by a gentler move)."""
    asked = float(plan.get("target_scale") or 1.3)
    sc = asked if n <= 1 or SCALE_LADDER[min(n, len(SCALE_LADDER)) - 1] is None else min(asked, SCALE_LADDER[min(n, len(SCALE_LADDER)) - 1])
    base = plan["end_frame_prompt"]
    if "{SCALE}" in base:
        return base.replace("{SCALE}", f"{sc:g}"), sc
    if sc != asked and f"{asked:g}" in base:
        return base.replace(f"{asked:g}", f"{sc:g}"), sc
    return base, asked


def gate_problems(g: dict, plan: dict) -> list:
    """Objective problems of an end frame, as correction sentences for the image model. A frame that cannot be measured is NOT blocked here
    (the Claude check still judges it, and the log says 'not measurable')."""
    if not g.get("ok"):
        return []
    out = []
    if g["scale"] < MIN_SCALE:
        want = max(min(float(plan.get("target_scale") or 1.3), 1.35), 1.3)
        out.append(f"The previous end frame was enlarged only about {g['scale']} times, which a viewer would not notice: move the camera clearly further forward so that the target appears about {want:g} times larger.")
    fx, fy = g.get("foe_x"), g.get("foe_y")
    if fx is None or max(abs(fx), abs(fy)) > MAX_FOE:
        out.append("The previous end frame drifted sideways or vertically: move the camera straight along the original viewing axis, with no sideways or vertical shift, so that everything in the picture grows outward from the centre of the picture.")
    if abs(g["rotation_deg"]) > MAX_ROT:
        out.append("The previous end frame was rotated: keep the horizon level and the camera pointing in exactly the same direction.")
    if g["inside"] < MIN_INSIDE:
        out.append("The previous end frame showed parts of the room that were not visible in the original: only the edges may leave the frame, nothing new may enter it.")
    return out


def direct_one_scene(photo: Path, tag: str, ask=ask_claude, gen=None, out_dir: Path = None, public: str = None) -> dict:
    from PIL import Image
    import camera_plan
    out_dir = out_dir or ef.OUT_DIR
    public = public or ef.PUBLIC
    gen = gen or (lambda prompt, model: ef.run_fal(model, photo, prompt))
    usage, log = {}, {"model": MODEL, "photo": str(photo), "attempts": []}
    def unsafe_words(pl):
        words = (pl.get("target") or "").lower().replace(",", " ").replace(".", " ").split()
        return sorted({w for w in words if w.startswith(camera_plan.ANCHOR_UNSAFE_STEMS)})   # SAME list production uses for anchors

    plan = ask(DIRECTOR_PROMPT, [photo], usage)
    log["director"] = plan
    bad = unsafe_words(plan)
    if bad:                               # a safety net in CODE, not only in the prompt (first real run: scene 4 target was a window WITH a curtain)
        log["first_plan_rejected"] = {"target": plan.get("target"), "unsafe_words": bad}
        plan = ask(DIRECTOR_PROMPT + f"\n\nYour previous target ({plan.get('target')!r}) was refused because it contains the forbidden word(s) {bad}. "
                   "Choose a different target that is plain, solid and fixed, and answer again in the same JSON format.", [photo], usage)
        log["director"] = plan
    log["target_unsafe_word"] = bool(unsafe_words(plan))
    prompt, asked_scale = prompt_for(plan, 1)
    results = {}
    for n in range(1, MAX_ATTEMPTS + 1):
        att = {"n": n, "prompt": prompt, "model": FAL_MODELS[min(n, len(FAL_MODELS)) - 1], "scale_asked": asked_scale}
        log["attempts"].append(att)
        raw = gen(prompt, att["model"])
        out = out_dir / f"endd_{tag}_a{n}.jpg"
        Image.open(BytesIO(raw)).convert("RGB").save(out, quality=92)
        m = out_dir / f"endd_{tag}_a{n}_m.jpg"
        ef.match_colour(out, photo, m)
        att.update({"file": out.name, "matched_file": m.name})
        results[f"tentativo {n}"] = m
        g = geo.analyse(photo, m, out_dir / f"endd_{tag}_a{n}_geom.jpg")
        att["geometry"] = g
        att["geometry_file"] = f"endd_{tag}_a{n}_geom.jpg"
        problems = gate_problems(g, plan)
        att["gate_problems"] = problems
        if problems and n < MAX_ATTEMPTS:      # a failed geometry costs no Claude QC: regenerate the (cheap) still with a precise correction
            att["qc"] = {"verdict": "skipped (geometry gate)"}
            prompt, asked_scale = prompt_for(plan, n + 1)
            prompt += " Correction from the previous attempt: " + " ".join(problems) + " Keep everything exactly as in the original photo."
            continue
        intent = (f"the camera ends at: {plan.get('end_position')}; target: {plan.get('target')} about {plan.get('target_scale')} times larger; "
                  f"what leaves the frame: {plan.get('leaves_the_frame')}")
        try:
            qc = ask(QC_PROMPT.format(intent=intent, target=plan.get("target")), [photo, m], usage)
        except Exception as e:             # the generated picture (already paid) must never be lost because the check failed
            qc = {"verdict": "error", "reasons": [str(e)[:500]]}
        att["qc"] = qc
        if qc.get("verdict") == "error":
            break
        if str(qc.get("verdict", "")).lower() == "pass" and not problems:
            att["pass"] = True
            break
        issues = "; ".join(list(qc.get("invented_or_changed") or qc.get("new_or_changed") or []) + problems)
        prompt, asked_scale = prompt_for(plan, n + 1)
        prompt += (" Correction from the previous attempt: the picture differed from the original here: " + issues[:500]
                   + ". Every object that was visible in the original must look exactly the same and sit in the same place on the same surface.")
    log["final"] = {"pass": any(a.get("pass") for a in log["attempts"]), "attempts": len(log["attempts"])}
    log["usage"] = usage
    log["claude_cost_estimate"] = round((usage.get("in", 0) * PRICE_IN + usage.get("out", 0) * PRICE_OUT) / 1e6, 4)
    sheet = out_dir / f"endd_{tag}_confronto.jpg"
    ef.compare_sheet(photo, results, sheet)
    log["sheet"] = sheet.name
    (out_dir / f"endd_{tag}_log.json").write_text(json.dumps(log, indent=2, ensure_ascii=False))
    return log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id")
    ap.add_argument("scene", type=int)
    ap.add_argument("--jobs-dir", default=ef.JOBS_DEFAULT)
    ap.add_argument("--go", action="store_true")
    a = ap.parse_args()
    photo = start_frame(a.jobs_dir, a.job_id, a.scene)
    print("start frame:", photo)
    print(f"model: {MODEL} | image model: {FAL_MODEL} | up to {MAX_ATTEMPTS} attempts | cost: a few cents of Claude + about USD 0.08 per image")
    if not a.go:
        print("PLAN ONLY (nothing spent). Add --go to run.")
        return
    ef.OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"{a.job_id}_s{a.scene}"
    log = direct_one_scene(photo, tag)
    d = log["director"]
    if log.get("first_plan_rejected"):
        print("FIRST TARGET REFUSED BY THE CODE:", log["first_plan_rejected"])
    print(f"ROOM: {d.get('room')} ({d.get('depth')}) | TARGET: {d.get('target')} ({d.get('target_where')}) | scale x{d.get('target_scale')}"
          + ("  [WARNING: target word is on the unsafe list]" if log["target_unsafe_word"] else ""))
    print("END POSITION:", d.get("end_position"))
    print("LEAVES THE FRAME:", d.get("leaves_the_frame"))
    print("REASONING:", d.get("reasoning"))
    print("PROMPT:", log["attempts"][0]["prompt"])
    for att in log["attempts"]:
        q = att["qc"]
        gm = att.get("geometry") or {}
        print(f"ATTEMPT {att['n']} GEOMETRY: scale {gm.get('scale')} | rotation {gm.get('rotation_deg')} | expansion point ({gm.get('foe_x')}, {gm.get('foe_y')}) | inside {gm.get('inside')} | "
              f"problems: {att.get('gate_problems') or 'none'} | outline {ef.PUBLIC + att.get('geometry_file', '')}")
        print(f"ATTEMPT {att['n']} ({att.get('model')}, asked x{att.get('scale_asked')}): verdict {q.get('verdict')} | scale estimate {q.get('target_scale_estimate')} | invented/changed: {q.get('invented_or_changed', q.get('new_or_changed'))} | "
              f"same room {q.get('same_room')} light {q.get('light_consistent')} forward {q.get('camera_moved_forward')}")
        print("   reasons:", q.get("reasons"))
        print("   image:", ef.PUBLIC + att["matched_file"])
    print("FINAL:", "PASS" if log["final"]["pass"] else "FAIL", f"after {log['final']['attempts']} attempt(s)")
    print("CONFRONTO:", ef.PUBLIC + log["sheet"])
    print(f"Claude tokens in/out {log['usage'].get('in')}/{log['usage'].get('out')} (~USD {log['claude_cost_estimate']})")


if __name__ == "__main__":
    main()
