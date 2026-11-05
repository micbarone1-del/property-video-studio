# Docs update B, 2026-11-05 evening (SUPERSEDES the "shadow / validation running / reject not active" statements of update A; append each section to the named file; Michele commits)

## >>> APPEND TO status.md

## 2026-11-05 (evening) - Clip standard validated, only the MEASURED rule enforced, 4-video GIAL pilot, auto-rework built (OFF)
- VALIDATION (90 fresh 360p clips, 36 watched by Michele): standard v0 (judge fail OR new_max>0.20) caught about 52% of bad clips and falsely rejected 17.9% -> NOT good enough to enforce as a whole. Caveat: 360p; production judge sees 1080p (behaviour unknown). Recall poorly measured (only 1 bad among 15 sampled passes).
- WHAT IS RELIABLE: geometry (share of a frame outside the first frame's field of view, limit 0.20, strict >). Judge (Claude vision) and the verification step do NOT separate bad from ok (would stop 9/24 clips): judge stays SHADOW/record-only. Content hallucinations at the edge (wxq, bsp, qaq, iya type) are invisible to the measures.
- SPEED: zoom_rate = ln(zoom_net)/duration, limit 0.28 PROVISIONAL, recorded only (speed_over_limit), not enforced. Needs more labelled fast clips and an archive check (228 clips).
- ENFORCED since commit 5343213 (rollback 0386bd7): PVS_STANDARD_ENFORCE=1 -> only measured_verdict=="reject" turns the clip verdict into reject (marks standard_enforced=True).
- 4-VIDEO GIAL PILOT (relinx_pilot_check -> gial_consolidate -> gial_start): 4 videos produced, 1031 refused by the acceptance rule (<5 usable photos / <4 room types). Michele's verdict: flagged scenes are real but PASSABLE defects; measured reject caught a true error. 1237 has no exterior because the listing has no facade photo.
- WASTE: 1186 and 1280 were regenerated although already done in production (~17.4 EUR). Fix: gial_start.py duplicate guard (skips listings with a done video; --again to force), deployed 2026-11-05 (commit 8cfebd5), tests pass.
- APPROVAL STATS (production, 19 jobs with QC stops): flags 28 (18 approved = 64%), rejects 9 (2 approved = 22%); all flags severity "minor", mostly type "structure"; no field separates harmless flags -> flags cannot be auto-approved yet.
- AUTO-REWORK on measured reject: BUILT, DEPLOYED, SWITCH OFF (PVS_AUTO_REWORK absent). auto_rework.py (pure plan) + one hook block in the run_pipeline QC gate that calls the shared _run_redo. Triggers only when the WHOLE stop is enforced measured rejects, one auto rework per scene (job["auto_reworked"]), rework budget respected (rework_policy.evaluate); still rejected after rework -> shared rework QC gate parks the job for the operator (option A). Rollback commit f42f99e (pre-8cfebd5). Tests: test_auto_rework.py A1-A15 pass. NOT yet exercised on a real job. Expected to trigger rarely (measured rejects ~5% of clips).
- TEST FIX: test_standard_enforce.py E1 failed once .env held PVS_STANDARD_ENFORCE=1 (vision_analysis load_dotenv() overrides a popped var); test now sets it to "0" explicitly (commit ed5960f). Test-only; production unaffected.
- COSTS: about 8.7 EUR per video (video 6.62 + Claude ~0.3), rework ~1.11 EUR per scene, judge ~0.008 EUR per clip (~0.05 EUR per video; earlier 0.04-0.06 USD estimates were wrong).
- LUMA: Douglas (2026-11-05) confirmed no seed, no camera-lock / FOV / forward-only control; other Luma App models not in the API. Auto-reload drains balance in 50 USD steps (risk, not reconciled).
- Server: production runs PVS_ANCHOR=1, PVS_ANCHORED_TIMELINE=1, PVS_DIRECTOR=1, PVS_SCENE_FACTS=1, PVS_STANDARD_ENFORCE=1, PVS_PARTNER_AGENCY_LIMIT_24H=40 (back to 2 at launch), PVS_UPSCALE_DEFAULT=0.
- gial_drafts.py (/jobs/from-url drafts) is UNUSABLE for relinx.it ("Site not yet supported") - left unused, do not build on it.

## >>> APPEND TO backlog.md

## 2026-11-05 - Clip acceptance standard (QC) [MEASURED RULE ENFORCED; JUDGE SHADOW ONLY] (replaces the earlier entry's status)
- Decision: enforce ONLY the geometry reject (limit 0.20). Why: validation showed v0 unreliable (52% caught / 17.9% false rejects). Judge and verification stay record-only.
- Open: (1) 1080p judge behaviour; (2) recall of the standard (more labelled passes needed); (3) speed rule: zoom_rate limit 0.28 provisional, needs labelled fast clips + archive check; (4) content hallucinations at the edge not detectable with current measures; the only structural answer is a real second view or 3D (after reporting + automation).
- Rule from Michele: do the detection myself, he checks only disputed clips; keep what works, no heavy new layers.

## 2026-11-05 - Automatic first rework on measured reject [BUILT, OFF, NOT TESTED ON A REAL JOB]
- Scope: only jobs whose whole stop is measured rejects; one auto rework per scene; then pause for the operator (option A). Switch PVS_AUTO_REWORK (default off).
- Open decision: extend to MIXED jobs (also flagged scenes) - needs a "hold" parameter in the shared _run_redo/_rework_qc_gate so pending stops are kept and reassembly is blocked; higher risk (shared path used by every rework). Not done. Michele to choose after seeing real triggers.
- To do: first real run with switch on; verify (a) message "Rework automatico", (b) rework cost in the total, (c) one notification only.

## 2026-11-05 - Feature registry and promotion process [PROPOSED, NOT BUILT]
- Michele: "parcheggiamo tante feature senza usarle". Proposal: features.json (name, switch, state off/shadow/on, owner metric, promote criterion, review date) + read-only status command; a feature moves shadow -> on only with measured evidence and a rollback commit. Review dates must come from Michele (19/11 was a 14-day default of mine, not a decision). Awaiting his OK.

## 2026-11-05 - Other open items (carried)
- Narration check that replaces nonsense sentences (spec above, not built); table of discarded photos incl. facades; scene-risk-based selection (needs data; registry in shadow); dashboard corrections (1305 not overnight, KPIs, Luma auto-reload and narration notifications); Luma older spend reconciliation; optional model switch for high-risk scenes; partner limit back to 2 at launch; 5th test listing not already done in production; speed archive check.

## >>> APPEND TO QUALITY_CRITERIA.md

## 10 (update). Q09-Q11 status 2026-11-05 evening
- Q09 (geometry limit 0.20): ENFORCED (measured, validated on 36 watched clips). Q10 (judge): SHADOW ONLY, not a pass/fail criterion. Q11 (speed, zoom_rate 0.28): PROVISIONAL, recorded only.
- Michele's stage-level tolerance: flagged "structure" defects are acceptable (passable) at this stage; rejects (true errors) are not.

## >>> APPEND TO AUTOMATION_TEST_PLAN.md

## 2026-11-05 evening - FMEA/test updates (scores are PROPOSALS, not reviewed by Michele)
- NEW row A1 "Auto-rework spends money twice / loops": S6 O3 D3 -> RPN 54. Control: one per scene (auto_reworked), rework budget (rework_policy), still-reject -> operator. Tests A1-A15 PASS (unit + source wiring); real-job test NOT RUN.
- NEW row A2 "Auto-rework bypasses a pending review": S7 O2 D3 -> RPN 42. Control: plan() refuses if any flagged/failed/non-measured reject. Test A4-A7 PASS.
- NEW row A3 "Duplicate regeneration of an already-done listing (credit waste)": S5 O5 D2 -> RPN 50 (occurred: ~17.4 EUR). Control: gial_start duplicate guard. test_gial_start S10-S13 PASS.
- NEW row A4 "Test depends on .env (false FAIL)": S2 O3 D2. Control: tests set switches explicitly. test_standard_enforce E1 PASS after fix (ed5960f).
- Q-rows: judge-based false reject 17.9% / recall 52% (validation, 360p) -> judge not enforced; ACT row for undetected content hallucinations (S7, D8) - accepted risk until second view/3D, to be dated by Michele.
- Four invariants for A1: no job lost (PASS unit), no double cost (not run on real job), final state correct/visible (not run), operator informed once (not run).
- Scoreboard: tests added today 15 + 4 (gial) PASS, 0 FAIL; real-job tests of auto-rework NOT RUN.
