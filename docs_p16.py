d = "2026-10-30"
status = f"""
## {d} (BW) - GIAL pronunciation live; next milestone scoped
- Pronunciation: pronunciation_fixes.json has GIAL -> gial, commit 8faf277 on the server. Checked on the server (block 276): apply_pronunciation_fixes turns "GIAL IMMOBILIARE" into "gial IMMOBILIARE". NOT yet heard on a real video. The two shared videos (1337, 1290) still have the old voice; regenerating voice only has not been checked.
- Michele's standing rule: GIAL is read as a word (gial) in everything produced for GIAL.
- Real videos with upscale off (test instance, 2026-10-29): 1337 (job 6c79ce33) and 1290 (job 86ebb8e4), EUR 8.54 and 8.50 actual; Michele: "molto bene", narration phrases too generic, not specific to the flat (see backlog).
- Next milestone requirements recorded in backlog.md (autonomous queue + live dashboard). Relinx asked for 12 listings via API (10 sale, 2 rent); 1312 (Castel Gandolfo) draft planned as an extra scraping check, not yet run.
"""
backlog = f"""
## {d} (BW) - NEXT MILESTONE (Concurrency + Operator Dashboard): requirements refined by Michele
This REFINES the existing "NEXT MILESTONE - Concurrency + Operator Dashboard" entry and its "Dashboard design principles"; it is not a second feature. One shared queue for all sources, no separate path for API jobs.
Decided 2026-10-30:
1. Goal: a system that manages the queue of API requests on its own. Michele watches ONE live screen.
2. Parallel jobs: configurable ceiling (not a fixed number). Luma is the suspected bottleneck; the real fal/Luma/ElevenLabs concurrency limits are NOT yet measured. Start low, raise by test; on a provider rate-limit answer, back off and retry, never fail the job for that.
3. Approval levels, chosen from the dashboard: L0 every job waits for Michele (as today); L1 jobs start by themselves unless flagged (QC risk, over threshold, unfurnished, few photos); L2 autonomous, only errors and escalations reach Michele. Start at L0 and loosen step by step. The approvals are temporary scaffolding to be removed as trust is earned.
4. Spend limits: per job and per day, configurable from the dashboard (starting daily ceiling EUR 50). When a limit is reached the queue PAUSES and asks Michele to approve raising the threshold; it does not return an error to the partner and does not drop the job.
5. QC and hallucination risk in autonomous mode: (a) automatic rework within limits (attempts and cost), (b) if the risk stays, flag the risk to the customer, (c) if rework does not work yet, escalate to Michele. Rework automation comes AFTER the QC has been validated on 4-5 more listings; those validations are part of the normal test runs (Relinx API listings), not separate runs.
6. Live dashboard (single screen): queue and state of every job, items needing action (approvals, flags, errors) with click-through actions, cost situation (per job, per day, vs thresholds), infrastructure and model health, and the controls for approval level and thresholds. Notifications appear on this screen.
7. Maintenance and checks that come out of the FMEA run inside the automation: infrastructure (disk, memory, services, backup freshness, certificate expiry), provider balances, model availability and behaviour (periodic judge calibration control test), stuck-job watchdog. Anything the automation cannot handle becomes a notification on the dashboard.
8. Security note: the access key of the UI/app is 7 characters; settings changed from the dashboard (thresholds, approval level) need a stronger key before this goes live.
Open: real provider concurrency limits; where the dashboard lives (inside the app behind the key vs separate page); how a risk flag to the customer is worded and delivered through the partner API; language of failure messages (unfurnished message is Italian, others English).
## {d} (BW) - Narration is generic (Michele, after watching 1337 and 1290)
Phrases read as generic, not specific to the flat. Not yet analysed: need the saved narration text and the listing description of one job to see whether the facts are missing or ignored. Related: scene facts feature (colours only, no materials, no place names).
## {d} (BW) - Rental listings (affitto) never tested
GIAL has 10 rentals (2 residential: 1251 Albano 170 mq, 1321 Marino 90 mq). The pipeline has not been tested on a rental: price per month, wording "in affitto", contract type field in the Relinx API (asked in the message to Relinx). Risk: a rental narrated as a sale.
"""
plan = f"""
## {d} (BW) - Autonomous queue + live dashboard: proposed FMEA rows, tests and checks (scores are PROPOSALS, not reviewed by Michele; all tests NOT RUN)
Proposed FMEA rows (ID, step, failure mode, S/O/D, RPN, level):
- Q1 P6 queue manager loses or duplicates a job across a restart/crash: S9 O3 D4 = 108 ACT. Control: queue state persisted with the job, re-read at start; invariant "no job lost, no double cost".
- Q2 P6 parallelism above what Luma/fal accept: failed clips, billed attempts: S7 O5 D5 = 175 ACT. Control: configurable ceiling, back-off on rate-limit answers, limits measured by test.
- Q3 P6 approval level wrongly set (L2 by mistake) so spend starts unreviewed: S8 O3 D4 = 96. Control: default L0, level change logged and shown on the dashboard.
- Q4 P6 spend threshold overshot because parallel jobs check the cap at the same time: S8 O4 D6 = 192 ACT. Control: reserve the estimated cost before starting a job; pause and ask for approval, never error.
- Q5 P7 QC misses a hallucination in autonomous mode and the video is delivered: S9 O5 D8 = 360 ACT. Control: rework within limits, risk flag to customer, escalation to Michele; stays the top open risk (backlog item 11).
- Q6 P7 automatic rework loops and spends repeatedly: S7 O4 D5 = 140 ACT. Control: max attempts and max cost per job, then escalate.
- Q7 P11 dashboard shows a stale or wrong state, Michele misses an escalation: S8 O3 D6 = 144 ACT. Control: state taken from the single job record, "last update" shown, a heartbeat that raises its own alert.
- Q8 P11 notification flood or one missed notification: S7 O4 D5 = 140 ACT. Control: one notification per event, grouped, acknowledgement kept.
- Q9 all infrastructure degrades unnoticed (disk full, memory, service down, backup stale, certificate or provider balance expiring): S8 O4 D6 = 192 ACT. Control: scheduled checks below.
- Q10 all provider or model changes behaviour silently (judge verdicts, narration, clip quality) or a model ID is retired: S7 O4 D7 = 196 ACT. Control: weekly judge calibration control test (about EUR 0.05), model availability probe.
- Q11 all settings changed from the dashboard by someone without the right: S8 O3 D5 = 120 ACT. Control: stronger access key before go-live, changes logged.
Proposed tests (Appendix T, section G/H), all NOT RUN: T-G6 queue order and no loss across a restart; T-G7 concurrency ceiling respected with fake providers; T-G8 threshold reached -> queue pauses, resumes after approval, partner sees no error; T-G9 approval levels L0/L1/L2 behave as defined; T-G10 dashboard shows every job state within a few seconds and each action button works; T-G11 rework limit and escalation; T-G12 infrastructure and model checks raise a notification when a check is forced to fail.
Proposed control-plan additions (maintenance inside the automation): disk and memory, services alive, backup_jobs.sh freshness, certificate expiry, provider balances (Luma, fal, Anthropic, ElevenLabs), model availability probe, judge calibration control test, stuck-job watchdog.
Invariants for every test: no job lost, no double cost, final state correct and visible, operator informed once.
"""
for f, t in (("status.md", status), ("backlog.md", backlog), ("AUTOMATION_TEST_PLAN.md", plan)):
    open(f, "a").write("\n" + t); print(f, ": entry added")
