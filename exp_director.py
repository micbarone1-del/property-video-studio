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

MODEL = os.environ.get("PVS_DIRECTOR_MODEL", "claude-sonnet-5-5")   # same model production uses for the clip QC
PRICE_IN, PRICE_OUT = 2.00, 10.00                                    # per million tokens (same table as listing_scraper), only for the printed estimate
MAX_ATTEMPTS = 2
FAL_MODEL = "fal-ai/nano-banana-2/edit"

DIRECTOR_PROMPT = """You are the director of a short real-estate video. A single photo of a room is the FIRST frame of a 5 second clip in which the camera moves slowly FORWARD. You decide where the camera ends, and you write the instruction for an image model that will draw the LAST frame (the same room seen from the new position).

Look at the photo and judge the depth and character of the room (small, medium or deep; what is far away; what is worth looking at).

Rules for the end position:
- The camera moves only straight forward along the direction it already looks. Same height, same direction, same lens: no turning, no tilt, no sideways move, no zoom of the picture.
- Choose ONE target: a FIXED, FAR feature near the middle of the photo that is worth showing (a far wall feature, an architectural detail, a view, a piece of furniture at the far end). Never a door of any kind, a curtain, a mirror or reflective surface, a screen, a person, a plant, water, or a utilitarian fixture (sink, toilet, bath, radiator, stove).
- The move must be clearly VISIBLE (a viewer must see the room come closer) but the end frame must stay INSIDE what the photo already shows: moving forward only lets things at the edges leave the frame, nothing new may enter it. Never choose a position so close that the view would have to be invented.
- Say how much larger the target appears in the end frame compared with the photo (linear size, a number). Take it from the room: a small or shallow room allows a modest change (about 1.2 to 1.35), a medium room about 1.35 to 1.55, a deep room about 1.5 to 1.8. Where the camera ends is expressed with landmarks of the photo (for example "about halfway between the sofa and the far window"), never with a number of metres.
- Everything else stays exactly as in the photo: same objects, same colours, same positions, same state of doors and windows, same light and white balance.

Write the image-model instruction ("end_frame_prompt") in plain positive sentences (say what the picture shows, not what to avoid). It must state: it is the same room photographed with the same camera, lens, height, exposure and white balance; the camera has moved straight forward to <where, with landmarks>; the target now appears about <scale> times larger and stays near the centre; objects near the left, right, top and bottom edges of the original have moved out of the frame; everything visible is exactly as in the original; the picture is completely still.

Answer with JSON only, no other text:
{"room": "...", "depth": "shallow|medium|deep", "target": "...", "target_scale": 1.4, "end_position": "where the camera ends, with landmarks", "leaves_the_frame": "what leaves the frame at the edges", "reasoning": "two sentences", "end_frame_prompt": "..."}"""

QC_PROMPT = """Image 1 is the START photo of a real-estate clip. Image 2 is a generated END frame: the same room after the camera moved straight forward. The intention was: {intent}

Check strictly, as a quality controller for a listing video where nothing may be shown that is not in the room:
1. same_room: is it clearly the same room, with the same furniture, finishes, colours and layout?
2. new_or_changed: list EVERY element visible in image 2 that is not in image 1 or that changed (a new object, a curtain, an extra fixture, a different window or door state, a changed pattern). Elements that merely moved out of the frame at the edges are fine. Small parts revealed behind an object because of the new viewpoint are fine if plain.
3. light_consistent: same light, exposure and white balance?
4. camera_moved_forward: does image 2 look like the same camera moved straight forward (same height and direction)? Or is it just a zoomed crop, or turned, or moved sideways?
5. target_scale_estimate: how many times larger does the target ({target}) look in image 2 than in image 1 (number)?
Verdict "pass" only if same_room is true, new_or_changed is empty, light_consistent is true, camera_moved_forward is true and the target is clearly larger. Otherwise "fail".

Answer with JSON only: {{"same_room": true, "new_or_changed": [], "light_consistent": true, "camera_moved_forward": true, "target_scale_estimate": 1.4, "verdict": "pass", "reasons": ["short sentence"]}}"""


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
    r = client.messages.create(model=MODEL, max_tokens=1500, messages=[{"role": "user", "content": content}])
    usage["in"] = usage.get("in", 0) + r.usage.input_tokens
    usage["out"] = usage.get("out", 0) + r.usage.output_tokens
    return _json_of("".join(b.text for b in r.content if getattr(b, "text", "")))


