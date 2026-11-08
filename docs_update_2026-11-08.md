# Docs update 2026-11-08 (only facts verified from server outputs; everything else is marked NOT verified / NOT built / PROPOSAL)

## >>> APPEND TO status.md

## 2026-11-08 - Single-question photo vision, listing guard across prod+test, dashboard filters, incident log
**State: production and test instance run the same code (registry check START 14 at commit 2c87da9). Delivery to the agency stays MANUAL.**
- Photo check consolidated: ONE vision question per photo (`_describe_photo` -> what, source, ok), cached by URL, not cached on failure. The same answer feeds category, usability (photo_exclusion), furnished/empty rule and acceptance. Furnished-check module removed. Tests passing on server: test_vision_classify 46/46, test_selection_report 29/29, test_photo_filters 76/76, test_label_first 5/5, plus aerial/feasibility/other_kinds/outdoor_rules suites.
- Label verification: a clear conflict between partner label and vision (partner label living/kitchen/bedroom/bathroom vs a different room, except living<->kitchen; or exterior/outdoor/floorplan/parking/shared/cellar/aerial) excludes the photo, `label_conflict` in the audit. Empty room with a label is used; without a label it is excluded (3 Nov rule). NOT VERIFIED on a real partner payload (not run).
- Aerial and render photos are deferred to the source check. Renders: decision A/B/C still open.
- INCIDENT 2026-11-08: 360p test runs were started for listings 1337 (job 70f03516) and 1312 (job 93432cd3) although both already had finished 1080p videos. Root cause: the duplicate guard looked only in the production jobs folder. Fix: `listing_registry.py` (reads prod + test folders, resolution aware) and `gial_start.same_listing_done`; auto-start uses the same rule. Cost of the two runs is an ESTIMATE (~0.6 / 0.8 EUR), not measured. 7 prod jobs without a listing number are not recognised by the guard.
- Registry state (START 14): finished at 1080p: 1186, 1189, 1235, 1237, 1249, 1263, 1280, 1290, 1294, 1305, 1307, 1310, 1312, 1321, 1336, 1337, 1339. Finished only at 360p: 1291, 1363. Production awaiting_approval: 1252 (3fcff5a9), 1272 (50472245). All other listings: failed or draft. Tracking lists relinx_listings*.txt and gial_test_candidates.txt annotated with this state.
- Job 93432cd3 (1312, 360p): reworked scene 5, then asked approval again. Cause NOT established: no job event history exists and the test log of that session was overwritten by a restart (test start script now uses `tee -a`). Narration drifted from scenes (balcony text over the bathroom).
- Narration cascade: per_scene fallback was used in 16 of 48 reviewed jobs (about one third). Root cause of block failures NOT established; experiment proposed, not run. Per-scene script has no margin and misaligns sentences from scenes; not fixed (on hold until Michele approves changes to narration).
- Speed: clips with too fast motion (frequent on facades, minor on living rooms). Prompt route closed (tried with Luma). `clip_speed_probe.speed` measures motion; AUC fast vs ok 0.96-0.98 on e_all/e_last/e_peak. NOT wired into the pipeline. Decision: threshold control + slow down the FIRST part of the clip (scene stays 5 s), integrated with the existing anchored-timeline speed adjustment (video_assembly MultiplySpeed, 0.8-1.25). Thresholds to be derived and confirmed by Michele before activation.
- Dashboard (operator page): badge `annuncio N`; the two overview cards (jobs waiting / scenes to review) filter the list on click. NOT visually confirmed by Michele; test instance UI port 8002 reachability not confirmed.
- Not built: API feedback to client "input ridotto a causa di xx" (1254 accepted as is); job event history in job_meta (approved); moving all GIAL videos to production under agency GIAL/Relinx (`gial_consolidate.py`, dry run first, only when no job runs).
- Correction: the forced trial of listing 1327 mentioned earlier was never executed.

## >>> APPEND TO backlog.md

## 2026-11-08 - Backlog entries
- **Speed control (priority):** baseline of motion per category from all job clips (read-only), propose thresholds, Michele confirms, then detection in QC (no extra Claude calls) + slowdown of the first part of the clip, apply to job 93432cd3 and future jobs. Test again at 1080p.
- **Narration root cause:** find why anchored/block narration fails ~1/3 of jobs before touching per_scene. Open: run blocks regeneration on past failed jobs with the current model vs a stronger one (no video, small cost, estimate first). Consider a hard gate for sentence-vs-scene mismatch.
- **Job event history** in job_meta (who/what/when per state change) to explain re-approvals.
- **API feedback** "input ridotto a causa di xx" (field or webhook not scoped).
- **Bring GIAL videos to production** under agency GIAL/Relinx with `gial_consolidate.py`.
- **1080p redo:** only 1291 and 1363 lack a 1080p video; at production switch, redo tracking at high resolution.
- **Registry:** collapse rows with same job id (prod copy + test original) in `listing_registry.scan`.
- **Annunci per i prossimi test:** see annotated relinx_listings*.txt; battery 1271, 1254, 1003, 1345, 1273, 1327 all failed/draft at 360p.
- Premium extra-category ideas (not built): ingresso, scale, cantina, parcheggio, piscina (most reliable), plus ripostiglio, cabina armadio, balcone/terrazzo/giardino, sala da pranzo, bagno padronale, cucinino, mansarda, lastrico solare, palestra, locale tecnico, cortile, vista panoramica.

## >>> APPEND TO AUTOMATION_TEST_PLAN.md

## 2026-11-08 - FMEA rows (PROPOSALS, scores to be reviewed by Michele) and test status
| Failure mode | S | O | D | RPN | Level | Control / test |
|---|---|---|---|---|---|---|
| Finished listing produced again (duplicate cost) | 5 | 6 | 3 | 90 | watch | registry guard, test_listing_registry, test_gial_start (PASS on server); fixed today, 7 prod jobs without number not covered |
| Narration per_scene misalignment not caught | 6 | 6 | 8 | 288 | ACT open | no test, no gate yet |
| Too fast clip not caught by QC | 6 | 6 | 7 | 252 | ACT open | probe measured, not wired |
| Unexplained re-approval after rework | 5 | 4 | 8 | 160 | ACT open | needs event history |
Test status: PASS (server): vision classify, selection report, photo filters, label first, listing registry, gial_start. NOT RUN: label mismatch on a real partner payload; any 1080p test of the new vision; dashboard visual check on a tablet.

## >>> APPEND TO QUALITY_CRITERIA.md

## 2026-11-08 - Photo selection criteria
- One question per photo; the same answer is used for category, usability and acceptance.
- Label rule: clear conflict between partner label and vision excludes the photo; empty room needs a label to be used.
- Quality: Haiku judge plus pixel checks (blockiness >= 2.5, period max 3.0, fine-mid max 0.60; OR for pixel defects, AND for blur).
- Speed: criterion defined (motion too high in first part of clip), thresholds not yet set.
