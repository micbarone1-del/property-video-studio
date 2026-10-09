# AUTOMATION_TEST_PLAN.md -- reliability of the automated flow (Relinx / GIAL pilot)

_Created 2026-10-09. Format as V2_TEST_PLAN.md: numbered steps, each ends PASS or FAIL. Honest status per step: VERIFIED (date, how), TO-DO, or KNOWN GAP (expected FAIL until fixed). Nothing is rounded up._

## 1. Purpose and the four invariants
Goal: show that heavy automation (target 100+ videos, then monitoring by a remote operator) does not lose work, charge twice, hide failures or leave the operator blind. EVERY test must check all four:
- **I1 no job lost**: after the event the job exists, with its photos and any finished clips.
- **I2 no double cost**: money spent once per paid unit; recorded cost matches what actually ran.
- **I3 final state correct and visible**: library and partner API show the true state (not a silent "done").
- **I4 operator informed**: exactly one push+email when a human is needed; none when not.

## 2. Rules for every test
- Test jobs are named `zz_...` and use cheap data. Claude never deletes anything under `jobs/`; the owner removes test jobs by hand. Backup: `backup_jobs.sh` nightly 03:00 -> /var/backups/pvs_jobs/, 30 days.
- Phase A runs on fake providers (switch `PVS_FAKE_PROVIDERS`, **off by default**, never set in production, to be built: item 58a). No real spend.
- Phase B uses real providers and a written spend budget (section 6).
- Never run a destructive test while a real job is running (check `status` of all jobs first).
- Record for each step: date, who, commit hash, PASS/FAIL, note.

## 3. Phase A -- we simulate Relinx (no Relinx needed, no real spend)
Tool to build (58b): `tools/relinx_simulator.py` -- reads a scenario file, sends signed partner-API requests, runs a local webhook receiver, writes a timeline per job and checks I1-I4 automatically. Scenarios below marked [SIM].

## 4. Test steps

### A. Restart / crash
1. Restart while a job is `running` before QC -> job becomes `interrupted` (or `done` if its final video is valid), never stays `running`. VERIFIED 2026-10-08 (fake + live). 
2. `interrupted` job + "Riprendi" reuses valid enhanced images, audio and clips; only missing parts are generated and paid. VERIFIED live 2026-10-08/09 (resume -> QC panel -> approval -> final video).
3. Restart while `awaiting_approval` -> still `awaiting_approval`, QC panel intact. TO-DO (live).
4. Restart during a rework -> old valid video kept, `rework_incomplete` + `needs_operator`, round given back, banner. VERIFIED by function test 2026-10-09 (25/25); live TO-DO.
5. Restart of a job with `callback_url` that cannot be recovered -> status `failed` and signed webhook sent once. VERIFIED by function test 2026-10-08; live TO-DO.
6. Kill -9 of the server during `job_meta.json` write -> file is old-complete or new-complete, never truncated (atomic write). TO-DO [SIM].
7. Server reboot (VPS) -> service comes back by itself. KNOWN GAP: start is manual (`./start.sh`, screen). Decide: systemd unit or watchdog.

### B. Rework
1. Same scene a 3rd time -> refused 429, no provider call, `needs_operator`. Function test VERIFIED 2026-10-09. Live: refusal via rounds cap VERIFIED 2026-10-09; per-scene cap with real scene ids TO-DO.
2. 4th rework round on a job -> refused. VERIFIED live 2026-10-09 (message shown, banner 🛠, "Risolto" dialog).
3. Cost cap (PVS_REWORK_MAX_COST_EUR) -> refused when spend >= cap. Function test VERIFIED; value TO-DO after ledger fix (backlog 57).
4. Refusal notifies the operator exactly once, even if retried. Function test VERIFIED; live push+email count TO-DO (check at the next refusal).
5. "Risolto" / reset clears counts and flag and is recorded in `rework_budget_resets`. VERIFIED live 2026-10-09.
6. Rework while the job is locked by another operation -> 409, nothing started. TO-DO.
7. Scene whose regeneration fails -> `rework_failed_scenes`, `needs_operator`, one notification, job not shown as clean success. Function test VERIFIED 2026-10-09; live TO-DO.
8. Two sequential reworks of the same scene -> second sees counters of the first. Function test VERIFIED; live TO-DO.
9. Cap reached in the middle of a batch (several scenes) -> whole request refused, nothing half-done. Function test VERIFIED.
10. Interruption during a QC-triggered redo (approve path) -> same as A4. TO-DO.
11. Request with zero valid scene ids must NOT count as a round. KNOWN GAP (found live 2026-10-09: a no-op request consumed a round). Expected FAIL until fixed (backlog 59).
12. Rework request carries the real scene ids of a real job (not regenerated ids). TO-DO with a real job.

