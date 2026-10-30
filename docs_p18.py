import sys
rb = sys.argv[1]; tests = open(sys.argv[2]).read().strip() if len(sys.argv) > 2 else "(not provided)"
d = "2026-10-30"
status = f"""
## {d} (BX) - Partner limit per agency is a setting; pilot tool uses one GIAL client (p18)
- Found: the Relinx limit "2 videos per agency per rolling 24h" was the number 2 written in POST /v1/videos. Relinx sending 12 GIAL listings in a day would get 429 from the third on.
- Change: partner_agency_limit_24h() reads PVS_PARTNER_AGENCY_LIMIT_24H (default 2, bad or < 1 value gives 2); the endpoint and its message use it. relinx_pilot_check.py now sends ONE agency_external_id (gial-test) instead of one per listing (the per-listing id existed only to get around the limit; the test instance had 14 duplicate GIAL clients).
- Pilot decision (Michele 2026-10-30): the limit is lifted for the pilot and put back for launch; it becomes a dashboard parameter. The value in .env is set by the operator step after this commit, see the run log.
- Tests: {tests}
- Not verified: a real request above the limit on the test instance; the .env value is NOT counted as done until the block output shows it.
- Rollback: commit {rb}.
"""
backlog = f"""
## {d} (BX) - Parameters for the dashboard (NEXT MILESTONE)
- Partner limit per agency per 24h (PVS_PARTNER_AGENCY_LIMIT_24H now; 2 at launch, higher for the pilot): to be editable from the dashboard.
- Notifications: the mobile push already exists (ntfy via maintenance_scheduler.send_notification, same call as the email). The dashboard must reuse that single path, no second notification system.
- The test instance (port 8002) listens on 127.0.0.1 only (start_test.sh), so its screen cannot be opened from outside by design. Michele wants to see test jobs: solve inside the dashboard (a test-instance view) instead of opening the port.
- New-job email: mark jobs from the test instance or with a T- external_ref as [TEST].
"""
plan = f"""
## {d} (BX) - Partner limit as a setting (p18)
- test_partner_rate_limit: default, valid and invalid values, endpoint uses the setting, one reader of the env value, pilot tool one agency. {tests}
- FMEA note (proposal, not reviewed): a pilot with a lifted limit removes the protection against a partner loop; the per-job and daily spend limits of the queue project are the replacement control. Not built yet.
"""
for f, t in (("status.md", status), ("backlog.md", backlog), ("AUTOMATION_TEST_PLAN.md", plan)):
    open(f, "a").write("\n" + t); print(f, ": entry added")
