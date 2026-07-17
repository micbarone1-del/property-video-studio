import os, sys, json, base64, time
from pathlib import Path
import requests

def load_key():
    k = os.getenv("UI_ACCESS_KEY", "").strip()
    if k:
        return k
    for line in open(".env").read().splitlines():
        if line.strip().startswith("UI_ACCESS_KEY="):
            v = line.split("=", 1)[1].strip()
            if v and v[0] in "\"'" and v[-1] == v[0]:
                v = v[1:-1]
            return v
    return ""

BASE = "http://127.0.0.1:8000"
HEADERS = {"X-Access-Key": load_key()}

results = []
def record(name, passed, detail=""):
    results.append((name, passed, detail))
    tag = "PASS" if passed is True else ("SKIP" if passed is None else "FAIL")
    print(f"{tag}: {name}" + (f"  [{detail}]" if detail else ""))

TINY_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABALDA4MChAODQ4SERATGCgaGBYWGDEjJR0oOjM9PDkzODdASFxOQERXRTc4UG1RV19iZ2hnPk1xeXBkeFxlZ2P/2wBDARESEhgVGC8aGi9jQjhCY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2P/wAARCAAEAAQDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDQooorzzuP/9k="
)

def make_scene(cap, voice="", dur=5):
    return {"caption": cap, "voiceover": voice, "duration": dur,
            "space_type": "large", "pov_movement": "walk_in_explore"}

def files_payload(n):
    return [("images", (f"s{i}.jpg", TINY_JPEG, "image/jpeg")) for i in range(n)]

print("=" * 70)
print("SUITE C: batch redo endpoint -- real integration test")
print("Creates a disposable job, does NOT touch job 2193129e or any other")
print("existing job. Real Luma+ElevenLabs cost incurred (~5 tiny clips).")
print("=" * 70)

scenes = [make_scene("Scene A", "Frase originale A.", 5),
          make_scene("Scene B", "Frase originale B.", 5),
          make_scene("Scene C", "Frase originale C.", 5)]
r = requests.post(f"{BASE}/jobs/", headers=HEADERS,
    files=files_payload(3),
    data={"config": json.dumps(scenes), "property_name": "TEST_batch_redo",
          "model_tier": "luma", "lighting": "bright_natural", "intensity": "natural_pace",
          "start_generation": "true"})
ok = r.status_code == 200
job_id = r.json().get("job_id") if ok else None
record("C1 create real 3-scene job", bool(ok and job_id), f"status={r.status_code}, job_id={job_id}")

if not job_id:
    print("Cannot continue without a job_id.")
    sys.exit(1)

print(f"Waiting for initial generation to complete (job {job_id})...")
status = None
j = {}
for _ in range(120):
    time.sleep(3)
    rs = requests.get(f"{BASE}/jobs/{job_id}", headers=HEADERS)
    j = rs.json()
    status = j.get("status")
    if status in ("done", "failed", "awaiting_approval"):
        break
record("C2 initial generation completes", status == "done", f"final_status={status}, message={j.get('message')}")

if status != "done":
    print("Initial generation did not complete cleanly, stopping here.")
    sys.exit(1)

job_before = requests.get(f"{BASE}/jobs/{job_id}", headers=HEADERS).json()
scenes_config = job_before["scenes_config"]
scene_ids = [s["scene_id"] for s in scenes_config]

job_dir = Path("jobs") / job_id
clip_paths = {sid: job_dir / "clips" / f"{sid}.mp4" for sid in scene_ids}
mtimes_before = {sid: p.stat().st_mtime for sid, p in clip_paths.items() if p.exists()}

updated_scenes = [dict(s) for s in scenes_config]
updated_scenes[2]["caption"] = "Scene C - caption edited, no redo"
redo_ids = [scene_ids[0], scene_ids[1], "sc_bogus_doesnotexist"]