### C. Providers
1. Luma HTTP 400/422 -> same-price fal Luma retry, then scene fails; NO Veo/LTX. VERIFIED 2026-10-09 (fake, server).
2. Luma transient error (500/timeout) -> full cascade preserved. VERIFIED 2026-10-09 (fake, server).
3. Luma accepts, later `state=failed` -> must not silently escalate to a pricier model. KNOWN GAP (need real data: bad input or content block?).
4. fal down / timeout -> bounded wait, scene fails cleanly, operator informed. TO-DO [SIM].
5. Provider credit exhausted (Luma/fal/Google TTS) -> clear error, job `failed` or paused, one notification, no retry storm. TO-DO.
6. Daily spend cap / low-balance alert. KNOWN GAP (not built).
7. TTS provider fallback (Google -> ElevenLabs) works and is costed once. TO-DO.

### D. Photos and listings (Phase 1 with Relinx data, ~30 listings)
1. Normal listing (8-12 photos) -> done. 2. Few photos (1-3). 3. Many photos (>20) -> selection/limit behaves. 4. Corrupt / non-image file -> skipped with reason, job continues. 5. Portrait and mixed orientation. 6. Duplicate photos. 7. Photos with watermark/logo. 8. Very long and very short description. 9. Missing fields (no price, no rooms). 10. Non-Italian text. 11. URL scraper listings (idealista/casa.it extraction is unreliable: record the failure rate). Each: I1-I4 + visual quality check by a human (pass/fail + note).

### E. Partner API (Relinx)
1. Create job with `external_ref` -> `queued/processing`. 2. Same `external_ref` again -> returns existing non-failed job, no second job, no second cost. 3. Re-request after `failed` -> new job allowed. 4. Status mapping: `awaiting_approval` -> `in_review`; `needs_operator`/`interrupted` stay `processing` (never `failed`). 5. Bad auth / bad payload -> clean 4xx. 6. Rate limit (2 per 24h per agency): raise for the test agency, confirm the limit returns a clear error elsewhere. 7. Signed webhook: signature verifies with `WEBHOOK_SIGNING_SECRET`; replay of an old payload is detectable. 8. Webhook receiver down (500/timeout) -> retry policy. KNOWN GAP: define it. 9. Video URL delivered stays valid for the agreed time. TO-DO. [SIM] for 1-8.

### F. Costs
1. Cost recorded at the QC gate (not only at the end). Function test VERIFIED 2026-10-09; live TO-DO on the next real QC-gated job. 2. Rework cost added once per rework. 3. Resume does not double-count clips already paid. 4. Sum of job costs vs provider invoices within an agreed tolerance (needs ledger/FX/Luma constants fixed: backlog 57). 5. Cascade cost visible (which model really ran).

### G. Queue and load
1. 5 simultaneous requests -> all finish or queue; none lost. [SIM] 2. 20 requests in a day (Phase B volume). 3. Disk: free space check and alert before it fills (jobs ~100s of MB each). 4. RAM/CPU during 3 parallel jobs. 5. Restore test: restore one job from /var/backups/pvs_jobs/ into a scratch folder and open it. TO-DO.

### H. Operator and observability
1. Needs-human cases notify once (push + email) and show in the library banner with the reason. Banner/row VERIFIED live 2026-10-09; push/email count TO-DO. 2. Operator can resolve from the library ("Risolto", "Riprendi", QC panel) without a terminal. VERIFIED for these three. 3. External uptime monitor + alert when the app is down. KNOWN GAP. 4. Daily summary (jobs done / failed / needing a human / spend). KNOWN GAP. 5. Logs reachable by the remote operator without full server access. KNOWN GAP.

### I. Production checklist (not PASS/FAIL tests, owner decisions)
DPA/GDPR with providers and Relinx; legal check on labelling AI-generated video; domain + HTTPS (today http://IP:8000); who is on call; handover tiers (operator / technical / decisions).

## 5. Known UI findings from 2026-10-09 (to fix, see backlog 59)
- Library edit view showed 2 scene cards for a 1-scene job; the extra scene was then saved into the job.
- After a refused rework the "Progress ... 0% / Ferma questo job" panel stays visible although nothing started.

## 6. Phase B -- joint window with Relinx (proposal, to agree with them)
- **When**: last week of October, 2-3 working days, then free official pilot (5-10 GIAL videos) from end October/early November; checkpoint early December.
- **Volume**: Phase 1 (before the window) ~30 listings from >=6 agencies, ~10 of them deliberately hard; Phase B ~20 real requests in the window. Real generation budget ~EUR 350-400 (decide a hard cap in advance).
- **Who**: we run the simulator beforehand (Phase A); Relinx sends real requests from their CRM during the window; we watch the library banner and logs; Relinx reports what they see on their side. One contact each side, named in advance.
- **Proposed success criteria (to confirm with Relinx)**: >=95% of requests end `done`/`in_review` without a developer touching the server; 0 lost jobs; 0 double-charged jobs; every failure visible to the operator within minutes; duplicate `external_ref` never creates a second job; every video that reaches Relinx passed human QC.
- **Stop rule**: if a job spends > 2x its estimate or the same failure repeats 3 times, pause new requests and decide.

## 7. Open items to build (backlog 58)
58a fake-provider switch `PVS_FAKE_PROVIDERS` (off by default, refuses to run if production flag set); 58b `tools/relinx_simulator.py`; 58c spend cap + low balance alert; 58d uptime monitor + daily summary; 58e systemd/watchdog for auto-restart.
