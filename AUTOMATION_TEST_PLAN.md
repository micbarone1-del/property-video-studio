# AUTOMATION_TEST_PLAN.md -- E2E risk, control and test plan (FMEA + control plan + V-model)

_Rewritten 2026-10-09 (replaces the first version of this file, kept in git history). Scope: the whole chain from an agency's request in the Relinx CRM to the agency seeing a satisfactory video inside Relinx. Living document: every incident, test round or new finding adds/changes rows. Status words are honest: VERIFIED (date, how), Verified (fn) = function test only, Open, VERIFY = to be checked on the server first. The S/O/D ratings below are a **baseline proposed by Claude from project evidence and must be reviewed by Michele (and S by Relinx)**; they are not measured data._

## 0. How the three tools fit together
- **V-model (section 3)** gives the structure: what the system must do (requirements) on the left, the test level that proves each requirement on the right. Nothing is tested without a requirement; no requirement without a test.
- **FMEA (section 4)** says what can go wrong at each step of the E2E chain, how bad, how likely, how detectable, and what we already do. It decides WHERE the tests go and WHAT to fix first.
- **Control plan (section 5)** is the run-time version for production and for the pilot: what is measured, how often, with which limit, and what happens when it is out of limit.
Traceability: Requirement R -> FMEA rows F -> test T (catalogue in Appendix T) -> status.

## 1. End-to-end process map (what "E2E" means here)
| Step | What happens | Owner | Interface / evidence |
|---|---|---|---|
| P1 | Agency user asks for a video in the Relinx CRM (on demand, Italian) | Relinx | Relinx UI |
| P2 | Relinx builds the request: >=6 photos as signed URLs (3-day expiry), description, per-photo category, `external_ref`, `callback_url` + token | Relinx | `POST /v1/videos` |
| P3 | We authenticate (Bearer key), resolve agency, check 2/24h limit, check idempotency, answer `queued` at once | PVS | HTTP response |
| P4 | Background build: download photos, AI narration, captions, vision QC -> job stays `draft` | PVS | job state |
| P5 | Human review of scenes/narration, then start of generation | Operator | library / API |
| P6 | Generation: watermark, enhance, TTS, clips (Luma/fal/Veo), vision QC | PVS | pipeline |
| P7 | QC gate (`awaiting_approval`), operator approves or reworks (caps) | Operator | QC panel |
| P8 | Final assembly | PVS | final mp4 |
| P9 | Release by operator -> `completed` webhook (signed if secret set) | Operator/PVS | webhook |
| P10 | Relinx receives webhook and re-fetches status | Relinx | `GET /v1/videos/{id}` (VERIFY exists) |
| P11 | Relinx fetches/streams the video and shows it in the CRM | Relinx/PVS | `video_url` (VERIFY partner access) |
| P12 | Agency watches: video is satisfactory (quality, voice, accuracy, logo) | Agency | feedback |
Cross-cutting (X): server/infra, restarts, disk, backups, provider balances and cost, notifications, operator availability, security/legal, test hygiene.

## 2. Requirements (left side of the V)
Targets marked (proposed) need agreement with Relinx; numbers are not facts.
| ID | Requirement | Target | FMEA | Test levels |
|---|---|---|---|---|
| R01 | Valid request accepted and acknowledged `queued` quickly | <= 5 s (proposed) | F01 F49 | Integration, System |
| R02 | One job per `external_ref`; retries never create or charge twice | 0 duplicates | F01 F50 | Integration, System |
| R03 | Photos are persisted at request time | 100% | F03 | Integration |
| R04 | Status of any job retrievable by partner with correct mapping | `GET /v1/videos/{id}` | F34 | Integration, Acceptance |
| R05 | Finished video retrievable by Relinx with partner auth, for an agreed time | >= 30 days (proposed) | F35 F36 F37 | Integration, Acceptance |
| R06 | Completion/failure webhook delivered, signed, retried | delivery >= 99% (proposed) | F32 F33 F31 | Integration, System |
| R07 | Turnaround request->completed | machine time <= 20 min; with human review <= 4 working hours (proposed; Relinx wants faster than ~1 day) | F10 F31 F44 | System, Acceptance |
| R08 | Video quality and accuracy accepted by the agency | >= 90% accepted without rework in pilot (proposed) | F07 F16 F18 F19 F38 | Acceptance |
| R09 | No job lost or silently wrong across restart/crash/rework | 0 | F09 F12 F25 F42 F48 | Component, System |
| R10 | Cost per video within ceiling, recorded once | ceiling TBD after ledger (backlog 57) | F14 F15 F20 F24 F47 | Component, System |
| R11 | Operator informed within minutes of any needs-human state, once | <= 5 min, 1 notification | F10 F23 F45 | Component, System |
| R12 | Capacity: expected daily volume handled without loss | >= 20 requests/day (Phase B), later 100+ | F21 F22 | System |
| R13 | Legal/privacy: processors documented, AI label agreed, HTTPS | before pilot | F06 F39 F40 | Review |
| R14 | Output playable in Relinx player | verified on their staging | F30 F37 | Acceptance |
| R15 | Test activity never contaminates production | 0 | F46 | System |

