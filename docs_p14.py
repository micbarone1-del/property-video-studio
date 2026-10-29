import sys, datetime
rb = sys.argv[1]; tests = open(sys.argv[2]).read().strip() if len(sys.argv) > 2 else "(not provided)"
d = "2026-10-29"
status = f"""
## {d} (BT) - Blockiness limit set from measured data (p14)
- Done: BLOCKINESS_MAX_DEFAULT 4.0 -> 2.5. Measured on the server (block 253): 101 real photos score 1.03-1.436 (median 1.153); the six q3 damaged copies score 3.246-7.174. The old 4.0 let copy 5f44c77a (3.246) through; 2.5 sits ~74% above the real max and ~30% below the lowest damaged copy.
- Honest limits: flags JPEG-grid damage only (roughly quality 20 and below). Pixelated copies (1.44-2.16) and soft/blur are still the models' job. Real-photo false-alarm rate at 2.5 is 0/101 by measurement. Enforcement is STILL OFF (PVS_QUALITY_ENFORCE=0 in .env).
- Also: test C9 (calibrate cap) was flaky (4 parallel workers race); now deterministic (15/15 reruns).
- Control test with the new limit: NOT run yet. 12 'soft' real photos NOT yet verified by Michele.
- Tests: {tests}
- Rollback: commit {rb}.
"""
backlog = f"""
## {d} (BT) - Quality judge: next steps after p14
- Rerun control test (~0.05 EUR, needs OK): criterion >=16/18 recognised and 0 false alarms on originals; then decide on removing PVS_QUALITY_ENFORCE=0.
- Michele to check the 12 real photos flagged 'soft' (real_sheet_soft_1.jpg) -> real false-alarm rate.
- Tell Relinx about failure_code / failure_message (language of messages to decide).
- GIAL 1307 with upscale off: not run.
"""
plan = f"""
## {d} (BT) - Blockiness limit 2.5 (p14)
- Test B4/B4b (test_photo_filters 74/74): default sits between real max 1.436 and damaged min 3.246. Status: PASS (sandbox + server run below). Control test with real Claude after the change: not run.
- {tests}
"""
for f, t in (("status.md", status), ("backlog.md", backlog), ("AUTOMATION_TEST_PLAN.md", plan)):
    open(f, "a").write("\n" + t); print(f, ": entry added")
