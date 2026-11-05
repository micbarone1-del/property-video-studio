# Docs update draft, 2026-11-05 (append each section to the file named in its heading; Michele commits)

Verified = output seen from the server or a clip watched by Michele. Not verified = stated as such. Scores in the test-plan section are PROPOSALS until Michele reviews them. All numbers of the calibration are IN-SAMPLE (thresholds fitted on the same labelled clips).

---

## >>> APPEND TO status.md

## 2026-11-05 - Round 6 (conservative prompts), clip acceptance standard v0, shadow mode deployed, validation batch started

**Deployed on production (commit 93eb359, restart via ./start.sh about 15:47, no job running):** clip_standard.py (new), hook in vision_analysis.analyse_output, exp_judge.py and exp_rotation.py now import from clip_standard (one copy of the judge prompt and of the geometry code). Rollback point before this: bbadef3.
- Verified (output seen on the server): git pull fast-forward, grep finds the hook, py_compile OK, test_clip_standard FAILS 0, test_exp_rotation FAILS 0, test_rework_qc ALL PASS, server answered after restart.
- NOT verified: a real production job writing `standard_shadow` into qc_results and a line into standard_shadow_events.jsonl (the first real job after the restart is the first real test); the measured Claude cost of the judge per clip (my estimate about 0.04 USD per clip, provisional; an earlier note of "0.06 USD per video" was too low); `systemctl is-active` prints "activating" because start.sh runs the app in screen (same as 2026-11-04, not a fault).
- SHADOW ONLY: the standard measures and records, it never changes a verdict, a rework or a job state. Kill switch PVS_STANDARD_SHADOW=0. Optional PVS_STANDARD_FEED_NUMBER=1 hands the measured number to the judge: NOT validated, default off.