## 3. V-model test levels (right side of the V)
| Level | Verifies | Where / how | Entry | Exit |
|---|---|---|---|---|
| L1 Component | single functions (cost, recovery, rework policy, cascade, UI predicates) | free fakes, ast/real functions, `test_stageN.py`; commit only on ALL PASS | code written | ALL PASS |
| L2 Integration | our API against the partner contract (schema, auth, idempotency, status, webhook, download) | Phase A simulator [SIM] on a staging/fake-provider instance | L1 done; contract written | contract tests PASS |
| L3 System | whole pipeline under failure: restart, provider errors, rework, load, disk, backup restore | Phase A with fake providers, then small real runs (budget) | L2 done | all `ACT` rows have a PASS test |
| L4 Acceptance | real Relinx requests, real photos, human judgement of the result in Relinx | Phase 1 (30 listings, internal) -> Phase B (window, ~20 requests) -> GIAL pilot (5-10) | L3 done, go/no-go gate G3 | exit criteria G4 |
Test already run (2026-10-08/09): L1 stages 1-4b (all PASS); L3 live: resume (A2), rework cap refusal + banner + Risolto (B2, B5, H1 push once). L2 and most of L3 still to do.

### Gates
- **G1 (before Phase A)**: simulator + fake-provider switch built (off by default, refuses to run in production); R04/R05 endpoints exist or consciously scheduled.
- **G2 (before Phase 1 on real listings)**: every FMEA row with S>=9 has an owner and either a control or an accepted risk written here; HTTPS decision made; balances topped up; spend cap set.
- **G3 (before Phase B window)**: all `ACT` rows closed or accepted by Michele in writing; L2 contract tests PASS; restore test PASS; real partner key issued and tested; stop rule agreed.
- **G4 (before GIAL pilot)**: Phase B exit criteria met (section 6); open S>=8 items none.
- **G5 (go/no-go to paid / more agencies, early December)**: pilot KPIs and agency feedback reviewed.

## 4. FMEA
Scales (1-10). **S** severity: 10 = agency/Relinx cannot get or see the video, or legal/safety harm; 9 = misleading/unsafe content delivered or data/money lost at scale; 8 = failure invisible to us, relationship damage; 7 = visible delay/rework or large cost; 6 = noticeable but recoverable; <=5 = minor. **O** occurrence: 10 = nearly every job, 7 = weekly, 5 = monthly, 3 = rare, 1 = practically never (use real counts from the pilot as soon as available). **D** detection: 1 = automatic and certain before impact, 5 = operator would likely notice, 8-10 = found only by the agency or never. **RPN = S x O x D.** Level `ACT` = S>=9 or RPN>=100 (action mandatory before gate); `watch` = RPN 60-99; `ok` otherwise. Sorted by severity then RPN. 50 failure modes, 33 at level ACT.

