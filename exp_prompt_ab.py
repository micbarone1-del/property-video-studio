"""exp_prompt_ab.py - blind A/B of the Luma prompt on the 360p DRAFT tier (2026-11-03, Michele: "Priority 1 = il prompt di Luma deve essere fatto ora").

Ideas from Luma support (email of 2026-11-03), tested ONE AT A TIME on the same photo, 5 s clips at 360p (20 credits = about 0.06 USD each):
  A  base       the exact prompt production sent for that clip (read from <clip>.view.json), unchanged
  B  nomove     the same prompt without the words move / moves / moving / down
  C  lock       "Stationary view ... Locked off camera": for clips that must stay still (aerial view, hallucination checks)
  D  keyframe   the same prompt as A, plus a half-way keyframe at frame index 60 of 120 (a crop at half the travel of the plan): speed control
  F  centre     (round 2) A with the target of the push-in replaced by "the centre of the frame" (no destination such as a door or an entrance)
  G  shorter    (round 2) A with "advancing less than three metres" replaced by "less than one metre"
Writes ONLY into jobs/_test_scratch/prompt_ab/ (never into a job, never deletes anything). The clips get blind codes: look first, then `reveal`.
Spend: own cap CAP_USD, every started clip counts (failed ones too, to be safe). Without --go nothing is generated and nothing is spent.

  python3 exp_prompt_ab.py plan   JOB:INDEX[,JOB:INDEX...] [--variants A,B,C,D] [--reps 2]     free: shows prompts, clip count and cost
  python3 exp_prompt_ab.py run    JOB:INDEX[,...]          [--variants ...] [--reps 2] --go      generates (blind codes printed with links)
  python3 exp_prompt_ab.py reveal RUN_ID                   prints which code was which variant
"""
import json
import os
import random
import re
import string
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOBS_DIR = Path(os.environ.get("PVS_JOBS_DIR") or (HERE / "jobs"))
OUT = JOBS_DIR / "_test_scratch" / "prompt_ab"
SPEND = OUT / "spend.json"
CAP_USD = 4.0
CLIP_USD = 0.06            # 360p, 5 s, SDR = 20 credits (docs.agents.lumalabs.ai/guides/pricing)
RESOLUTION = "360p"
VARIANTS = ("A", "B", "C", "D", "F", "G")
MID_INDEX = 60             # of 0..120 for a 5 s clip
LINK_BASE = os.environ.get("PVS_LINK_BASE", "http://187.77.196.94:8000/test-scratch/prompt_ab")

# B: ordered replacements; whatever still matches BAD_RE afterwards is reported (never silently kept)
B_REPLACE = [      # regexes with word boundaries ("movement" must stay "movement")
    (r"\bthe only thing that moves is the camera\b", "the only thing that changes is the camera position"),
    (r"\bmoving through\b", "through"), (r"\bmoving\b", "travelling"), (r"\bmoves\b", "travels"), (r"\bmove\b", "travel"),
    (r",? \bdown\b", ""),
]
BAD_RE = re.compile(r"\b(move|moves|moving|down)\b", re.I)

# C: the movement clause of the positive rules is replaced by a still camera
C_PREFIX = "Stationary view, locked off camera, no camera movement. "
C_REPLACE = [      # regexes: production says "room" or "scene" depending on the photo
    (r"the only thing that moves is the camera, which makes the movement described above smoothly, at a constant slow speed", "nothing moves, the camera stays locked off"),
    (r"everything in view at the start stays in view and in place while the parts of the (room|scene) nearest the edges leave the frame", "everything in view stays in view and in place"),
    (r"the shot ends on a view of the same (room|scene) that contains exactly the same elements as the first frame", "the last frame is identical to the first frame"),
]
C_CUT = re.compile(r",?\s*The shot ends on a view of the (?:room|scene) showing\b.*$", re.S | re.I)   # Claude's description of the END view: it describes travelling, so it goes


def nomove(prompt: str) -> tuple:
    """(new prompt, words that could not be removed)"""
    out = prompt
    for a, b in B_REPLACE:
        out = re.sub(a, b, out, flags=re.I)
    return out, sorted(set(m.group(0).lower() for m in BAD_RE.finditer(out)))


RETARGET_RE = re.compile(r"(push-in toward )(.+?)(, advancing less than)", re.I | re.S)


def retarget(prompt: str) -> tuple:
    """(new prompt, True if the target phrase was found and replaced)"""
    new, n = RETARGET_RE.subn(r"\1the centre of the frame\3", prompt, count=1)
    return new, n == 1


def shorter(prompt: str) -> tuple:
    new, n = re.subn(r"advancing less than three metres", "advancing less than one metre", prompt, count=1, flags=re.I)
    return new, n == 1


