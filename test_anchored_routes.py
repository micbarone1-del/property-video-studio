import re, sys
src = open("api_server.py").read()
ok = True
def chk(n, c):
    global ok; print(("PASS" if c else "FAIL"), n); ok &= bool(c)
m = re.search(r'_JOB_DONE_STATES = .*?\n\n\n(?=@app\.post\("/jobs/\{job_id\}/narration"\))', src, re.S)
ns = {}
exec(m.group(0), ns)
blk, route = ns["_narration_regen_block"], ns["_audio_only_route"]
for st in ("done", "failed", "awaiting_approval"):
    chk(f"AR1 anchored {st} -> /narration refused", blk({"narration_mode": "anchored", "status": st}))
chk("AR2 anchored draft -> allowed", blk({"narration_mode": "anchored", "status": "draft"}) is None)
chk("AR3 non-anchored done -> allowed", blk({"narration_mode": "legacy", "status": "done"}) is None and blk({"status": "done"}) is None)
chk("AR4 anchored: any selection -> revoice", route({"narration_mode": "anchored"}, []) == "revoice" and route({"narration_mode": "anchored"}, ["s1"]) == "revoice")
chk("AR5 other job + scenes -> old path", route({}, ["s1"]) == "scenes")
chk("AR6 other job + nothing -> none", route({}, []) == "none")
chk("AR7 refusal text names the button", "Rigenera solo audio" in blk({"narration_mode": "anchored", "status": "done"}))
chk("AR8 endpoint wired", "_narration_regen_block(job)" in src and "_audio_only_route(job, ids)" in src and "return await revoice_anchored(job_id, background_tasks)" in src)
sys.exit(0 if ok else 1)