| ID | Step | Failure mode | Effect | Cause | S | O | D | RPN | Current control | Action / test | Status | Level |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| F35 | P11 | video_url points to admin-only /jobs/{id}/download | Agency cannot open the video in Relinx | Partner download path not built (VERIFY today) | 10 | 6 | 3 | 180 | None documented | Verify; build partner-authenticated or signed expiring URL | VERIFY | ACT |
| F40 | X | Photos with people/plates/personal data sent to US providers without DPA | GDPR exposure | No DPA, no review | 9 | 4 | 8 | 288 | Relinx holds agency release (belief) | DPA/GDPR review, document processors | Open | ACT |
| F16 | P6 | AI video artifacts: warped walls, invented objects, people, bad camera move | Unusable or misleading video | Generative model limits | 9 | 5 | 6 | 270 | Vision QC (Florence caption diff = weak) + human QC gate | Agent-based QC; acceptance rubric; audit sample | Open | ACT |
| F41 | X | Server down or process dead (manual start, no uptime monitor) | All requests fail unnoticed | screen+start.sh, no watchdog | 9 | 4 | 7 | 252 | None | External uptime monitor + auto-restart (T-A7, T-H3) | Open | ACT |
| F07 | P4 | AI narration invents or distorts facts (rooms, size, price, claims) | Misleading listing video seen by agency/buyers | LLM generation from description | 9 | 4 | 6 | 216 | Human review before generation | Automated fact check vs description (numbers, rooms); sample audit | Open | ACT |
| F34 | P10 | GET /v1/videos/{id} status endpoint missing (Relinx re-fetches status) | Relinx cannot confirm state | Not built as of status.md (VERIFY today) | 9 | 6 | 3 | 162 | None documented | Verify on server; build + contract test | VERIFY | ACT |
| F46 | X | Test traffic pollutes production (zz_ jobs, fake-provider flag left on, test callbacks) | Wrong KPIs or fake videos delivered | Missing guard | 9 | 2 | 6 | 108 | Test naming convention | Fake flag refuses to run in production; KPI filter | Open | ACT |
| F43 | X | Secrets leaked (public repo) | Account takeover, spend | Commit mistake | 9 | 2 | 5 | 90 | .env gitignored | Periodic secret scan | Control exists | ACT |
| F42 | X | Job data lost (rm -rf on jobs/ happened 2026-07-16) | Videos/clips lost | Human/command error | 9 | 2 | 3 | 54 | Absolute rule, nightly backup 30d | Restore test T-G5 | Partly | ACT |
| F38 | P12 | Agency finds video unsatisfactory (quality, voice, framing, accuracy) | Pilot judged a failure | Quality variance, subjective | 8 | 5 | 9 | 360 | Human QC before release | Acceptance rubric, agency feedback form, audit sample | Open | ACT |
| F44 | X | Operator unavailable (solo operator, bus factor) | No reviews/approvals, SLA missed | One person | 8 | 5 | 5 | 200 | Notifications to phone | Handover tiers, remote operator Nov-Dec | Open | ACT |
| F32 | P9 | Webhook delivery fails (Relinx down/5xx/timeout); no retry policy | Relinx unaware of completion | No retry defined | 8 | 4 | 6 | 192 | Relinx re-fetches status (if API exists, see F34) | Retry with backoff + log of deliveries (T-E8) | Open | ACT |
| F39 | P12 | AI-generated label / watermark policy conflict | Legal or brand issue | No legal check yet | 8 | 3 | 8 | 192 | Watermark present | Legal check; per-partner label setting | Open | ACT |
| F21 | P6 | Disk fills (22MB clips, duplicate copies, many jobs) | Jobs fail, server unstable | No disk alert; duplicate clip names | 8 | 3 | 7 | 168 | Nightly backup only | Disk alert; naming cleanup (backlog 59) | Open | ACT |
| F37 | P11 | Relinx re-host/embed fails (size, codec, headers, CORS) | Not playable in CRM | Player constraints unknown | 8 | 3 | 7 | 168 | None | Ask Relinx for player specs; test with their staging | Open | ACT |
| F31 | P9 | Operator forgets to release; completed webhook never fires | Relinx waits forever | Manual release gate, no UI button | 8 | 4 | 5 | 160 | None | Release SLA alert; button | Open | ACT |
| F47 | X | No global spend cap; runaway loop | Large unplanned cost | No cap | 8 | 3 | 6 | 144 | Per-job caps only | Daily/monthly spend cap + alert | Open | ACT |
| F09 | P4 | Background builder crashes silently | Job stuck `queued`/`draft` forever, Relinx waits | Unhandled error in BackgroundTasks | 8 | 3 | 4 | 96 | Failure webhooks at 3 paths; startup recovery | Watchdog: alert if queued/draft older than N min | Partly | watch |
| F28 | P8 | Assembly fails (ffmpeg/moviepy) | No final video | Corrupt clip, codec | 8 | 3 | 3 | 72 | Fallback in unified assembly; failure webhook | T-A, T-D with corrupt clip | Control exists | watch |
| F48 | P3-P4 | Partner job left `queued` by a restart before builder ran | Job lost | Background task not durable | 8 | 3 | 3 | 72 | Startup recovery: failed + webhook (fn-tested) | Live restart test T-A5 | Verified (fn) | watch |
| F04 | P3 | Partner key missing/deactivated/not issued for the real Relinx account | Every request rejected | Key management | 8 | 2 | 2 | 32 | Hashed keys, deactivation tested | Checklist before window: real key issued, tested | Open | ok |
| F11 | P5,P7 | Operator approves a bad scene/narration | Bad video delivered | Human error, fatigue at volume | 7 | 3 | 8 | 168 | QC panel shows flags | Review checklist; random second-look sample | Open | ACT |
| F14 | P6 | Provider credit/key exhausted mid-batch (Anthropic card, ElevenLabs renewal 13 Oct, fal, Luma) | Batch fails, several jobs stop | No balance monitoring | 7 | 4 | 6 | 168 | None | Balance alerts + pre-window top-up checklist | Open | ACT |
| F45 | X | Notification channel fails (ntfy/email) | Operator not informed | Third-party outage | 7 | 3 | 8 | 168 | Multi-topic best-effort (push verified) | Heartbeat/test ping daily; email count check | Partly | ACT |
| F22 | P6 | Many simultaneous jobs exhaust CPU/RAM or provider rate limits | Slow/failed jobs | No confirmed queue/semaphore | 7 | 4 | 5 | 140 | Per-IP rate limiter only | Load test T-G1..G4; add concurrency limit | Open | ACT |
| F29 | P8 | Audio/video desync or double padding | Voice cut/early | Two padding mechanisms (fixed) | 7 | 3 | 6 | 126 | Buffer tests (July) | One sentence per scene (backlog 54); sync check | Partly | ACT |
| F36 | P11 | Video URL expires, file moved or removed; slow download over http | Broken video later | Retention/backup/clean-up | 7 | 3 | 6 | 126 | Nightly backup | Retention rule + link check job | Open | ACT |
| F03 | P2-P4 | Signed photo URL (3-day expiry) expired before we download | Photos missing, job fails or uses wrong set | Queue delay, restart, retry days later | 7 | 3 | 5 | 105 | None documented; originals not all saved (backlog 49) | Persist photos at request time; test with expired URL [SIM] | Open | ACT |
| F18 | P6 | Wrong/missing agency logo or watermark (earlier black box; advertising other firms) | Brand problem for agency/Relinx | Logo config per agency | 7 | 3 | 5 | 105 | Logo normalisation; black-box fixed | Per-agency logo check in acceptance | Partly | ACT |
| F24 | P7 | Repeated reworks burn money | Cost overrun | Operator/automation loop | 7 | 4 | 3 | 84 | Caps per scene/rounds, needs_operator (verified live) | Cost cap value after ledger fix | Verified | watch |
| F25 | P7 | Rework interrupted looks like clean done | Old video delivered as new | Restart during rework | 7 | 3 | 3 | 63 | rework_in_progress marker + recovery (function-tested) | T-A4 live | Verified (fn) | watch |
| F06 | P3,P9 | Plain http on a bare IP (no domain/TLS) | Relinx security review blocks, or payload/URL tampering | No domain yet | 7 | 4 | 2 | 56 | None | Domain + HTTPS before pilot | Open | ok |
| F19 | P6 | Voice not acceptable (news-anchor tone) | Agency dislikes video | Voice choice | 6 | 5 | 8 | 240 | Voice selectable | Voice acceptance in pilot; collect feedback | Open | ACT |
| F10 | P5 | Pre-generation review is a bottleneck or forgotten (release has no UI button) | Turnaround > 24h; Relinx wants faster | Single human, manual gate | 6 | 7 | 4 | 168 | Notification on new partner job | SLA timer + banner for draft jobs + release button; define turnaround target | Open | ACT |
| F08 | P4 | Narration longer than scene durations / overflow | Audio cut or clip too long | Text length vs 5-9s clips | 6 | 5 | 5 | 150 | Duration from audio length; overflow warning not built (task 8) | Warning + test with long descriptions (T-D8) | Open | ACT |
| F13 | P6 | Provider timeout/failure (fal, Luma, Google TTS) | Scene missing | Provider outage | 6 | 6 | 3 | 108 | Cascade; scene marked failed; operator notified | T-C4 [SIM] | Control exists | ACT |
| F27 | P7 | Cap bypassed because scene ids regenerate | Cap does not protect | Non-standard ids; ensure_scene_ids | 6 | 3 | 6 | 108 | Round cap still applies | Test with real job ids (T-B12); count only non-empty requests (T-B11) | Open | ACT |
| F20 | P6-P7 | Cost per job above plan (cascade, resume pay twice, reworks, wrong constants) | Margin lost, no true cost known | Duplicated logic, FX/Luma constants (backlog 57) | 6 | 4 | 4 | 96 | Cost at QC gate (stage 3), rework caps (stage 4) | Ledger fix; cost per job KPI; T-F1..F5 | Partly | watch |
| F33 | P9 | Webhook unsigned (secret unset), replay or spoof | False completion/failure injected | WEBHOOK_SIGNING_SECRET unset | 6 | 2 | 8 | 96 | Callback token per request (Relinx side) | Set secret; agree verification with Relinx | Open | watch |
| F49 | P2 | Relinx changes payload fields/values (contract drift) | Requests fail or mis-map | No contract tests; schema undocumented | 6 | 4 | 4 | 96 | None | Publish schema; contract tests in simulator | Open | watch |
| F12 | P6 | Server restart/crash mid-generation | Job interrupted, work/cost lost | Deploy, OOM, VPS reboot | 6 | 5 | 3 | 90 | Orphan recovery + Riprendi reuses valid work (verified live) | T-A1..A4; auto-restart (T-A7) | Verified | watch |
| F30 | P8 | Output orientation/format not what Relinx player expects | Black bars / unplayable | Portrait vs landscape, codec | 6 | 3 | 5 | 90 | output_format inherited | Test in Relinx player (T-E9) | Open | watch |
| F01 | P2-P3 | Relinx client times out and retries; each retry creates a new job | Duplicate jobs, double cost, rate limit eaten | Synchronous work in POST (happened live 2026-10-02: 4 retries) | 6 | 3 | 4 | 72 | Immediate `queued` return; idempotency on partner_id+external_ref (fixed) | T-E2 + [SIM] retry storm with timeouts | Fixed, retest | watch |
| F26 | P7 | UI shows wrong state (phantom 2nd scene saved; progress panel after refusal) | Operator confusion, paid generation of a bogus scene | UI state bugs (found live 2026-10-09) | 5 | 4 | 6 | 120 | None | Fix UI; test T-B12 | Open | ACT |
| F50 | P4 | Real listing from non-GIAL agency has unusual data (few rooms, long text, other language) | Failure or poor video | Data variability | 5 | 6 | 4 | 120 | Failure paths | Phase 1: 30 listings, 10 hard (T-D) | Planned | ACT |
| F17 | P6 | Photo category/order wrong (kitchen shown as bedroom) | Confusing video, wrong captions | Relinx category mapping, scene ordering | 5 | 4 | 5 | 100 | Per-photo category field | Contract test on categories | Open | ACT |
| F02 | P2 | Fewer than 6 usable photos / corrupt files | Job fails; agency gets nothing | Agency data quality | 5 | 5 | 3 | 75 | Clear 'not enough photos' error + failed webhook | T-D4, T-D9 on real Relinx data | Control exists | watch |
| F23 | P7 | QC flags nearly everything | No real automation, operator overloaded | Strict thresholds | 5 | 6 | 2 | 60 | Banner + counts | Track flag rate KPI | Control exists | watch |
| F15 | P6 | Luma rejects input (400/422) and we escalate to pricier model; or accepts then fails | Cost spike for a bad photo | Cascade design | 5 | 3 | 3 | 45 | No Veo/LTX after 400/422 (stage 4b, verified) | Luma accept-then-fail still cascades: gather data (T-C3) | Partly | ok |
| F05 | P3 | 2/24h per-agency limit blocks legitimate pilot/test traffic | 429s, Relinx UI shows errors | Pilot limit | 4 | 6 | 2 | 48 | Relinx handles 429 | Raise limit for test agency; test 429 path | Open | ok |

