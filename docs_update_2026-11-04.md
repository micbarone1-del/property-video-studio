# Docs update draft, 2026-11-04 (append each section to the file named in its heading; Michele commits)

Verified = output seen from the server or a clip watched by Michele. Not verified = stated as such. Scores in the test-plan section are PROPOSALS until Michele reviews them.

---

## >>> APPEND TO status.md

## 2026-11-04 - Clip prompts, motion detectors, scene risk registry (shadow mode)

**Deployed on production at about 22:24 (restart via ./start.sh, no job was running):** defaults B (nomove), N1 (neutral end-view description), NEAR director target, EYE rule (vertical fixed feature at eye level; guard against targets that tilt the camera down), and the shadow-mode scene risk registry. Rollback points: d6ecccf (before B+N), 4eeccb6 (before EYE default ON), 5a774b9 (before the registry hooks).
- Verified: server answers HTTP 200 after restart; compile OK; test_scene_risk 17/17, test_rework_qc 11, test_clip_qc 44, test_scene_rework 77, director tests 0 FAIL.
- NOT verified: behaviour on a real production job (first real job after the restart is the first real test). `systemctl is-active property-video.service` printed "activating" right after the restart while the server was answering (start.sh runs it in a screen session); cause not investigated.
- Incident (mine, fixed): the deploy block ran test_rework_qc against the real registry, which wrote 7 fake events. File moved to /tmp (not deleted), scene_risk now never records when started from a test_*.py script (explicit PVS_SCENE_RISK overrides).

**Scene risk registry (scene_risk.py, new):** records, from the existing production clip QC only (first generation in api_server, regenerated clips in scene_rework.qc_redone), one JSON line per verdict in scene_risk_events.jsonl (outside jobs/, gitignored). Records successes too. Zero extra cost. Records only; nothing reads it yet. `python3 scene_risk.py` prints the summary; `scene_risk.summary()` is the JSON for the autonomous-management report (see backlog). Not yet covered by the nightly backup (backup_jobs.sh copies jobs/ only).

