import sys
rb = sys.argv[1]; tests = open(sys.argv[2]).read().strip() if len(sys.argv) > 2 else "(not provided)"
d = "2026-10-29"
status = f"""
## {d} (BU) - Judge crop at the video's scale; enforcement back OFF (p15)
- Control test with limit 2.5 (block 256): 18/18 damaged copies recognised, 0/6 false alarms, 0.0487 EUR. Enforcement was switched on (block 257).
- FIRST real GIAL listing 1307 (relinx.it page copies, 25 photos up to 4096x3041): the judge rejected 18 photos as soft -> job a8eef71b failed with failure_code insufficient_photo_quality (the failure path works end to end). Michele looked at the photos: ALL sharp = false alarms. Cause measured (block 260, 49 photos): above 3000 px 33 of 36 'soft'; 1301-2000 px 0 of 7. The crop at REAL pixels of a huge photo is a tiny patch of plain wall.
- Fix: to_video_scale() brings the photo to long side 1920 (the video scale, LANCZOS, smaller photos untouched) before the crop. The pixel blockiness check is NOT rescaled (it needs the original JPEG grid). Enforcement set back to OFF (PVS_QUALITY_ENFORCE=0) until the rerun shows the false alarms gone.
- Tests: {tests}
- Not verified: rerun on the same 64 photos after the fix; the white-band detector on the 1307 page (Michele sees no bands on the site; the tool found bands on 25 of 25).
- Rollback: commit {rb}.
"""
backlog = f"""
## {d} (BU) - Open after p15
- Rerun the 64 test-instance photos with the fix; if false alarms are gone, switch enforcement on again and run 1307 end to end (upscale off).
- Band detector (relinx_pilot_check._content_box): found bands on 25 of 25 photos of the 1307 page, Michele sees none on the site. Check per photo (size, content box).
- Batch of GIAL listings with report and links to the videos; then e2e automation, parallel runs, live report (to be scoped).
"""
plan = f"""
## {d} (BU) - Judge crop at video scale (p15)
- B5/B5b (test_photo_filters 76/76): scale rule and crop size. Status PASS in sandbox. {tests}
- Real-photo check after the fix: not run yet (rerun on 64 photos).
"""
for f, t in (("status.md", status), ("backlog.md", backlog), ("AUTOMATION_TEST_PLAN.md", plan)):
    open(f, "a").write("\n" + t); print(f, ": entry added")