**FMEA rules**: re-rate a row after each action (new O/D); add a row after every incident, bug or test failure; review the whole table at each gate and at the checkpoint; never delete a row, mark it closed with date and evidence.

## 5. Control plan (production and pilot)
| Process step | Characteristic | Spec / limit | Measure / detection | Frequency / sample | Reaction plan | Owner |
|---|---|---|---|---|---|---|
| P2-P3 | Ack time of `POST /v1/videos` | <= 5 s | server log | every request | investigate if p95 > 5 s | Tech |
| P3 | Duplicate external_ref | 0 new jobs | idempotency log | every request | check retry handling | Tech |
| P4 | Photos persisted | 100% on disk before queue ack | file count vs request | every job | fail job with clear reason | Tech |
| P4-P5 | Draft/queued age | < 30 min machine, < 4 h human (proposed) | job list age | continuous, alert | notify operator, escalate to Michele | Operator |
| P5 | Narration vs description | no invented number/room | checklist + automated check | 100% in pilot, sample later | edit or reject | Operator |
| P6 | Provider call outcome and model used | no Veo/LTX on 400/422 | log `model_used` | every clip | stop scene, needs_operator | Tech |
| P6 | Cost per job | <= ceiling (TBD) | cost_actual vs estimate | every job | stop rule: >2x estimate pauses requests | Michele |
| P6 | Provider balances | above 7 days of expected use | balance check / alert | daily | top up | Michele |
| P6 | Disk free | > 30% | df | daily + alert | clean/extend | Tech |
| P7 | QC flag rate | < 40% of scenes (proposed) | counts | per day | review thresholds | Tech |
| P7 | Rework per scene / rounds | <= 2 / <= 3 | rework_policy | every rework | needs_operator + one notification | Operator |
| P8 | Final video valid | ffprobe duration > 0, expected orientation | ffprobe | every job | rebuild assembly | Tech |
| P9 | Release lag | < 4 h after QC (proposed) | time between awaiting_approval/done and release | every job | alert operator | Operator |
| P9 | Webhook delivery | 2xx within retry window | delivery log | every event | retry, then alert | Tech |
| P10-P11 | Partner can fetch status and video | HTTP 200 with partner key | synthetic partner probe | every 15 min | alert, fix | Tech |
| P12 | Agency satisfaction | >= 90% accepted | rubric + feedback | every pilot video | analyse, adjust voice/tier/QC | Michele |
| X | App up | 99% in business hours | external monitor | every minute | auto-restart + page | Tech |
| X | Backups | last backup < 26 h, restore tested monthly | backup log + restore drill | daily/monthly | fix script | Tech |
| X | Daily summary | done / failed / needs human / spend | scheduled report | daily | review | Operator |
| X | Test hygiene | no zz_ job in KPIs, fake flag off | config check | before each window | block run | Tech |
Roles: **Operator** = person watching the library and notifications; **Tech** = can restart, read logs, deploy; **Michele** = decisions and spend. Until the remote operator exists all three are Michele.