def lock(prompt: str) -> tuple:
    """(new prompt, number of replacements that did NOT apply). Keeps only the rules; the movement sentence at the start and the description of the end view go."""
    i = prompt.find("this is a frozen photograph")
    rules = prompt[i:] if i >= 0 else prompt
    rules = C_CUT.sub("", rules)
    miss = 0
    for a, b in C_REPLACE:
        new = re.sub(a, b, rules, flags=re.I)
        if new == rules:
            miss += 1
        rules = new
    return C_PREFIX + rules.rstrip(", "), miss


def find_clip_notes(job: str, index: int) -> dict:
    """The production sidecars of one scene: {'view': path, 'view_data': {...}} ('prompt', 'last_view', 'scale', 'center'); {} when none."""
    jd = JOBS_DIR / job
    pat = re.compile(rf"(?:scene_)?0*{index}(?!\d)")
    cands = sorted(p for p in jd.rglob("*.view.json") if pat.search(p.name.replace(".view.json", "")))
    for p in cands:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("prompt"):
            return {"view": p, "view_data": d}
    return {}


def load_photo(job: str, index: int):
    import exp_luma
    s = exp_luma.load_scene(job, index)
    return s["image"]


def mid_keyframe(photo: Path, scale: float, center, out: Path) -> Path:
    """A crop of the photo at HALF the travel of the plan (scale 1 -> `scale`), centred on the plan target, resized to the photo size."""
    from PIL import Image
    im = Image.open(photo).convert("RGB")
    w, h = im.size
    mid = 1 + (max(scale, 1.0) - 1) * 0.5
    cw, ch = round(w / mid), round(h / mid)
    cx, cy = center or (0.5, 0.5)
    x0 = min(max(0, round(cx * w - cw / 2)), w - cw)
    y0 = min(max(0, round(cy * h - ch / 2)), h - ch)
    im.crop((x0, y0, x0 + cw, y0 + ch)).resize((w, h)).save(out, quality=95)
    return out


def spent() -> float:
    try:
        return float(json.loads(SPEND.read_text()).get("total_usd", 0.0))
    except Exception:
        return 0.0


def add_spend(usd: float, note: str):
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        d = json.loads(SPEND.read_text())
    except Exception:
        d = {"total_usd": 0.0, "runs": []}
    d["total_usd"] = round(d["total_usd"] + usd, 4)
    d["runs"].append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "usd": usd, "note": note})
    SPEND.write_text(json.dumps(d, ensure_ascii=False, indent=1))


def build_jobs(cases: list, variants: list, reps: int) -> tuple:
    """([{case, variant, rep, prompt, extra, note}], [problems]) - pure except for reading the production sidecars and photos."""
    jobs, problems = [], []
    for job, idx in cases:
        notes = find_clip_notes(job, idx)
        if not notes:
            problems.append(f"{job}:{idx} - no production prompt found next to the clips (*.view.json with 'prompt'): scene skipped")
            continue
        base = notes["view_data"]["prompt"]
        for v in variants:
            prompt, note, extra = base, "", {}
            if v == "B":
                prompt, left = nomove(base)
                note = f"words left: {left}" if left else ""
                if prompt == base:
                    problems.append(f"{job}:{idx} B - the prompt has none of the words to remove: B would equal A, skipped")
                    continue
            elif v == "C":
                prompt, miss = lock(base)
                note = f"{miss} clause(s) of the rules not found" if miss else ""
            elif v in ("F", "G"):
                prompt, found = (retarget if v == "F" else shorter)(base)
                if not found:
                    problems.append(f"{job}:{idx} {v} - the prompt has no push-in target / travel phrase to change: skipped")
                    continue
            elif v == "D":
                extra = {"scale": notes["view_data"].get("scale") or 1.2, "center": notes["view_data"].get("center")}
            for r in range(reps):
                jobs.append({"job": job, "index": idx, "variant": v, "rep": r + 1, "prompt": prompt, "extra": extra, "note": note})
    return jobs, problems


def generate_luma(photo: Path, prompt: str, out: Path, keyframe: Path = None) -> bool:
    """One 360p 5 s SDR clip through the Agents API (the same endpoint, key and polling as production's _generate_luma_direct)."""
    import requests
    import video_generation as vg
    key = os.environ.get("LUMA_API_KEY")
    if not key:
        print("LUMA_API_KEY missing"); return False
    from PIL import Image
    w, h = Image.open(photo).size
    ratio = "9:16" if h > w else "16:9"
    first = vg._upload_bytes(Path(photo).read_bytes(), "ab_first.jpg")
    video = {"resolution": RESOLUTION, "duration": "5s"}
    if keyframe is not None:
        mid = vg._upload_bytes(Path(keyframe).read_bytes(), "ab_mid.jpg")
        video["keyframes"] = [{"url": first}, {"url": mid}]
        video["keyframe_indexes"] = [0, MID_INDEX]
    else:
        video["start_frame"] = {"url": first}
    r = requests.post(vg.LUMA_DIRECT_API_URL, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                      json={"model": "ray-3.2", "type": "video", "prompt": prompt, "aspect_ratio": ratio, "video": video}, timeout=30)
    if r.status_code not in (200, 201):
        print("create failed", r.status_code, r.text[:300]); return False
    gid = r.json().get("id")
    for _ in range(90):
        time.sleep(5)
        p = requests.get(f"{vg.LUMA_DIRECT_API_URL}/{gid}", headers={"Authorization": f"Bearer {key}"}, timeout=30)
        if p.status_code != 200:
            continue
        d = p.json()
        if d.get("state") == "completed":
            url = ((d.get("output") or [{}])[0]).get("url")
            if not url:
                return False
            out.write_bytes(requests.get(url, timeout=120).content)
            return True
        if d.get("state") == "failed":
            print("generation failed:", d.get("failure_reason")); return False
    print("timed out:", gid); return False


