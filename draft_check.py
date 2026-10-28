"""draft_check.py - repeatable draft-level check of the whole pipeline BEFORE any paid video (2026-10-27).

Why: a full job costs about EUR 6.6 in video generation, but everything that decides most of the quality - reading the listing, choosing
and ranking the photos, writing and voicing the narration, picking the camera movement - is finished at the DRAFT stage and costs cents.
This tool runs that part on a list of real listings (the "golden set") and checks the same invariants every time, so a rule change is
judged on many listings and not on the one that showed the problem. It never generates a video and never touches anything under jobs/
except reading (the drafts it creates are ordinary drafts).

Usage on the server (venv active):
    python3 draft_check.py golden_listings.txt            # one line per listing:  URL | short label
    python3 draft_check.py --job a8184a2b --job c9099c46  # re-check drafts that already exist (no new draft, no cost)

evaluate() is a pure function (no network, no files) so the rules themselves are unit-tested (test_draft_check.py).
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HALL_SPACES = ("corridor", "hallway")
INTERIOR_CATEGORIES = ("living", "kitchen", "bedrooms", "bathrooms")
from camera_plan import OUTDOOR_UNRECOGNISED_MOVEMENT
# 2026-10-28 (P3): the minimal move is what an outdoor space gets when the analysis cannot name it: intended, not a warning
OUTDOOR_MOVES = ("outward_view", "approach_facade", OUTDOOR_UNRECOGNISED_MOVEMENT)
MAX_PAUSE_WARN, MAX_PAUSE_FAIL = 2.6, 4.0
MAX_CLAUDE_EUR_WARN = 0.6
SPEECH_MIN, SPEECH_MAX = 26.0, 32.0        # listing_scraper.STANDARD_*_SPEECH_SECS for 6 scenes (checked by the tests)


def evaluate(meta: dict, silences=None, image_hashes=None) -> list:
    """[(level, id, message)] with level FAIL (the draft is not good enough to pay for a video) or WARN / INFO (look at it)."""
    out = []
    add = lambda lvl, i, m: out.append((lvl, i, m))
    status = meta.get("status")
    if status not in ("draft", "awaiting_approval", "done") or not meta.get("scenes_config"):
        add("FAIL", "C1", f"status is {status!r} or no scenes: {meta.get('prep_error') or meta.get('message') or ''}"[:200])
        return out
    cfg = meta.get("scenes_config") or []
    sr = meta.get("selection_report") or {}

    mode = meta.get("narration_mode")
    if mode not in ("per_scene", "anchored"):
        add("FAIL", "C2", f"narration mode is {mode!r} (the voice is not tied to the scenes); reason: {meta.get('narration_script_fallback')}")
    dur = meta.get("narration_duration_secs")
    if not isinstance(dur, (int, float)) or not (SPEECH_MIN <= dur <= SPEECH_MAX):
        add("FAIL", "C3", f"voice lasts {dur} s, allowed {SPEECH_MIN}-{SPEECH_MAX} s for 6 scenes")
    if len(cfg) != 6 or any(c.get("duration") != 5 for c in cfg):
        add("FAIL", "C4", f"expected 6 scenes of 5 s, got {[c.get('duration') for c in cfg]}")
    if image_hashes:
        seen, dup = {}, []
        for i, h in enumerate(image_hashes):
            if h in seen:
                dup.append((seen[h], i))
            seen.setdefault(h, i)
        if dup:
            add("FAIL", "C5", f"the same photo is used in scenes {dup}")
    cats = [c.get("category") for c in cfg]
    repeated = sorted({c for c in cats if cats.count(c) > 1})
    if repeated:
        add("WARN", "C6", f"category used twice: {repeated} (backfill because another category had no photo?)")
    for i, c in enumerate(cfg):
        if c.get("category") in INTERIOR_CATEGORIES and c.get("space_type") in HALL_SPACES:
            add("WARN", "C7", f"scene {i} is '{c.get('category')}' but the photo reads as a {c.get('space_type')} (entrance hall / corridor)")
    cand = sr.get("candidates_by_category") or {}
    for cat, label in (("exterior", "facade"), ("outdoor", "balcony / garden / view")):
        if cand.get(cat) and cat not in cats:
            add("WARN", "C8", f"the listing has {cand[cat]} '{cat}' photo(s) but no scene shows the {label}")
    if silences:
        longest = max(silences)
        if longest > MAX_PAUSE_FAIL:
            add("FAIL", "C9", f"a pause of {longest:.1f} s inside the narration")
        elif longest > MAX_PAUSE_WARN:
            add("WARN", "C9", f"longest pause {longest:.1f} s")
    text = (meta.get("narration_text") or "").lower()
    if "contatt" not in text:
        add("FAIL", "C10", "the narration has no closing invitation to contact the agency")
    if "€" in text or re.search(r"\beuro\b", text):
        add("FAIL", "C11", "the narration mentions a price")
    for i, c in enumerate(cfg):
        if c.get("category") == "outdoor" and c.get("pov_movement") not in OUTDOOR_MOVES:
            add("WARN", "C12", f"scene {i} is 'outdoor' but moves with {c.get('pov_movement')} (space read as {c.get('space_type')})")
    usage = (meta.get("claude_usage") or {}).get("cost_eur")
    if isinstance(usage, (int, float)) and usage > MAX_CLAUDE_EUR_WARN:
        add("WARN", "C13", f"Claude cost of the draft EUR {usage} (expected well below {MAX_CLAUDE_EUR_WARN})")
    try:
        import camera_plan
        usable = [i for i, c in enumerate(cfg) if camera_plan.intent_kwargs(c)]
        add("INFO", "C14", f"scenes that will use an anchor: {usable}" if camera_plan.anchor_enabled() else "anchor switch is off")
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------------------------------- I/O (server only)
def _silences(path: Path) -> list:
    try:
        r = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path), "-af", "silencedetect=noise=-35dB:d=0.6", "-f", "null", "-"],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120).stderr
        return [float(m) for m in re.findall(r"silence_duration: ([0-9.]+)", r)]
    except Exception:
        return []


def _hashes(job_dir: Path, n: int) -> list:
    import hashlib
    out = []
    for i in range(n):
        f = job_dir / "images" / f"scene_{i:03d}.jpg"
        out.append(hashlib.sha256(f.read_bytes()).hexdigest() if f.exists() else f"missing-{i}")
    return out


def _api_state(job_id: str, base="http://localhost:8000") -> dict:
    try:
        import requests
        d = requests.get(f"{base}/jobs/{job_id}", headers={"X-Access-Key": _env_key()}, timeout=30).json()
        return {"status": d.get("status") or "unknown", "message": d.get("message") or d.get("error") or json.dumps(d)[:200], "property_name": d.get("property_name")}
    except Exception as e:
        return {"status": "unknown", "message": f"no job_meta.json and the API is unreachable: {e}"}


def check_job(job_id: str, jobs_dir: Path = Path("jobs")) -> dict:
    jd = jobs_dir / job_id
    try:
        meta = json.loads((jd / "job_meta.json").read_text())
    except Exception:
        meta = _api_state(job_id)      # a failed draft preparation is not a job on disk (by design): read what the API says
    n = len(meta.get("scenes_config") or [])
    results = evaluate(meta, _silences(jd / "narration.mp3"), _hashes(jd, n))
    return {"job": job_id, "name": meta.get("property_name"), "mode": meta.get("narration_mode"), "results": results,
            "claude_eur": (meta.get("claude_usage") or {}).get("cost_eur")}


def _env_key() -> str:
    for line in Path(".env").read_text().splitlines():
        if line.startswith("UI_ACCESS_KEY="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def create_drafts(listings: list, base="http://localhost:8000") -> list:
    import requests
    key = _env_key()
    ids = []
    for url, label in listings:
        r = requests.post(f"{base}/jobs/from-url", headers={"X-Access-Key": key},
                          data={"url": url, "property_name": label, "model_tier": "luma"}, timeout=60)
        jid = r.json().get("job_id") if r.ok else None
        print(f"  created {label or url}: {jid or 'ERROR ' + r.text[:120]}")
        ids.append((jid, label, url))
    return ids


def _status_from_api(jid: str, base="http://localhost:8000"):
    # 2026-10-28: a refused draft (prep_failed) never writes job_meta.json, so wait_for used to wait the full 900 s.
    # The server keeps the status in memory and returns it on GET /jobs/{id}.
    try:
        d = requests.get(f"{base}/jobs/{jid}", headers={"X-Access-Key": _env_key()}, timeout=30).json()
        return d.get("status")
    except Exception:
        return None


def wait_for(ids: list, jobs_dir: Path = Path("jobs"), max_secs=900) -> None:
    """Wait until every created draft has a job_meta.json whose status is no longer 'preparing' (file based: no HTTP, no guessing)."""
    t0 = time.time()
    while time.time() - t0 < max_secs:
        pending = 0
        for jid, _, _ in ids:
            if not jid:
                continue
            try:
                st = json.loads((jobs_dir / jid / "job_meta.json").read_text()).get("status")
            except Exception:
                st = _status_from_api(jid)
            pending += st in (None, "preparing")
        if not pending:
            return
        time.sleep(10)


def read_listings(path: str) -> list:
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            url, _, label = line.partition("|")
            out.append((url.strip(), label.strip() or url.strip()[-12:]))
    return out


def report(checks: list) -> int:
    fails = 0
    for c in checks:
        lv = [r[0] for r in c["results"]]
        verdict = "FAIL" if "FAIL" in lv else ("WARN" if "WARN" in lv else "PASS")
        fails += verdict == "FAIL"
        print(f"\n[{verdict}] {c['name']} ({c['job']}) mode={c['mode']} claude=EUR {c['claude_eur']}")
        for lvl, i, m in c["results"]:
            print(f"    {lvl:<4} {i:<3} {m}")
    total = len(checks)
    print(f"\nDRAFT CHECK: {total - fails}/{total} listings without FAIL; total Claude cost EUR {round(sum(c['claude_eur'] or 0 for c in checks), 3)}")
    return 1 if fails else 0


def _load_env() -> None:
    try:
        for line in Path(".env").read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
    except Exception:
        pass


def main(argv: list) -> int:
    _load_env()
    jobs = [argv[i + 1] for i, a in enumerate(argv) if a == "--job" and i + 1 < len(argv)]
    files = [a for a in argv if not a.startswith("--") and a not in jobs]
    if files:
        created = create_drafts(read_listings(files[0]))
        wait_for(created)
        jobs += [j for j, _, _ in created if j]
    if not jobs:
        print("usage: python3 draft_check.py golden_listings.txt | --job ID [--job ID ...]")
        return 2
    return report([check_job(j) for j in jobs])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