## 6. Phases, schedule and exit criteria
- **Phase A (now to ~20 Oct)**: build simulator + fake-provider switch, run L2/L3; fix `ACT` rows; verify R04/R05.
- **Phase 1 (2nd half of October)**: ~30 real listings from >=6 agencies through the real channel, ~10 hard cases; internal only, not delivered to agencies. Capture real O values for the FMEA.
- **Phase B (last week of October, 2-3 working days)**: ~20 requests sent by Relinx from the CRM with a separate test callback; real providers; hard spend cap decided in advance (expected EUR 350-400). Exit: >=95% of requests reach `completed`/`in_review` without a developer touching the server; 0 lost; 0 double-charged; every failure visible to the operator within 5 min; 0 duplicate jobs; every video shown correctly in Relinx's player (R14); acceptance rubric >= 90%.
- **GIAL pilot (end Oct/early Nov to end Nov)**: 5-10 videos, one review step kept by Michele; weekly KPI review.
- **Checkpoint (early December)**: G5.
- **Stop rule** (any phase): a job above 2x its estimate, or the same failure 3 times -> pause new requests and decide.
**Leading indicators to watch daily**: needs-human count, draft/queued age, QC flag rate, rework rate, cost per job, failures per provider, webhook failures, notifications sent vs expected.

