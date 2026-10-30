import sys
rb = sys.argv[1]; tests = open(sys.argv[2]).read().strip() if len(sys.argv) > 2 else "(not provided)"
d = "2026-10-30"
status = f"""
## {d} (BY) - Video library by agency (video_library.py)
- Requested by Michele: videos produced in the test area must be classifiable by agency and reusable later (e.g. for GIAL).
- Built: video_library.py reads the finished jobs of the production and the test instance (read-only) and COPIES each video to /var/www/pvs_library/<agency>/<job>_<property>.mp4 (outside the repo and outside jobs/), one card per video, a master index.json + index.html with agency, listing id, property, instance, date, real cost, upscale flag and Michele's review (reusable yes/no, note). Agencies are grouped by NAME (the test instance had 14 GIAL client records, one per listing). Re-runs copy nothing twice and keep the review. --publish adds ONE file to the test-scratch folder under a random name and prints the https link. No delete or move call exists in the tool.
- This is a first step of backlog item 39 (client/property/job library), not the whole item. It is a standalone script, not part of the job pipeline, so no job state or cost logic changed.
- Tests: {tests}
- Not verified: a real copy on the server (output of the run is the evidence); the library is not part of the nightly backup yet (backup_jobs.sh covers jobs/ only).
- Rollback: commit {rb}.
"""
backlog = f"""
## {d} (BY) - Video library: open points
- Reuse rules still to decide with Michele: which videos may be handed over to the agency (voice before the GIAL pronunciation fix, test with page copies of photos), expiry of listings that are sold, labelling.
- Add the library folder to the nightly backup; show the library in the dashboard (agency view, review buttons, publish link).
- Classification is by agency name; sale/rent and zone are not fields yet.
"""
plan = f"""
## {d} (BY) - Video library tests
- test_video_library: finds only finished jobs with a file, groups by agency name, dry run writes nothing, copy is byte-identical, jobs/ untouched, second run copies nothing and keeps the review, publish gives a random-name https link, no delete or move call. {tests}
- Not run on real data yet.
"""
for f, t in (("status.md", status), ("backlog.md", backlog), ("AUTOMATION_TEST_PLAN.md", plan)):
    open(f, "a").write("\n" + t); print(f, ": entry added")