**Clip acceptance standard v0 (Michele's rule: black and white reject, flags only in validation):** reject if (1) new_max > 0.20 = the share of any sampled frame (0.25 s steps) outside the first frame's field of view, measured with composed similarity transforms; or (2) the Claude judge (6 key frames) says "fail" = something appears/changes/animates inside what was already visible, or backward/downward/very fast. "review" never rejects. Tracking lost = geometry not measured, never a reject alone.
- Calibration on 126 labelled clips (34 bad, 20 part, 72 ok): standard v0 rejects 25/34 bad (74%), 8/20 part, 9/72 ok (12.5%). Judge alone flags 28/34 bad but also 19/72 ok; new_max >= 0.20 alone catches 15/34 bad and 1/72 ok.
- Production archive, 228 clips, UNLABELLED: new_max median 0, 90th percentile 0.114, 95th 0.200; flagged at 0.2: 5%, at 0.3: 3%. If every reject were retried once the extra cost is about +1 USD per video (estimate).
- Direct registration of first and last frame (exp_outside.py) was tried and DISCARDED: parallax and blur, 35% of clips not registrable, no separation. exp_outside.py is left unused.
- Wrong claim corrected: the motion value e_all does not identify rotation (ok clips have similar values).

**Round 6 (conservative prompts on the 7 riskiest scenes, 56 clips, labels by Michele):** bad share R0 (production) 21%, R1 (static token) 29%, R2 (Luma "locked off") 29%, R3 (minimal) 21%, n 14 each. No variant is safer; static prompts add elements or pull backward; failures depend on the scene. Conclusion: no conservative prompt exists; the levers are selection (avoid a scene such as e7f516e3:4) and detection/rejection. A rework is a re-roll and only helps with a detector that rejects.
- Photo-feature analysis (what the photos of risky scenes have in common): inconclusive. Two candidate flags ("opening to unseen space", "dark edge zone") not yet tested (about 0.2 USD).
- Luma: 1080p clip 1.20 USD, 360p draft 0.06 USD (confirmed in the console); no seed, results vary run to run; Douglas agrees the photo matters more than the prompt; keyframes-from-draft proposal rejected by Michele. Account: auto-reload in 50 USD steps (8 reloads, 280 USD), 79.40 USD left, about 200 USD spent all time. Older spend NOT reconciled (earlier pages not available).
- Review of the overnight GIAL jobs (ag_abea5414), Michele's findings, only partly diagnosed: 1321 narration nonsense (root cause: Claude paraphrased a typo in the listing and misplaced "completano"; not regenerated, decision: not now); missing exteriors in 1294, 1321, 1339 (not investigated: discarded facade photos are not listed anywhere); rework made some scenes worse; QC flagged but did not reject. 1305 is last week's job and was wrongly counted in the overnight figures (43.05 EUR).

**Validation batch (started 2026-11-05 15:51, exp_validate.py, log /tmp/validate.log):** 90 fresh scenes (15 per category), one 360p clip each with the production prompt, every clip through clip_standard.evaluate; Michele watches a blind shuffled list (all standard rejects + 15 random passes). Budget 9 USD (cap handed to the guard: spent 21.48 + 9). RESULT NOT YET KNOWN. Proposed go-live criteria (Michele to confirm): catches >= 70% of bad clips and rejects <= 10% of ok clips on the fresh sample; then reject with one retry per scene, cost cap 12 EUR per video unchanged.

**Tools added (experiments, not in the production path):** exp_conservative.py, add_labels_1105.py, exp_risk_features.py, exp_rotation.py (now imports clip_standard), exp_outside.py (discarded), exp_qc_combo.py, exp_validate.py.

---

## >>> APPEND TO backlog.md

## 2026-11-05 - Clip acceptance standard (QC) [SHADOW BUILT, VALIDATION RUNNING, REJECT NOT ACTIVE]
**Requirement (Michele):** black and white reject on agreed, clear quality states; reports/flags are fine only during validation. Acceptable new content at the frame edge is measured as AREA of the frame outside the original field of view (not a count of objects, not a rotation angle), over sampled frames. Anything appearing/changing inside the already visible area is a reject.
**Done:** clip_standard.py in production, shadow mode (see status.md). **Open:**
1. Validation batch result (90 clips) and the go-live decision; threshold 0.20 and the judge rule are in-sample.
2. Activate reject + one retry per scene (touches the main path: note the rollback commit first, plain-language confirmation first).
3. Consolidate with the existing analyse_output Claude check (two Claude calls per clip today: duplicate cost) once the standard is trusted.
4. Speed rule from measured thresholds (accel_last_over_first >= 11.8 or drift_y_std >= 4.5) is NOT in v0; decide after validation.
5. Feed the measured number to the judge (PVS_STANDARD_FEED_NUMBER): needs its own validation.
6. Measure the real judge cost per clip (estimate 0.04 USD).
7. standard_shadow_events.jsonl is outside the nightly backup (backup_jobs.sh covers jobs/ only), same as scene_risk_events.jsonl.
8. Identify risky environments from the validation data (needs >= 10 scenes per category) and feed scene selection (avoid scenes such as e7f516e3:4); keep an exploration share.

## 2026-11-05 - Narration check that replaces nonsense sentences [REQUIRED, NOT BUILT]
**Requirement (Michele):** an automatic check (Claude) that finds nonsense sentences in the narration and REPLACES them with specific facts from the listing or from the photo analysis; it does not remove them and the operator is not in the loop. Interesting results go to the dashboard notifications. Do NOT change the text-to-image pairing. Window descriptions that come from the photos are legitimate; a car space may be an internal garage.
**Evidence:** job 1321 (Claude paraphrased a typo; misplaced "completano"). Chain: NARRATION_PROMPT (listing_scraper.py) then SHORTEN_PROMPT / EXTEND_PROMPT. **Before building:** search for the same logic in the manual-upload path and in the URL-scraper path (architecture discipline). Log a `narration_check` field.

## 2026-11-05 - Other open items
- Table of discarded photos per job, facades included (read-only); investigate duplicates and missing exteriors in 1339, 1294, 1321.
- Dashboard corrections: 1305 is not part of the overnight batch; recompute spend and KPIs; add notifications for Luma auto-reload and narration checks.
- Luma spend reconciliation (needs the earlier billing pages).
- Auto-reload risk: the Luma balance can drain by 50 USD steps unattended; a spend alert is needed (see the provider spend cap item).
- Sequence agreed with Michele: validate the QC standard, put the new workflow in production, then the automatic management of the whole pipeline (queue, approval levels, dashboard). 3D reconstruction only after reporting and automation.
- Four flagged scenes of the overnight jobs not yet reworked.

---

## >>> APPEND TO QUALITY_CRITERIA.md

## 10. Clip acceptance standard v0 (PROPOSED 2026-11-05, shadow mode, not yet enforced)
Applies to every generated clip, before assembly. Thresholds come from 126 labelled clips (in-sample) and must be re-checked on the validation batch.
| ID | Rule | Method | Limit | Result |
|---|---|---|---|---|
| Q09 | New area: the share of any sampled frame (0.25 s steps) that lies outside the field of view of the first frame | A (tracking + composed transforms, clip_standard) | <= 20% of the frame | above = reject |
| Q10 | Content inside the already visible area: nothing may appear, disappear, move, animate or deform (curtains, water, light patches, signs, people, vehicles) | A (Claude judge, 6 key frames) | judge verdict "fail" | = reject; "review" is reported only |
| Q11 | Camera direction: not backward, not downward, not very fast | A (judge) | judge "fail" | = reject |
If the tracking is lost the geometry is not measured and only the judge decides. Flags ("review") are for the validation phase only; the production rule is pass or reject. Q05 and Q06 above stay the human release checks until this standard is validated and enforced.

---

## >>> APPEND TO AUTOMATION_TEST_PLAN.md

## 2026-11-05 - Clip acceptance standard (shadow mode) and validation (scores are PROPOSALS, not reviewed by Michele)

**FMEA rows (proposed):**
- Q5 (existing, QC misses a hallucination, S9 O5 D8 = 360, ACT): new control in shadow mode (standard v0). In-sample it would reject 74% of bad clips at 12.5% false rejects. Do NOT lower O or D until the validation batch and a real enforced run exist. Keep 360.
- S1 shadow hook breaks the existing QC or a job: S8 O2 D3 = 48. Control: hook in try/except inside analyse_output, evaluate() never raises, kill switch PVS_STANDARD_SHADOW=0, verdict code untouched. Tests S7, S17.
- S2 judge cost not under control (a second Claude call per clip): S4 O4 D3 = 48. Control: usage merged into the job's claude_usage; measure the real cost per clip (NOT measured yet).
- S3 false rejects once enforced (good clips rejected, retries cost money): S5 O4 D4 = 80 (in-sample 12.5%). Control: validation criteria before activation, one retry cap, 12 EUR per video cap. Not active yet.
- S4 tracking lost, geometry silently not measured: S4 O4 D3 = 48. Control: recorded as geo_ok false and counted in summary(); never a reject alone. Test S8.
- S5 shadow data polluted by tests or fake providers: S3 O3 D3 = 27. Control: never evaluated from test_*.py or with PVS_FAKE_PROVIDERS=1. Test S14.

**Tests:**
- PASS (output seen on the server 2026-11-05 about 15:45): test_clip_standard S1-S18 FAILS 0; test_exp_rotation FAILS 0; test_rework_qc ALL PASS; test_exp_validate FAILS 0 (V1-V7). The "could not evaluate missing.mp4" line is the expected message of test S7.
- NOT RUN / UNKNOWN: a real production job end to end with the shadow hook (no `standard_shadow` seen in a real job yet); the validation batch result (running); enforcement and retry (not built); the rework path producing standard_shadow (same function, not observed).
- Four invariants (no job lost, no double cost, final state correct and visible, operator informed once): the shadow adds one Claude call per clip (cost counted in claude_usage, amount not yet measured), no state, no verdict. Verified only by the unit tests above.
- Scoreboard in section 8 not recomputed (manual).