## 7. Open inputs needed to finish (ask list)
1. VERIFY on the server whether `GET /v1/videos/{id}` and a partner-accessible video download exist today (status.md as fetched predates 7 Oct) -> F34, F35 (S=9/10).
2. Relinx: how do they display the video (stream our URL, download and re-host, player/codec limits), URL lifetime they need, their webhook retry/timeouts, and what they consider "satisfactory".
3. Michele/Relinx: numeric targets: turnaround, cost ceiling per video, acceptable failure rate, volume per day.
4. Michele: review S and O ratings (section 4) and the acceptance rubric (voice, framing, accuracy, logo).
5. Who runs which tests on our side; who is the named contact at Relinx for Phase B.

## Appendix T -- test catalogue (system-level steps, kept from the first version; IDs are referenced above)
Status words as in the first version of this plan. New required tests derived from the FMEA that are not in this catalogue yet: partner status endpoint contract (F34), partner video fetch with partner auth (F35), expired photo URL (F03), webhook retry/replay/signature (F32/F33), Relinx-player playback (F37), balance-exhausted mid-batch (F14), concurrent jobs (F22), disk-low behaviour (F21), spend cap (F47), fake-flag-in-production guard (F46), narration fact check (F07), uptime/auto-restart (F41).

### A. Restart / crash
- **T-A1** Restart while a job is `running` before QC -> job becomes `interrupted` (or `done` if its final video is valid), never stays `running`. VERIFIED 2026-10-08 (fake + live). 
- **T-A2** `interrupted` job + "Riprendi" reuses valid enhanced images, audio and clips; only missing parts are generated and paid. VERIFIED live 2026-10-08/09 (resume -> QC panel -> approval -> final video).
- **T-A3** Restart while `awaiting_approval` -> still `awaiting_approval`, QC panel intact. TO-DO (live).
- **T-A4** Restart during a rework -> old valid video kept, `rework_incomplete` + `needs_operator`, round given back, banner. VERIFIED by function test 2026-10-09 (25/25); live TO-DO.
- **T-A5** Restart of a job with `callback_url` that cannot be recovered -> status `failed` and signed webhook sent once. VERIFIED by function test 2026-10-08; live TO-DO.
- **T-A6** Kill -9 of the server during `job_meta.json` write -> file is old-complete or new-complete, never truncated (atomic write). TO-DO [SIM].
- **T-A7** Server reboot (VPS) -> service comes back by itself. KNOWN GAP: start is manual (`./start.sh`, screen). Decide: systemd unit or watchdog.