def start_frame(jobs_dir: str, job: str, scene: int) -> Path:
    os.environ["PVS_JOBS_DIR"] = jobs_dir          # exp_luma reads it at import: the ONE place that decides which photo Luma receives
    import exp_luma
    img = exp_luma.load_scene(job, scene)["image"]
    if not img:
        raise SystemExit("start frame not found")
    return Path(img)


def direct_one_scene(photo: Path, tag: str, ask=ask_claude, gen=None, out_dir: Path = None, public: str = None) -> dict:
    from PIL import Image
    import camera_plan
    out_dir = out_dir or ef.OUT_DIR
    public = public or ef.PUBLIC
    gen = gen or (lambda prompt: ef.run_fal(FAL_MODEL, photo, prompt))
    usage, log = {}, {"model": MODEL, "photo": str(photo), "attempts": []}
    plan = ask(DIRECTOR_PROMPT, [photo], usage)
    log["director"] = plan
    tgt = (plan.get("target") or "").lower()
    log["target_unsafe_word"] = any(w.startswith(camera_plan.ANCHOR_UNSAFE_STEMS) for w in tgt.replace(",", " ").split())
    prompt = plan["end_frame_prompt"]
    results = {}
    for n in range(1, MAX_ATTEMPTS + 1):
        att = {"n": n, "prompt": prompt}
        log["attempts"].append(att)
        raw = gen(prompt)
        out = out_dir / f"endd_{tag}_a{n}.jpg"
        Image.open(BytesIO(raw)).convert("RGB").save(out, quality=92)
        m = out_dir / f"endd_{tag}_a{n}_m.jpg"
        ef.match_colour(out, photo, m)
        att.update({"file": out.name, "matched_file": m.name})
        results[f"tentativo {n}"] = m
        intent = (f"the camera ends at: {plan.get('end_position')}; target: {plan.get('target')} about {plan.get('target_scale')} times larger; "
                  f"what leaves the frame: {plan.get('leaves_the_frame')}")
        qc = ask(QC_PROMPT.format(intent=intent, target=plan.get("target")), [photo, m], usage)
        att["qc"] = qc
        if str(qc.get("verdict", "")).lower() == "pass":
            break
        issues = "; ".join(list(qc.get("new_or_changed") or []) + list(qc.get("reasons") or []))
        prompt = plan["end_frame_prompt"] + " Correction from the previous attempt: " + issues[:400] + " Keep everything exactly as in the original photo."
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
    print(f"ROOM: {d.get('room')} ({d.get('depth')}) | TARGET: {d.get('target')} | scale x{d.get('target_scale')}"
          + ("  [WARNING: target word is on the unsafe list]" if log["target_unsafe_word"] else ""))
    print("END POSITION:", d.get("end_position"))
    print("LEAVES THE FRAME:", d.get("leaves_the_frame"))
    print("REASONING:", d.get("reasoning"))
    print("PROMPT:", log["attempts"][0]["prompt"])
    for att in log["attempts"]:
        q = att["qc"]
        print(f"ATTEMPT {att['n']}: verdict {q.get('verdict')} | scale estimate {q.get('target_scale_estimate')} | new/changed: {q.get('new_or_changed')} | "
              f"same room {q.get('same_room')} light {q.get('light_consistent')} forward {q.get('camera_moved_forward')}")
        print("   reasons:", q.get("reasons"))
        print("   image:", ef.PUBLIC + att["matched_file"])
    print("CONFRONTO:", ef.PUBLIC + log["sheet"])
    print(f"Claude tokens in/out {log['usage'].get('in')}/{log['usage'].get('out')} (~USD {log['claude_cost_estimate']})")


if __name__ == "__main__":
    main()