**Experiment findings today (360p draft tier, about 0.06 USD per 5 s clip; clips judged by Michele's labels, the Claude judge, and local motion measures):**
- Caused by the prompt/target (found, fixed): floor/ground targets tilt the camera down and make clips run toward the road (EYE rule: 0 of 36 downward afterwards); camera-only push-in prompts rush (round 5: C3 flagged 42% vs 21-33%, mean speed 7.6 vs about 6); converting a static plan to a push-in is harmful; words Luma advises against (move/movement/down, movable things) removed and linted.
- NOT caused by the prompt: rotation to the left, "backward", invented rooms. They recur in every configuration on the same scenes. Round 5, 12 scenes x 4 configurations x 2 reps: 3 scenes flagged nowhere, 4 scenes flagged in 3-4 configurations. Identical static prompt on e7f516e3:4 gave 2/2 ok (C0), 1/2 (C3), 0/2 (C2) clips ok.
- Round 5 result: flagged share C0 29%, C1 33%, C2 21%, C3 42% (n 24 each). C2 wins by the stated rule but C0 vs C2 is 2 clips of 24: not distinguishable. No prompt change adopted from round 5. Luma's own static phrase ("Stationary view of ... Locked off camera.") did worse than our micro-parallax prompt on the one static scene tested (C1 0/2 ok vs C0 2/2): one scene, not conclusive, not adopted.
- risk_table.py (all 280 clips of the day, 21 scenes): rate by plan type static 31% / forward 27% / other 31% (no difference); by category it ranges 20-53% but "living" is two scenes of one listing. Six scenes are above 40%: e21367fe:1, 5b09f3ba:1, e21367fe:2, e7f516e3:4, e21367fe:0, e7f516e3:3. Room and plan type do NOT predict risk; photo content has to be examined (not done yet).
- Claude judge vs Michele on 11 clips of round 5: agrees on 10 (one false alarm). Detector (judge review/fail OR motion extremes) catches about 90% of bad clips and flags about 42% of ok ones on 70 labelled clips (thresholds fitted in-sample). Fine as a pre-filter for comparing configurations, not as an approver of client videos.
- Photo sharpness (photo_metrics.py: lap, detail) is stored in photo_audit next to the quality verdict; no threshold applied, no selection behaviour changed.
- Experiment spend: tracked in jobs/_test_scratch/facade/spend.json (source of truth); about 19 USD cumulative by my arithmetic (12.36 before round 5, 5.76 for round 5 clips, judge at most 1.5 cap). Approved loop budget was 9 USD, so it was exceeded; the 3 USD hold-out confirmation was NOT run.
- Vertical photos: video_generation detects the real input orientation (fix 2026-07-17); the scraper has no rule for portrait photos mixed in a landscape listing. Not decided.

**Tools added (experiments, not in the production path):** exp_judge.py, exp_motion_cal.py, risk_table.py, exp_facade.py variants C0-C3, photo_sheet.py (--only, --sharp), photo_metrics.py.

---

## >>> APPEND TO backlog.md

## 2026-11-04 - Scene risk registry (shadow mode built; use of it NOT built)
**Requirement (Michele):** prevent, do not react. A dynamic file of risky scenes that learns on its own: when QC finds a problem that survives rework, it is recorded; the selector must know risky scenes and avoid them; when there is no alternative, use a minimal low-risk prompt; automatic rework is only the last resort. Michele wants to be detached from it as soon as possible. No weekly summary: the information goes into the report of the autonomous management of the Relinx API (the live operator dashboard, NEXT MILESTONE).
**Done (shadow mode, 2026-11-04):** scene_risk.py records every clip-QC verdict (first generation and after rework, successes too) into scene_risk_events.jsonl; summary() gives counts by category, movement and both, and a "risky" flag (n>=10 scenes, >=3 reworked, persistent rate >=25%) that is informational only.
**Not done / open:**
1. Dashboard/report integration: expose summary() in the autonomous-management report (live dashboard item). Nothing reads the registry yet.
2. Photo features: category and plan type do not predict risk (risk_table). Describe the 21 test photos with Claude vision on a fixed checklist (windows with sky, reflections, people, perspective, far background) and compare the 6 risky scenes with the rest; first check the existing foreground-risk feature in vision_analysis/movement_director to avoid a duplicate. Estimated under 0.5 USD; the script must print the cost and need --go.
3. Selector use (prevention): prefer the lower-risk photo of the same room while keeping the acceptance rule (5 photos, 4 rooms); only after enough data and Michele's review of the report. Touches the main path: note the rollback commit first.
4. Low-risk minimal prompt for risky scenes with no alternative: which prompt is safest is unknown; needs a test on the six risky scenes (about 3 USD, cost shown before launch). Candidate: our static micro-parallax prompt (2/2 ok on e7f516e3:4 with C0, but 0/2 with an identical prompt in C2, so noise is large).
5. Operator approval of a flagged scene is a strong false-alarm signal and is not recorded yet; operator rejection likewise.
6. Detector in production QC: the Claude judge plus motion measures run only in experiments; about 40% false alarms. Estimated judge cost about 0.005 USD per clip (0.5 USD for 96 clips, to be verified). Needed to feed the registry with motion problems the current QC does not see. Never auto-rework on it alone.
7. Closed-loop bias: avoiding risky scenes stops data collection on them; keep a small exploration share (draft-tier tests).
8. The registry file is not in the nightly backup (backup_jobs.sh covers jobs/ only): add it.
9. Representativeness: risk learned at 360p draft may not hold at final resolution; ask Luma (see item below) and compare on a few scenes.

## 2026-11-04 - Prompt policy after rounds 1-5
Decisions: stop tuning wording (differences between reasonable prompts are smaller than Luma's randomness); keep the production prompt chain with B+N1+NEAR+EYE; do NOT adopt Luma's "Locked off camera" static phrase on current evidence (one scene); do not use camera-only prompts (rush). The 3 USD hold-out confirmation (C0 vs C2, new scenes) is not worth running: it cannot resolve a 2-clip difference.
Open: static-plan problems (window/terrace views e7f516e3:3,4,5; bathroom mirror/person); facade lateral cases; narration length bug (1312); band detector false positives on 4096 px photos; OOM risk.
Questions for Luma (Douglas) only after our tests: is 360p draft representative of 1080p behaviour, is there a seed, can people/cars be frozen, does "locked off" combine with a slow push-in, mid keyframe/end-frame test.

## 2026-11-04 - Photo selection
- Sharpness (lap/detail) is measured and stored; collect it over the GIAL population before choosing a threshold; compare soft vs sharp at 1080p (needs cost approval).
- Replace the hard "soft" quality cut with a per-category ranking (plain-language confirmation and rollback commit first); the quality verdict was inconsistent on soft photos.
- Facade photos are classified as "parti comuni dell'edificio" (hypothesis: _VISION_OTHER_PROMPT mentions shared street/courtyard).
- Floor plans need their own sub-category.
- Acceptance count (types counted before the quality filter) differs from the selection count.
- Portrait photos mixed with landscape ones in a listing: no rule in the scraper; decide whether to discard them when at least 5 landscape photos over 4 rooms exist.
- Open items kept: partner limit back to 2 at launch; GIAL videos kept for now (reuse decision later); gial_rename --apply not done.

---

## >>> APPEND TO AUTOMATION_TEST_PLAN.md

## 2026-11-04 - Scene risk registry and clip-prompt findings (scores are PROPOSALS, not reviewed by Michele)

**FMEA rows (proposed):**
- Q5 (existing, QC misses a hallucination and the video is delivered, S9 O5 D8 = 360, ACT): new evidence: rotation, "backward" and invented rooms recur on the same scenes with any prompt, so the cause is partly scene-level and random. Control added: scene risk registry (shadow mode, records only; it does not reduce O or D until it is used). Keep 360 until a detector and registry are proven on real jobs.
- R1 registry write breaks a job: S8 O2 D3 = 48. Control: record() never raises, every hook in try/except. Test S7, S13.
- R2 registry polluted by test or fake data: S3 O4 D3 = 36 (happened once on 2026-11-04). Control: no recording from test_*.py or fake providers; the polluted file was moved to /tmp. Tests S6, S15b.
- R3 detector false alarms cause unnecessary rework cost: S4 O5 D3 = 60 (about 40% on labelled clips). Control: rework budget limits; no auto-rework on the detector.
- R4 registry biases selection (avoided scenes stop being observed): S5 O4 D6 = 120 ACT when selector use is built. Control to decide: exploration share. Accepted for now: nothing reads the registry.

**Tests:**
- PASS (output seen on the server 2026-11-04 22:26): test_scene_risk S1-S16 plus S15b, FAILS: 0; test_rework_qc 11; test_clip_qc 44; test_scene_rework 77 (run locally, same result expected on the server after the pull).
- NOT RUN: a real production job end to end with B+N1+NEAR+EYE and the registry hooks; behaviour of the first-generation hook with a real QC "failed" clip; restart under load; the systemd "activating" state.
- Four invariants (no job lost, no double cost, final state correct and visible, operator informed once): the registry adds no cost and no state; verified only by the unit tests above.