### B. Rework
- **T-B1** Same scene a 3rd time -> refused 429, no provider call, `needs_operator`. Function test VERIFIED 2026-10-09. Live: refusal via rounds cap VERIFIED 2026-10-09; per-scene cap with real scene ids TO-DO.
- **T-B2** 4th rework round on a job -> refused. VERIFIED live 2026-10-09 (message shown, banner 🛠, "Risolto" dialog).
- **T-B3** Cost cap (PVS_REWORK_MAX_COST_EUR) -> refused when spend >= cap. Function test VERIFIED; value TO-DO after ledger fix (backlog 57).
- **T-B4** Refusal notifies the operator exactly once, even if retried. Function test VERIFIED; live push+email count TO-DO (check at the next refusal).
- **T-B5** "Risolto" / reset clears counts and flag and is recorded in `rework_budget_resets`. VERIFIED live 2026-10-09.
- **T-B6** Rework while the job is locked by another operation -> 409, nothing started. TO-DO.
- **T-B7** Scene whose regeneration fails -> `rework_failed_scenes`, `needs_operator`, one notification, job not shown as clean success. Function test VERIFIED 2026-10-09; live TO-DO.
- **T-B8** Two sequential reworks of the same scene -> second sees counters of the first. Function test VERIFIED; live TO-DO.
- **T-B9** Cap reached in the middle of a batch (several scenes) -> whole request refused, nothing half-done. Function test VERIFIED.
- **T-B10** Interruption during a QC-triggered redo (approve path) -> same as A4. TO-DO.
- **T-B11** Request with zero valid scene ids must NOT count as a round. KNOWN GAP (found live 2026-10-09: a no-op request consumed a round). Expected FAIL until fixed (backlog 59).
- **T-B12** Rework request carries the real scene ids of a real job (not regenerated ids). TO-DO with a real job.

