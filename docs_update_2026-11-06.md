# Docs update 2026-11-06 (written from this session's verified outputs; "Verified" = output seen from the server; everything else is stated as not verified)

## >>> APPEND TO status.md

## 2026-11-06 - Automation running on the TEST instance: auto-rework widened, flag auto-approval, auto-start, operator page, release mode, narration rules, render trial
**State at end of day: production code and test instance both at commit 1b69b37 (rollback 0068559, before that a384be7). Delivery to the agency stays MANUAL (Michele approves). PVS_AUTO_START is OFF in production; it is ON only on the test instance (port 8002: 360p, cap 100 EUR, max 2 active, PVS_AUTO_START_NOT_BEFORE = start time, PVS_ACCEPT_RENDERS=1).**
- Auto-rework (PVS_AUTO_REWORK=1 in production .env): now triggers on ANY scene with verdict "reject" (not only measured ones); one automatic rework per scene; refuses when flagged/failed scenes are also pending; budget respected. Fired twice on the test instance, repaired one scene (per session log; not re-verified today).
- Flag auto-approval (PVS_AUTO_APPROVE_FLAGS=1 in production .env, backup .env.bak_20261106): flagged scenes are approved by the system only if ALL flags are minor, none mentions a person (guard added after a "possible human figure" flag was approved), space_matches is not False and there is no error. Approved scenes go to a review list with a notification ("Auto-approved flags") and `review_pending`; the operator clears them with /jobs/{id}/review-done.
- Narration rules (scene_script.py): extended generic/filler phrases, photo facts block "WHAT THE PHOTOS PLAINLY SHOW", view rule (no sea/view claims the photos or the listing do not support). Triggered by real cases: "luminoso e affaccia verso il mare" (Albano Laziale has no sea), "su questo livello della casa" (single-level flat). Unit tests G1-G14 pass.
- Auto-start (auto_start.py, loop in api_server.py): starts partner drafts when the 24 h spend is under the cap (30 EUR agreed, editable) and fewer than MAX_ACTIVE (2) jobs generate; PVS_AUTO_START_NOT_BEFORE ignores older drafts. test_auto_start.py S1-S24, FAILS 0 on the server (verified, run 2026-11-06 15:00).
- Operator page /operator-page (clickable job rows, scene review with approve/redo, release switch manual/automatic, input/output panel: original listing link, photo audit with exclusion reasons, listing text, narration and scene facts). Needs the UI access key (X-Access-Key) like the app. /operator/status, /operator/job/{id}/input, /operator/review-queue, POST /operator/release-mode. The partner request accepts optional `listing_url` (null accepted since 1b69b37).
- Release mode: manual by default; automatic release only when the job has no pending scenes (checks the inner lists of awaiting_scenes). Automatic release NOT exercised on a real job.
- Render acceptance trial (PVS_ACCEPT_RENDERS, default OFF): interior renders are accepted only when the listing has NO real photo; flagged "render_accepted" in the photo audit. Test only. Result on listing 1327: 5 usable photos but 3 environment types -> still refused by the intake rule (job 37e0763f, no cost). This is a TEST, not a rule change; the decision on renders is still open.
- Forced trial of 1327: PVS_MIN_ENVIRONMENT_TYPES (default 4 = the rule; read in listing_scraper.py) lowered on the TEST instance only to let the 5 photos through so the video can be judged; to be removed from the test start script afterwards.
- Failed jobs on the test instance today (7, 12:58-13:34): 4 "insufficient_photos" (0..8 photos, 1..3 types) and 3 "unlabeled_empty_rooms": all intake refusals, no generation, no spend. The 44 older failed jobs on port 8002 and 2 on port 8000 are the same kind (28 Oct - 4 Nov).
- Incidents: (1) the server was restarted while job 1336 (4417c1c5) was generating -> job interrupted, resumed with /jobs/{id}/resume-interrupted (only the missing scene paid). (2) 1290 was picked without checking production; the duplicate guard prevented a repeat spend. (3) updated files were announced but not attached twice; the first deploy of api_server.py used an older upload (GitHub copy stale/older version) -> tests failed S22/S23 and R11; found because sizes and tests were checked.
- Test-instance cost display: jobs run at 360p (PVS_LUMA_RESOLUTION) are priced by the cost model at 1080p list (about 8.6 EUR per job), so test spend is OVERSTATED.
- Known gaps (not fixed): the photo audit is not saved for jobs refused at intake, so the dashboard input panel is empty for them; one voice-length criterion shared by test and production is not yet defined (old single-text band 26-32 s still used by draft_check C3); production auto-start and automatic release never run on a real production job.
- Docs: docs_update_2026-11-04.md, docs_update_2026-11-05.md and docs_update_2026-11-05_b.md had NOT been merged into status/backlog/test plan/quality criteria; merged on 2026-11-06 (this file set).