r3 = requests.post(f"{BASE}/jobs/{job_id}/scenes/redo-batch", headers=HEADERS,
    data={"scenes_config": json.dumps(updated_scenes),
          "redo_scene_ids": json.dumps(redo_ids)})
ok3 = r3.status_code == 200
record("C3 batch redo call accepted", ok3, f"status={r3.status_code}, body={r3.text[:200]}")

print("Waiting for batch redo to complete...")
status2 = None
j2 = {}
for _ in range(120):
    time.sleep(3)
    rs = requests.get(f"{BASE}/jobs/{job_id}", headers=HEADERS)
    j2 = rs.json()
    status2 = j2.get("status")
    if status2 in ("done", "failed"):
        break
record("C4 batch redo completes", status2 == "done", f"final_status={status2}, message={j2.get('message')}")

job_after = requests.get(f"{BASE}/jobs/{job_id}", headers=HEADERS).json()
record("C5 bogus scene_id skipped without crashing batch", status2 == "done")

mtimes_after = {sid: p.stat().st_mtime for sid, p in clip_paths.items() if p.exists()}
regenerated = all(mtimes_after.get(sid, 0) > mtimes_before.get(sid, 0) for sid in [scene_ids[0], scene_ids[1]])
record("C6 scenes A+B clips actually regenerated", regenerated,
       f"A: {mtimes_before.get(scene_ids[0])} -> {mtimes_after.get(scene_ids[0])}, "
       f"B: {mtimes_before.get(scene_ids[1])} -> {mtimes_after.get(scene_ids[1])}")

c_untouched = mtimes_after.get(scene_ids[2], 0) == mtimes_before.get(scene_ids[2], 0)
record("C7 scene C clip untouched (metadata-only, no regen)", c_untouched)

c_caption_saved = job_after["scenes_config"][2]["caption"] == "Scene C - caption edited, no redo"
record("C8 scene C caption persisted without regenerating video", c_caption_saved)

reworks = job_after.get("reworks", [])
record("C9 exactly one combined batch rework cost entry", len(reworks) == 1, f"reworks count={len(reworks)}")

if reworks:
    r_entry = reworks[0]
    expected_video_cost = 2 * 0.46
    record("C10 batch rework cost = 2 scenes at luma rate (0.92)",
           abs(r_entry.get("video_eur", 0) - expected_video_cost) < 0.01,
           f"video_eur={r_entry.get('video_eur')}, expected={expected_video_cost}")
else:
    record("C10 batch rework cost math", None, "SKIPPED - no rework entry")

cost_actual = job_after.get("cost_actual") or {}
cost_before = (job_before.get("cost_actual") or {})
record("C11 cost_actual grand total reflects the rework",
       cost_actual.get("grand_total_eur", 0) > cost_before.get("grand_total_eur", 0),
       f"before={cost_before.get('grand_total_eur')}, after={cost_actual.get('grand_total_eur')}")

out_path = job_after.get("output_path")
out_ok = bool(out_path) and Path(out_path).exists() and Path(out_path).stat().st_size > 1000
record("C12 final reassembled video exists and is non-empty", out_ok, f"output_path={out_path}")

r13 = requests.get(f"{BASE}/jobs/{job_id}/lock-status", headers=HEADERS)
lock_status = r13.json() if r13.status_code == 200 else {}
record("C13 job lock released after batch completes", lock_status.get("locked") == False, f"lock_status={lock_status}")

print()
print("=" * 70)
n_pass = sum(1 for _, p, _ in results if p is True)
n_fail = sum(1 for _, p, _ in results if p is False)
n_skip = sum(1 for _, p, _ in results if p is None)
print(f"RESULTS: {n_pass} PASS, {n_fail} FAIL, {n_skip} SKIPPED (of {len(results)} total)")
print(f"\nTest job: jobs/{job_id} -- delete manually when convenient (real cost incurred)")
if n_fail:
    sys.exit(1)