### C. Providers
- **T-C1** Luma HTTP 400/422 -> same-price fal Luma retry, then scene fails; NO Veo/LTX. VERIFIED 2026-10-09 (fake, server).
- **T-C2** Luma transient error (500/timeout) -> full cascade preserved. VERIFIED 2026-10-09 (fake, server).
- **T-C3** Luma accepts, later `state=failed` -> must not silently escalate to a pricier model. KNOWN GAP (need real data: bad input or content block?).
- **T-C4** fal down / timeout -> bounded wait, scene fails cleanly, operator informed. TO-DO [SIM].
- **T-C5** Provider credit exhausted (Luma/fal/Google TTS) -> clear error, job `failed` or paused, one notification, no retry storm. TO-DO.
- **T-C6** Daily spend cap / low-balance alert. KNOWN GAP (not built).
- **T-C7** TTS provider fallback (Google -> ElevenLabs) works and is costed once. TO-DO.

### D. Photos and listings (Phase 1 with Relinx data, ~30 listings)
- **T-D1** Normal listing (8-12 photos) -> done. 2. Few photos (1-3). 3. Many photos (>20) -> selection/limit behaves. 4. Corrupt / non-image file -> skipped with reason, job continues. 5. Portrait and mixed orientation. 6. Duplicate photos. 7. Photos with watermark/logo. 8. Very long and very short description. 9. Missing fields (no price, no rooms). 10. Non-Italian text. 11. URL scraper listings (idealista/casa.it extraction is unreliable: record the failure rate). Each: I1-I4 + visual quality check by a human (pass/fail + note).

### E. Partner API (Relinx)
- **T-E1** Create job with `external_ref` -> `queued/processing`. 2. Same `external_ref` again -> returns existing non-failed job, no second job, no second cost. 3. Re-request after `failed` -> new job allowed. 4. Status mapping: `awaiting_approval` -> `in_review`; `needs_operator`/`interrupted` stay `processing` (never `failed`). 5. Bad auth / bad payload -> clean 4xx. 6. Rate limit (2 per 24h per agency): raise for the test agency, confirm the limit returns a clear error elsewhere. 7. Signed webhook: signature verifies with `WEBHOOK_SIGNING_SECRET`; replay of an old payload is detectable. 8. Webhook receiver down (500/timeout) -> retry policy. KNOWN GAP: define it. 9. Video URL delivered stays valid for the agreed time. TO-DO. [SIM] for 1-8.

### F. Costs
- **T-F1** Cost recorded at the QC gate (not only at the end). Function test VERIFIED 2026-10-09; live TO-DO on the next real QC-gated job. 2. Rework cost added once per rework. 3. Resume does not double-count clips already paid. 4. Sum of job costs vs provider invoices within an agreed tolerance (needs ledger/FX/Luma constants fixed: backlog 57). 5. Cascade cost visible (which model really ran).

### G. Queue and load
- **T-G1** 5 simultaneous requests -> all finish or queue; none lost. [SIM] 2. 20 requests in a day (Phase B volume). 3. Disk: free space check and alert before it fills (jobs ~100s of MB each). 4. RAM/CPU during 3 parallel jobs. 5. Restore test: restore one job from /var/backups/pvs_jobs/ into a scratch folder and open it. TO-DO.

### H. Operator and observability
- **T-H1** Needs-human cases notify once (push + email) and show in the library banner with the reason. Banner/row VERIFIED live 2026-10-09; push/email count TO-DO. 2. Operator can resolve from the library ("Risolto", "Riprendi", QC panel) without a terminal. VERIFIED for these three. 3. External uptime monitor + alert when the app is down. KNOWN GAP. 4. Daily summary (jobs done / failed / needing a human / spend). KNOWN GAP. 5. Logs reachable by the remote operator without full server access. KNOWN GAP.