## >>> APPEND TO backlog.md

## 2026-11-06 - Workflow automation (queue + operator dashboard) [BUILT, RUNNING ON TEST; PRODUCTION AUTO-START OFF]
- Michele's decisions: delivery to the agency stays manual; "release mode" switch manual/automatic in the dashboard (default manual); auto-start cap 30 EUR/day and max 2 jobs generating; automatic first rework on any rejected scene; minor flagged scenes auto-approved with notification and review list; test instance reachable on port 8002 with the UI key.
- To do before switching PVS_AUTO_START on in production: first real production run watched; set PVS_AUTO_START_NOT_BEFORE; confirm release stays manual; partner limit per agency (PVS_PARTNER_AGENCY_LIMIT_24H=40 now) back to 2 at launch.
- To do: save the photo audit also for jobs refused at intake (dashboard input panel); show 360p test jobs at their real price; define the single voice-length criterion (minimum and maximum) from real data and use it in draft_check AND production; unify clip speed/buffer absorption notes; listing registry of Relinx/GIAL listings already tried (job id, outcome, cost) to avoid repeats; dashboard KPIs/trend/mobile (2026-11-05 request); Luma spend alert.
- Renders decision (OPEN): trial on 1327 showed interior renders alone do not satisfy the 4-environment rule. Options: A keep excluding renders; B accept interior renders only when the listing has no real photos (needs the rule on environments reconsidered); C accept always. No new label for renders (Michele, 2026-11-06).
- Narration still open: minimum acceptable voice length (candidate 22-32 s, no short-voice data yet); optional per-sentence Claude check only if filler still leaks; replace (not remove) unsupported sentences.
- 3D (World Labs Atlas beta access obtained): only after automation and reporting.

## >>> APPEND TO AUTOMATION_TEST_PLAN.md

## 2026-11-06 - Automation rows and tests (scores are PROPOSALS, not reviewed by Michele; "not run" stays "not run")
- NEW A5 "Flag auto-approval lets a real defect reach the client": S6 O4 D5 -> RPN 120 (ACT). Control: all-or-none, minor only, no person words, space_matches, review list + notification, delivery stays manual. Tests B1-B19 (test_auto_rework) PASS (unit). Real-job: approvals seen on the test instance; no production job yet.
- NEW A6 "Auto-start spends over the cap or restarts a done listing": S6 O3 D3 -> 54. Control: 24 h cap, MAX_ACTIVE, NOT_BEFORE, duplicate guard. Tests S1-S24 PASS (server, 2026-11-06). Production run NOT RUN (switch off).
- NEW A7 "Server restarted while a job generates": S6 O4 D4 -> 96. OCCURRED 2026-11-06 (1336). Control: resume-interrupted (only missing scenes paid); deploy blocks now stop when /operator/status shows active > 0. Live restart test T-A5 for partner jobs still open.
- NEW A8 "Automatic release delivers a video without approval": S8 O2 D3 -> 48. Control: default manual; auto release only with no pending scenes. Test S22-S24 PASS (unit); real run NOT RUN.
- NEW A9 "Updated file not on the server / older upload": S4 O5 D2 -> 40. OCCURRED twice 2026-11-06. Control: size check + grep + tests in the deploy block.
- NEW A10 "Test-instance cost shown at 1080p price": S2 O6 D2 -> 24 (reporting only). Open.
- Test added today: test_accept_renders.py R1-R11 PASS (server 2026-11-06 15:00); listing_url null bug found by the real 1327 run (R11 asserted the code, not null input) and fixed in 1b69b37.
- Scoreboard today: tests PASS on the server: test_accept_renders, test_auto_start, test_auto_rework, test_selection_report 29/29, test_aerial_filter, test_photo_filters 76/76; real-job tests of auto-start in production and automatic release: NOT RUN.

## >>> APPEND TO QUALITY_CRITERIA.md

## 11. 2026-11-06 - Automation tolerance
- Flagged scenes with only minor findings and no person may be approved by the system (review list + notification); any reject gets ONE automatic rework, then the operator. Delivery to the agency remains manual.
- Narration: no claims (sea, views, floor, light) that the listing text or the photos do not support; unsupported sentences are replaced, not left empty.
- Voice length: one criterion for test and production, minimum and maximum still to be fixed from data.