def sheet(mp4: Path) -> Path:
    """A strip of 6 frames of the clip (easy to look at on a tablet); None if ffmpeg fails."""
    jpg = mp4.with_suffix(".jpg")
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4), "-vf", "fps=1.2,scale=320:-1,tile=6x1", "-frames:v", "1", str(jpg)], check=True, timeout=60)
        return jpg
    except Exception:
        return None


def cmd_plan_or_run(arg: str, variants: list, reps: int, go: bool, generate=generate_luma):
    cases = []
    for c in arg.split(","):
        j, i = c.split(":")
        cases.append((j.strip(), int(i)))
    jobs, problems = build_jobs(cases, variants, reps)
    for p in problems:
        print("NOTE:", p)
    n = len(jobs)
    cost = round(n * CLIP_USD, 2)
    print(f"{n} clips x {CLIP_USD} USD = {cost} USD (already spent {spent():.2f} of {CAP_USD:.2f} USD)")
    for j in jobs:
        print(f"  {j['job']}:{j['index']} {j['variant']}#{j['rep']} {j['note']}\n    prompt: {j['prompt'][:260]}")
    if not go:
        print("No generation (no --go)."); return 0
    if spent() + cost > CAP_USD:
        print("REFUSED: it would pass the cap."); return 3
    run_id = time.strftime("%m%d_%H%M%S")
    OUT.mkdir(parents=True, exist_ok=True)
    random.shuffle(jobs)
    key, codes = [], set()
    for j in jobs:
        code = "".join(random.choice(string.ascii_lowercase) for _ in range(3))
        while code in codes:
            code = "".join(random.choice(string.ascii_lowercase) for _ in range(3))
        codes.add(code)
        photo = load_photo(j["job"], j["index"])
        if not photo:
            print(f"{j['job']}:{j['index']} photo not found, skipped"); continue
        kf = None
        if j["variant"] == "D":
            kf = mid_keyframe(Path(photo), j["extra"]["scale"], j["extra"]["center"], OUT / f"mid_{run_id}_{code}.jpg")
        out = OUT / f"ab_{run_id}_{code}.mp4"
        add_spend(CLIP_USD, f"{run_id} {j['job']}:{j['index']} {j['variant']} (counted when started)")
        ok = generate(Path(photo), j["prompt"], out, kf)
        key.append({"code": code, "case": f"{j['job']}:{j['index']}", "variant": j["variant"], "rep": j["rep"], "ok": bool(ok and out.exists()), "prompt": j["prompt"]})
        if ok and out.exists():
            sh = sheet(out)
            print(f"{j['job']}:{j['index']}  {code}  {LINK_BASE}/{out.name}" + (f"   strip: {LINK_BASE}/{sh.name}" if sh else ""))
        else:
            print(f"{j['job']}:{j['index']}  {code}  FAILED")
        (OUT / f"key_{run_id}.json").write_text(json.dumps(key, ensure_ascii=False, indent=1))
    print(f"RUN {run_id} done. Look at the clips, tell me what you see per code, THEN: python3 exp_prompt_ab.py reveal {run_id}")
    return 0


def cmd_reveal(run_id: str):
    for k in json.loads((OUT / f"key_{run_id}.json").read_text()):
        print(k["code"], k["case"], k["variant"], f"rep{k['rep']}", "ok" if k["ok"] else "FAILED")
    return 0


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(HERE / ".env")
    a = sys.argv[1:]
    def opt(name, default):
        return a[a.index(name) + 1] if name in a else default
    variants = [v for v in opt("--variants", "A,B,C,D").split(",") if v in VARIANTS]
    if len(a) >= 2 and a[0] in ("plan", "run"):
        sys.exit(cmd_plan_or_run(a[1], variants, int(opt("--reps", "2")), a[0] == "run" and "--go" in a))
    elif len(a) >= 2 and a[0] == "reveal":
        sys.exit(cmd_reveal(a[1]))
    else:
        print(__doc__)
