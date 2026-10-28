"""P2 (2026-10-28): Luma direct follows the SAME generation up to 900 s (was 300), keeps its id in the log, and a billed generation that
gave no clip is counted in the cost of a failed rework. Fake HTTP and a fake clock: no network, no key, no cost.
Run: python3 test_luma_wait.py"""
import os, sys, logging, tempfile, shutil, json
from pathlib import Path
sys.path.insert(0, os.getcwd())
os.environ["LUMA_API_KEY"] = "test-key"; os.environ.pop("PVS_FAKE_PROVIDERS", None)
import types
for _m in ("fal_client", "anthropic"):     # only where the package is missing (the sandbox); on the server the real ones load
    try: __import__(_m)
    except ImportError: sys.modules[_m] = types.ModuleType(_m)
import video_generation as vg
import clip_provenance as cp
import scene_rework as sr

fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

class Resp:
    def __init__(self, code, payload): self.status_code, self._p, self.text = code, payload, json.dumps(payload)
    def json(self): return self._p

class Clock:
    t = 0
def run(done_at=None, fail_at=None, gen_id="gen-XYZ"):
    """done_at: seconds after which Luma reports completed; fail_at: ... reports failed; neither: never finishes."""
    Clock.t = 0; polls = []
    def fake_sleep(s): Clock.t += s
    def fake_post(url, **kw): return Resp(201, {"id": gen_id})
    def fake_get(url, **kw):
        polls.append(url)
        if done_at is not None and Clock.t >= done_at:
            return Resp(200, {"state": "completed", "output": [{"url": "http://x/v.mp4"}]})
        if fail_at is not None and Clock.t >= fail_at:
            return Resp(200, {"state": "failed", "failure_reason": "nope"})
        return Resp(200, {"state": "dreaming"})
    vg.time.sleep = fake_sleep; vg.requests.post = fake_post; vg.requests.get = fake_get
    vg._LUMA_STATE.lost_generation = None
    msgs = []
    class H(logging.Handler):
        def emit(self, r): msgs.append(r.getMessage())
    h = H(); vg.log.addHandler(h); vg.log.setLevel(logging.INFO)
    try:
        url = vg._generate_luma_direct("http://x/i.jpg", "p", 5)
    finally:
        vg.log.removeHandler(h)
    return url, msgs, polls, Clock.t

check("L1 ceiling is 900 s", vg._LUMA_DIRECT_MAX_WAIT_SECS == 900)
url, msgs, polls, t = run(done_at=420)
check("L2 a generation that needs 420 s (old code gave up at 300) is collected", url == "http://x/v.mp4", (url, t))
check("L3 the same generation id is polled all along", all(p.endswith("/gen-XYZ") for p in polls) and len(polls) > 75)
check("L4 the id is in the log at creation and at completion", sum("gen-XYZ" in m for m in msgs) >= 2, msgs)
check("L5 a finished generation leaves no 'lost' note", getattr(vg._LUMA_STATE, "lost_generation", None) is None)

url, msgs, polls, t = run()
check("L6 never finishing: gives up after 900 s, not before", url is None and 896 <= t <= 904, t)
lg = getattr(vg._LUMA_STATE, "lost_generation", None)
check("L7 the abandoned generation is remembered with its id", lg and lg["id"] == "gen-XYZ" and lg["reason"] == "timeout", lg)
check("L8 the timeout line names the id and says it is probably billed", any("gen-XYZ" in m and "billed" in m for m in msgs), msgs[-2:])

url, msgs, polls, t = run(fail_at=60)
check("L9 a generation Luma reports as failed is not counted as lost", url is None and getattr(vg._LUMA_STATE, "lost_generation", None) is None)
check("L10 its id is in the failure log line", any("gen-XYZ" in m and "failed" in m for m in msgs))

# ---- cost of a failed rework with a billed generation
tmp = Path(tempfile.mkdtemp()); (tmp / "clips").mkdir()
clip = tmp / "clips" / "sc9.mp4"
cp.write_lost(clip, {"id": "gen-A", "reason": "timeout"}, 5)
check("C1 the note is stored next to the clip and can be read", (cp.read_lost(clip) or {}).get("id") == "gen-A")
job = {"cost_actual_raw": {"type": "actual", "total_eur": 6.0, "model_tier": "luma", "video_eur": 5.0}}
lost = sr.lost_generations(tmp, ["sc9", "sc-none"])
check("C2 only the scene with a note is returned, with duration and id", lost == [{"scene_id": "sc9", "duration": 5, "lost_generation": "gen-A"}], lost)
check("C3 the note is consumed: a later failed round cannot count the same call twice", sr.lost_generations(tmp, ["sc9"]) == [])
rec = sr.record_rework_cost(job, lost, "luma", True, job_dir=tmp)
check("C4 the lost generation is priced as one Luma clip and added to the job", rec is not None and len(job["reworks"]) == 1 and rec.get("video_eur", 0) > 0, rec)
check("C5 the displayed total grew", (job["cost_actual"].get("grand_total_eur") or 0) > 6.0, job["cost_actual"])
cp.write_lost(clip, {"id": "gen-B", "reason": "timeout"}, 5); cp.clear_lost(clip)
check("C6 a new attempt clears the old note", cp.read_lost(clip) is None)

# ---- wiring (source)
vsrc = open("video_generation.py").read(); asrc = open("api_server.py").read()
check("W1 the note is written right after the direct call, whatever happens next", "clip_provenance.write_lost(output_path, _LUMA_STATE.lost_generation, duration)" in vsrc)
check("W2 each luma attempt clears the previous note first", "clip_provenance.clear_lost(output_path)" in vsrc)
check("W3 the redo runner counts lost generations of failed scenes", "_sr.lost_generations(job_dir, result[\"failed\"])" in asrc)
shutil.rmtree(tmp, ignore_errors=True)
print(f"\nRESULT: {'ALL PASS' if not fails else 'FAILURES'} ({total - len(fails)}/{total})")
sys.exit(1 if fails else 0)
