# AUTOMATION_TEST_PLAN.md -- E2E risk, control and test plan (FMEA + control plan + V-model)

_Rewritten 2026-10-09 (replaces the first version of this file, kept in git history). Scope: the whole chain from an agency's request in the Relinx CRM to the agency seeing a satisfactory video inside Relinx. Living document: every incident, test round or new finding adds/changes rows. Status words are honest: VERIFIED (date, how), Verified (fn) = function test only, Open, Exists, untested = code found but no contract test yet. The S/O/D ratings below are a **baseline proposed by Claude from project evidence and must be reviewed by Michele (and S by Relinx)**; they are not measured data._

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
| P10 | Relinx receives webhook and re-fetches status | Relinx | `GET /v1/videos/{id}` (exists) |
| P11 | Relinx fetches/streams the video and shows it in the CRM | Relinx/PVS | `video_url` -> `/v1/videos/{id}/download` (exists; auth/expiry to agree) |
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
Companion documents: QUALITY_CRITERIA.md (what a finished video must satisfy, release rule) and RELINX_QUESTIONS.md (questions to agree with Relinx). Test already run (2026-10-08/09): L1 stages 1-4b (all PASS); L3 live: resume (A2), rework cap refusal + banner + Risolto (B2, B5, H1 push once). L2 and most of L3 still to do.

### Gates
- **G1 (before Phase A)**: simulator + fake-provider switch built (off by default, refuses to run in production); R04/R05 endpoints exist (confirmed 2026-10-09) and have a contract test.
- **G2 (before Phase 1 on real listings)**: every FMEA row with S>=9 has an owner and either a control or an accepted risk written here; HTTPS decision made; balances topped up; spend cap set.
- **G3 (before Phase B window)**: all `ACT` rows closed or accepted by Michele in writing; L2 contract tests PASS; restore test PASS; real partner key issued and tested; stop rule agreed.
- **G4 (before GIAL pilot)**: Phase B exit criteria met (section 6); open S>=8 items none; quality release rule in QUALITY_CRITERIA.md applied to every video.
- **G5 (go/no-go to paid / more agencies, early December)**: pilot KPIs and agency feedback reviewed.

## 4. FMEA
Scales (1-10). **S** severity: 10 = agency/Relinx cannot get or see the video, or legal/safety harm; 9 = misleading/unsafe content delivered or data/money lost at scale; 8 = failure invisible to us, relationship damage; 7 = visible delay/rework or large cost; 6 = noticeable but recoverable; <=5 = minor. **O** occurrence: 10 = nearly every job, 7 = weekly, 5 = monthly, 3 = rare, 1 = practically never (use real counts from the pilot as soon as available). **D** detection: 1 = automatic and certain before impact, 5 = operator would likely notice, 8-10 = found only by the agency or never. **RPN = S x O x D.** Level `ACT` = S>=9 or RPN>=100 (action mandatory before gate); `watch` = RPN 60-99; `ok` otherwise. Sorted by severity then RPN. 53 failure modes, 36 at level ACT.

| ID | Step | Failure mode | Effect | Cause | S | O | D | RPN | Current control | Action / test | Status | Level |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| F35 | P11 | Video cannot be opened from the CRM: download needs partner auth, link expiry/streaming/range unknown | Agency cannot watch the video in Relinx | video_url = https://api.propertyvideostudioai.com/v1/videos/{id}/download exists; how a browser/player authenticates and how long it lives is unknown | 10 | 4 | 5 | 200 | Download endpoint exists | Contract test with partner key and with Relinx's real player; agree URL lifetime and auth model (Q-B) | Exists, untested | ACT |
| F40 | X | Photos with people/plates/personal data sent to US providers without DPA | GDPR exposure | No DPA, no review | 9 | 4 | 8 | 288 | Relinx holds agency release (belief) | DPA/GDPR review, document processors | Open | ACT |
| F16 | P6 | AI video artifacts: warped walls, invented objects, people, bad camera move | Unusable or misleading video | Generative model limits | 9 | 5 | 6 | 270 | Vision QC (Florence caption diff = weak) + human QC gate | Agent-based QC; acceptance rubric; audit sample | Open | ACT |
| F41 | X | Server down or process dead (manual start, no uptime monitor) | All requests fail unnoticed | screen+start.sh, no watchdog | 9 | 4 | 7 | 252 | None | External uptime monitor + auto-restart (T-A7, T-H3) | Open | ACT |
| F07 | P4 | AI narration invents or distorts facts (rooms, size, price, claims) | Misleading listing video seen by agency/buyers | LLM generation from description | 9 | 4 | 6 | 216 | Human review before generation | Automated fact check vs description (numbers, rooms); sample audit | Open | ACT |
| F34 | P10 | GET /v1/videos/{id} returns wrong state or fields (Relinx re-fetches status) | Relinx shows wrong state | Endpoint exists (grep 2026-10-09: GET /v1/videos/{id} and list); contract not tested | 9 | 3 | 4 | 108 | Endpoint + status mapping exist | Contract test: every internal state -> expected external state, incl. needs_operator/interrupted | Exists, untested | ACT |
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
| F52 | P4,P6 | A new language is enabled without its golden set or a native-level reviewer (language parameter exists, only Italian live) | Wrong voice/format/pronunciation reaches agencies | Language-general design, no per-language acceptance | 7 | 3 | 7 | 147 | Only Italian enabled | Rule: a language is supported only after golden set + native reviewer sign-off | Planned | ACT |
| F22 | P6 | Many simultaneous jobs exhaust CPU/RAM or provider rate limits | Slow/failed jobs | No confirmed queue/semaphore | 7 | 4 | 5 | 140 | Per-IP rate limiter only | Load test T-G1..G4; add concurrency limit | Open | ACT |
| F29 | P8 | Audio/video desync or double padding | Voice cut/early | Two padding mechanisms (fixed) | 7 | 3 | 6 | 126 | Buffer tests (July) | One sentence per scene (backlog 54); sync check | Partly | ACT |
| F36 | P11 | Video URL expires, file moved or removed; slow download over http | Broken video later | Retention/backup/clean-up | 7 | 3 | 6 | 126 | Nightly backup | Retention rule + link check job | Open | ACT |
| F03 | P2-P4 | Signed photo URL (3-day expiry) expired before we download | Photos missing, job fails or uses wrong set | Queue delay, restart, retry days later | 7 | 3 | 5 | 105 | None documented; originals not all saved (backlog 49) | Persist photos at request time; test with expired URL [SIM] | Open | ACT |
| F18 | P6 | Wrong/missing agency logo or watermark (earlier black box; advertising other firms) | Brand problem for agency/Relinx | Logo config per agency | 7 | 3 | 5 | 105 | Logo normalisation; black-box fixed | Per-agency logo check in acceptance | Partly | ACT |
| F24 | P7 | Repeated reworks burn money | Cost overrun | Operator/automation loop | 7 | 4 | 3 | 84 | Caps per scene/rounds, needs_operator (verified live) | Cost cap value after ledger fix | Verified | watch |
| F25 | P7 | Rework interrupted looks like clean done | Old video delivered as new | Restart during rework | 7 | 3 | 3 | 63 | rework_in_progress marker + recovery (function-tested) | T-A4 live | Verified (fn) | watch |
| F19 | P6 | Voice not acceptable (news-anchor tone) | Agency dislikes video | Voice choice | 6 | 5 | 8 | 240 | Voice selectable | Voice acceptance in pilot; collect feedback | Open | ACT |
| F10 | P5 | Pre-generation review is a bottleneck or forgotten (release has no UI button) | Turnaround > 24h; Relinx wants faster | Single human, manual gate | 6 | 7 | 4 | 168 | Notification on new partner job | SLA timer + banner for draft jobs + release button; define turnaround target | Open | ACT |
| F53 | P5,P7,P12 | Single-reviewer bias or reviewer disagreement (Michele alone; criteria read differently) | Inconsistent releases, defects missed | Small team | 6 | 4 | 7 | 168 | Reviewers decided 2026-10-09: internal phase Michele + Relinx contact; pilot Michele + agency | Common rubric, calibration on 5 videos, record disagreements | Planned | ACT |
| F08 | P4 | Narration longer than scene durations / overflow | Audio cut or clip too long | Text length vs 5-9s clips | 6 | 5 | 5 | 150 | Duration from audio length; overflow warning not built (task 8) | Warning + test with long descriptions (T-D8) | Open | ACT |
| F51 | P6,P12 | AI label light grey is illegible on bright walls, or missing in some scenes | Label requirement not met; agency/legal issue | Light grey text-only English label over variable backgrounds (decision 2026-10-09) | 6 | 5 | 4 | 120 | None yet (watermark change not built) | No shadow (decision 2026-10-09: it could become a problem), so the contrast check on frames (Q31) is the only safeguard; test on bright and dark photos; if contrast fails, choose a darker grey or another position with Michele. O may need re-scoring (up) after the first real frames | Open | ACT |
| F13 | P6 | Provider timeout/failure (fal, Luma, Google TTS) | Scene missing | Provider outage | 6 | 6 | 3 | 108 | Cascade; scene marked failed; operator notified | T-C4 [SIM] | Control exists | ACT |
| F27 | P7 | Cap bypassed because scene ids regenerate | Cap does not protect | Non-standard ids; ensure_scene_ids | 6 | 3 | 6 | 108 | Round cap still applies | Test with real job ids (T-B12); count only non-empty requests (T-B11) | Open | ACT |
| F20 | P6-P7 | Cost per job above plan (cascade, resume pay twice, reworks, wrong constants) | Margin lost, no true cost known | Duplicated logic, FX/Luma constants (backlog 57) | 6 | 4 | 4 | 96 | Cost at QC gate (stage 3), rework caps (stage 4) | Ledger fix; cost per job KPI; T-F1..F5 | Partly | watch |
| F33 | P9 | Webhook unsigned (secret unset), replay or spoof | False completion/failure injected | WEBHOOK_SIGNING_SECRET unset | 6 | 2 | 8 | 96 | Callback token per request (Relinx side) | Set secret; agree verification with Relinx | Open | watch |
| F49 | P2 | Relinx changes payload fields/values (contract drift) | Requests fail or mis-map | No contract tests; schema undocumented | 6 | 4 | 4 | 96 | None | Publish schema; contract tests in simulator | Open | watch |
| F12 | P6 | Server restart/crash mid-generation | Job interrupted, work/cost lost | Deploy, OOM, VPS reboot | 6 | 5 | 3 | 90 | Orphan recovery + Riprendi reuses valid work (verified live) | T-A1..A4; auto-restart (T-A7) | Verified | watch |
| F30 | P8 | Output orientation/format not what Relinx player expects | Black bars / unplayable | Portrait vs landscape, codec | 6 | 3 | 5 | 90 | output_format inherited | Test in Relinx player (T-E9) | Open | watch |
| F01 | P2-P3 | Relinx client times out and retries; each retry creates a new job | Duplicate jobs, double cost, rate limit eaten | Synchronous work in POST (happened live 2026-10-02: 4 retries) | 6 | 3 | 4 | 72 | Immediate `queued` return; idempotency on partner_id+external_ref (fixed) | T-E2 + [SIM] retry storm with timeouts | Fixed, retest | watch |
| F06 | P3,P9 | API domain/TLS not verified end to end; operator UI is still plain http on IP:8000 | Relinx blocks, tampering, expired certificate | Partner URLs already use api.propertyvideostudioai.com; certificate validity/renewal and http->https not checked; UI on IP | 6 | 3 | 3 | 54 | Domain in use for partner URLs | Check certificate + auto-renew + redirect; decide UI access (domain or VPN) | Partly | ok |
| F26 | P7 | UI shows wrong state (phantom 2nd scene saved; progress panel after refusal) | Operator confusion, paid generation of a bogus scene | UI state bugs (found live 2026-10-09) | 5 | 4 | 6 | 120 | None | Fix UI; test T-B12 | Open | ACT |
| F50 | P4 | Real listing from non-GIAL agency has unusual data (few rooms, long text, other language) | Failure or poor video | Data variability | 5 | 6 | 4 | 120 | Failure paths | Phase 1: 30 listings, 10 hard (T-D) | Planned | ACT |
| F17 | P6 | Photo category/order wrong (kitchen shown as bedroom) | Confusing video, wrong captions | Relinx category mapping, scene ordering | 5 | 4 | 5 | 100 | Per-photo category field | Contract test on categories | Open | ACT |
| F02 | P2 | Fewer than 6 usable photos / corrupt files | Job fails; agency gets nothing | Agency data quality | 5 | 5 | 3 | 75 | Clear 'not enough photos' error + failed webhook | T-D4, T-D9 on real Relinx data | Control exists | watch |
| F23 | P7 | QC flags nearly everything | No real automation, operator overloaded | Strict thresholds | 5 | 6 | 2 | 60 | Banner + counts | Track flag rate KPI | Control exists | watch |
| F15 | P6 | Luma rejects input (400/422) and we escalate to pricier model; or accepts then fails | Cost spike for a bad photo | Cascade design | 5 | 3 | 3 | 45 | No Veo/LTX after 400/422 (stage 4b, verified) | Luma accept-then-fail still cascades: gather data (T-C3) | Partly | ok |
| F05 | P3 | 2/24h per-agency limit blocks legitimate pilot/test traffic | 429s, Relinx UI shows errors | Pilot limit | 4 | 6 | 2 | 48 | Relinx handles 429 | Raise limit for test agency; test 429 path | Open | ok |
| F54 | P4,P7 | UI shows stale or duplicated scene cards when a job is opened (previous job's cards copied over the loaded values; two overlapping editJob() calls push into the same file list -> 9-12 cards for 6 scenes, repeated photos, wrong room labels) | Operator reviews and may save a wrong video; false alarms on good jobs | editJob() wrote shared global state; no sequence guard (found 2026-10-12) | 7 | 6 | 5 | 210 | Fix 69c3af2 (cards emptied) + this commit (sequence token, data built locally) | T-B12 + node race test (control reproduces 12 cards on old code, 6 on new); live re-check on Via Giulia v5 pending | Fixed, live check pending | ACT |
| F55 | P4 | Scraped photo URL truncated (".../image/<id>/", 404) or resolution upgrade returns 403 on GET | Job creation fails (422) or photo missing | Page reader output; CDN HEAD ok but GET 403 | 6 | 5 | 3 | 90 | Shared fetch with fallback to original URL, URL normalisation, selection_report (commits 0dcc5ad, 0bdd62d); tests 29+11 PASS | Real listings Via Giulia and Euclide created with 6 scenes in server log | Verified | watch |
| F56 | P4 | Page-read photo categories are unstable between readings (living 4 -> 1, exterior 0 -> 2) and sometimes wrong (kitchen as exterior) | Wrong rooms in the video, wrong captions/camera | Non-deterministic page reading | 6 | 8 | 6 | 288 | Selection report shows what was used; manual review | Superseded 2026-10-12 night by A+: interior labels kept, vision only on exterior/outdoor candidates (shared function); then re-run the same listings twice and compare | Built, not run live | ACT |
| F57 | P4,P5 | Narration length measured twice with different results (scraper 22.3 s vs UI 29.5 s) | UI message "video esteso a N s", planned scene count does not match audio | Two TTS/duration implementations (architecture discipline) | 5 | 8 | 4 | 160 | UI extends duration | Package 2: one shared implementation (decision pending) | Open | ACT |
| F58 | P4 | "&" (and similar characters) in agency names break TTS | Narration fails or mispronounced | Unsanitised text to TTS | 6 | 4 | 3 | 72 | Sanitiser, test_tts_sanitize 9 PASS | Keep test in suite | Verified | watch |
| F59 | P4,P7 | "Genera voiceover" calls draft/resync, which can overwrite server job data with the UI state | Good job data replaced by stale UI values | resync trusts the UI | 7 | 3 | 6 | 126 | UI cause fixed (F54); server-side guard postponed | Decide server guard after F54 live check | Open | ACT |
| F60 | P4 | Standard-video acceptance rule (>=5 usable photos AND >=4 environment types) rejects a listing a human would accept, or accepts a weak one | Lost video for a good listing, or a poor video produced | Rule is a proposal to be tested (Michele 2026-10-12); category labels still unstable (F56) | 5 | 4 | 4 | 80 | Rejection happens before narration/TTS cost; reason + counts stored in the job (failure_code, failure_reason, selection_report.acceptance) | Run the ~30 real listings (Phase 1), list every rejection and judge it; tune thresholds only on that evidence | Built, not run live | watch |
| F62 | P4 | New listing site (annunci.getrix.it) read by the generic page reader: photo paths missing, relative, thumbnails only, or wrong categories (no captions) | Job with 0 or low-quality photos, or wrong scene order | Site never tested; paths are relative; no captions | 5 | 5 | 3 | 75 | Domain allow-list (other sites still refused); URLs made absolute; _hd verified by HEAD; human review of scenes before any paid generation | Run the real page once and review the chosen photos (unit tests G1-G7 PASS) | Run live 2026-10-15: page reader returned 0 photos (FAILED); adapter not built by decision; handled by a one-off manual vision test | watch |
| F63 | P5 | Scene durations over-estimated: narration buffer counted twice (scene allowance + blank frames), extension given to the first scene | Longer/more expensive Luma video than needed, dead air at the end, pictures out of sync with the narration | Rule differed between narration.py, assembly and ui.html | 3 | 5 | 3 | 45 | One rule now in narration.py + assembly + ui.html; extra seconds on the last scene | test_narration_durations.py 13 PASS (sandbox); a real generation after the change is NOT yet run; URL workflow derivation (listing_scraper.py) still on the old inside-the-scenes model | Built, not run live | watch |
| F64 | P5 | Luma invents a person in a mirror (bathroom) | Unusable scene, repeated paid redo | Mirror was already in the photo, rule only forbade new mirrors | 3 | 4 | 4 | 48 | Mirror/reflection rule added to the single Luma rules constant | test_prompt_rules.py 5 PASS (source-level); NOT verified on a real clip | Built, not run live | watch |
| F65 | P5 | Narration not synchronised with the pictures / length unpredictable (Luma) | Sentence about a room spoken while another room is shown; silence or overrun at the end | Durations estimated, scenes extended, pauses fixed | 3 | 4 | 4 | 48 | plan_sentence_sync adds pauses so sentences start on scene cuts; scenes fixed at 5 s; overrun above 2 s is refused with a shorten message | test_narration_sync.py 22 PASS (sandbox; audio part with a pydub stand-in); NOT verified on a real generation | Built, not run live | watch |
| F66 | P5 | URL/Relinx narration built by a different mechanism than the manual one (whole-text TTS, buffers counted inside the scenes, band 24-28 s) | Automated videos with speech not aligned to the pictures, wasted seconds, last words cut by the safety trim | Duplicate implementation of the narration/duration logic (architecture discipline) | 3 | 4 | 4 | 48 | URL, Relinx and manual now share narration.synthesize_sentences/assemble_narration and the same constants (MAX_OVERFLOW_SECS, TOO_SHORT_THRESHOLD_SECS) | test_standard_3b 32 PASS, test_package1 26 PASS (sandbox, stand-in audio); NOT verified on a real URL job | Built, not run live | watch |
| F67 | P5 | Direct Luma refused (402 credits/budget) and the code switches silently to fal.ai Ray 2 / Veo | Unplanned cost (USD 2.00 per clip vs 1.20 direct; USD 20 invoice 2026-10-15), different quality, nobody informed | Silent fallback cascade; no balance check; no per-clip record of the model | 6 | 6 | 7 | 252 | Patch A: per-clip model sidecar, `fal_usage` in the job API, red UI banner, `FAL_FALLBACK_ENABLED` switch; Michele sets Luma auto-reload threshold/amount | test_clip_provenance 28 PASS, test_fake_video_cascade 13 PASS (sandbox); deployed f690d99; live 2026-10-22: real rework on direct Luma OK; banner on a real fallback NOT verified | Deployed, partly verified | ACT |
| F68 | P5 | Per-scene narration states something the listing does not support (number, feature, floor, price) | A false claim spoken in a video sent to customers | Claude writes the text; the fact check is a heuristic, not a proof; a photo's floor is unknown | 6 | 4 | 5 | 120 | scene_script fact check, 3 attempts (Patch D) then single-text fallback, `narration_mode` in the job; a person listens to the first real jobs | test_scene_script 75 PASS (sandbox, fake Claude/TTS); REAL TEST 2026-10-22 job 4374ebc4: script rejected twice on word counts (15-16 vs 14), single-text fallback used; Patch D (soft margin, 3 attempts) built, NOT deployed; deployed b5d2cdc | Deployed; real test FAILED on word limit, fix not deployed | ACT |
| F69 | P5 | Rework state, clip length or cost differ between the three rework paths (twin scene entries and a stale 'reject' in the library; rework clip 4-8 s vs 6-20 s; cost recorded in 4 copies) | Library shows a rejected scene that was already redone; a rework clip shorter than its voiceover; rework cost not matching what was spent | Three parallel copies of the same steps in api_server.py, fixed one at a time; status matched by scene_id while entries only have an index | 5 | 4 | 5 | 100 | ONE engine scene_rework.redo_scenes behind all rework entry points (api_server `_run_redo`), one clip-length rule, one cost record; rework budget and lock unchanged | test_scene_rework 65 PASS + 14 other suites (sandbox, fakes); api_server.py not importable in the sandbox (source/name check only); NOT run on a real rework; deployed 2041128 2026-10-22 (restart, no Traceback) | Deployed, not verified on a real rework | ACT |

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
- **Phase 1 (2nd half of October)**: ~30 real listings from >=6 agencies through the real channel, ~10 hard cases; internal only, not delivered to agencies; reviewers Michele + Relinx's contact (to confirm). Capture real O values for the FMEA.
- **Phase B (last week of October, one agreed session running the whole written protocol, plus one reserve date to re-run failures; dates agreed with the Relinx contact)**: ~20 requests sent by Relinx from the CRM with a separate test callback; real providers; hard spend cap decided in advance (expected EUR 350-400). Exit: >=95% of requests reach `completed`/`in_review` without a developer touching the server; 0 lost; 0 double-charged; every failure visible to the operator within 5 min; 0 duplicate jobs; every video shown correctly in Relinx's player (R14); acceptance rubric >= 90%.
- **GIAL pilot (end Oct/early Nov to end Nov)**: 5-10 videos, one review step kept by Michele, agency gives qualitative feedback by voice (Michele relays); weekly KPI review.
- **Checkpoint (early December)**: G5.
- **Stop rule** (any phase): a job above 2x its estimate, or the same failure 3 times -> pause new requests and decide.
**Leading indicators to watch daily**: needs-human count, draft/queued age, QC flag rate, rework rate, cost per job, failures per provider, webhook failures, notifications sent vs expected.

## 7. Open inputs needed to finish (ask list)
1. RESOLVED 2026-10-09 (grep on server): `GET /v1/videos/{id}`, `GET /v1/videos` and `GET /v1/videos/{id}/download` exist, and `video_url` uses https://api.propertyvideostudioai.com. Still open: contract tests (F34), and how a browser/player authenticates and how long the URL lives (F35, question Q-B to Relinx).
2. Relinx: how do they display the video (stream our URL, download and re-host, player/codec limits), URL lifetime they need, their webhook retry/timeouts, and what they consider "satisfactory".
3. Michele/Relinx: numeric targets: turnaround, cost ceiling per video, acceptable failure rate, volume per day.
4. Michele: review S and O ratings (section 4) and the acceptance rubric (voice, framing, accuracy, logo).
5. Who runs which tests on our side; who is the named contact at Relinx for Phase B.


## 8. Governance: keep the scores and the control plan alive (like status.md / backlog.md)
**Rule (requested 2026-10-09):** the FMEA, the test results and the control plan are updated on the same cadence as status.md and backlog.md, never "later".
- **Triggers for an update**: any code change in a risk area; every bug, incident or near miss; every test round; every Relinx/agency feedback item; every gate review. Update the linked FMEA rows (Status, and O/D re-rated with evidence), the test statuses, and the control-plan lines in the same commit that records the change.
- **Cadence**: quick pass at every deploy; full review at each gate (G1-G5) and weekly during Phase 1, Phase B and the pilot.
- **Scores to watch** (computed, not typed): total RPN; number of `ACT` rows still open; open rows with S>=9; tests by status per level (VERIFIED / Verified (fn) / TO-DO / KNOWN GAP / FAILED); requirement coverage (requirements with at least one VERIFIED test); first-pass release rate and Critical findings per 100 videos (from QUALITY_CRITERIA.md). Each review appends a dated line to the scoreboard below.
- **Implementation (to build, backlog 63)**: move FMEA rows and the test catalogue from the generator script into data files (CSV), generate this markdown and the scoreboard from them with one script, so there is a single source of truth; add the update rule to the project's standing instructions.
- **Rows are never deleted**: close with date and evidence.
**Scoreboard** (manual until the script exists)
| Date | Rows | ACT open | Total RPN | Tests VERIFIED / total | Note |
|---|---|---|---|---|---|
| 2026-10-09 | 53 | 36 | 7066 | see catalogue: 4 live + stages 1-4b function tests | baseline; ratings are proposals, not yet reviewed by Michele/Relinx |

## 9. Decision log
| Date | Decision | Where it lands |
|---|---|---|
| 2026-10-09 | Reviewers: internal phase with Relinx = Michele + Relinx's contact (Michele); pilot = Michele + the agency (GIAL) | QUALITY_CRITERIA.md section 7, F53, Q-F8 |
| 2026-10-09 | Agency feedback: qualitative, by voice, for the ~10 pilot videos; Michele reports to Claude; no feedback endpoint now | QUALITY_CRITERIA.md section 8, F38 |
| 2026-10-09 | Languages: language-general design, only Italian live; a language is supported after golden set + native reviewer | QUALITY_CRITERIA.md section 4, F52, backlog 62 |
| 2026-10-09 | Video marking: text-only "Generated with AI", light grey, NO shadow (revised 2026-10-09), same text style and position as today's watermark, ALWAYS in English (not localized, corrected 2026-10-09); no Property Video Studio logo (white label); agency logo comes through the API and stays separate and optional | QUALITY_CRITERIA.md Q30/Q31, F51, backlog 61 |
| 2026-10-09 | Relinx communication: short open-points list (webhook signing, video_url lifetime, agency logo field, privacy/DPA, test dates); quality spec sent for information; photos assumed high-res originals with reliable order/categories; Relinx contact is the test referent | RELINX_QUESTIONS.md, QUALITY_SPEC_FOR_RELINX.md, DPA_DRAFT.md |
| 2026-10-09 | FMEA/test scores and control plan updated regularly like status/backlog | section 8, backlog 63 |
| 2026-10-09 | Automating light-bug handling: evaluate after the pilot with real finding frequencies; auto-fix only deterministic, reversible, low-cost, check-verified defects, never content/facts/deploy/jobs data | backlog 64 |

## Appendix T -- test catalogue (system-level steps, kept from the first version; IDs are referenced above)
Status words as in the first version of this plan. New required tests derived from the FMEA that are not in this catalogue yet: partner status endpoint contract (F34), partner video fetch with partner auth and in Relinx's real player (F35), expired photo URL (F03), webhook retry/replay/signature (F32/F33), Relinx-player playback (F37), balance-exhausted mid-batch (F14), concurrent jobs (F22), disk-low behaviour (F21), spend cap (F47), fake-flag-in-production guard (F46), narration fact check (F07), uptime/auto-restart (F41).

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






Scores for F54-F59 added 2026-10-12 are proposals until reviewed by Michele. Tests still not run live: F54 live re-check; F56 repeatability test.

Update 2026-10-12 (3B): F02 (fewer than 6 usable photos) now has a stricter, earlier control (acceptance rule before narration); its test status stays 'not run live' until the Phase 1 listings have been run. F60 added (proposal scores).

Update 2026-10-12 (evening): F56 mitigation built (vision classification of every photo in the URL workflow, 22 unit tests PASS); the row stays Open/ACT until a repeatability run on real listings shows stable categories. Test status: unit tests PASS, real-listing repeatability not run.

Update 2026-10-12 (evening, later): F56 evidence: on 9 photos labelled by Michele page-read categories 3/9, vision v1 6/9, v2 7/9. Row stays Open/ACT: sample too small, repeatability not run.

Update 2026-10-12 (night): F56 mitigation changed from whole-listing vision (C) to A+ (vision only for exterior/outdoor candidates, URL and Relinx). Evidence: A/B/C single runs on 5 listings, C lost facade/balcony on 2 listings. Test status: test_vision_classify 30 PASS (unit), live review on the 5 listings and repeatability NOT run. Row stays ACT.

Update 2026-10-15: F62 added (proposal scores) for annunci.getrix.it support; unit tests G1-G7 PASS, live run on the real page not done.

Update 2026-10-15 (afternoon): F62 re-scored from live evidence (0 photos), F63 and F64 added (proposal scores S/O/D to be reviewed by Michele). Tests added: test_narration_durations.py (13 PASS, sandbox), test_prompt_rules.py (5 PASS, sandbox). No real generation run since these changes.
Update 2026-10-15 (evening): F65 added (narration/picture sync for Luma), proposal scores S3/O4/D4 to be reviewed by Michele. Test added: test_narration_sync.py (22 PASS, sandbox, pydub stand-in for the audio part). Not run on a real generation.
Update 2026-10-15 (late night): F67 added (silent fal fallback, scores S6/O6/D7 = proposal for Michele to review; the real cost was seen: USD 20 invoice). Tests added: test_clip_provenance.py (28 PASS), test_fake_video_cascade V5-V8, test_prompt_rules R6-R7 (sandbox only). Backlog 74-78. Not deployed, not run live.
Update 2026-10-15 (night): F66 added (URL/Relinx narration on the shared code), proposal scores S3/O4/D4 to be reviewed by Michele. Tests updated/added in test_standard_3b.py and test_package1.py (sandbox only). A real URL job with the new code is still to be run; it is the pass criterion for F65 and F66.
Update 2026-10-22: F67 deployed and partly verified live (real rework on direct Luma); F68 added (per-scene narration claims), proposal scores S6/O4/D5 for Michele to review. Test added: test_scene_script.py (74 PASS, sandbox). Not run with a real Claude script or on a real job: the pass criterion for F68 (and still for F65/F66).

Update 2026-10-22 (late morning): F68 deployed (b5d2cdc, server restarted, no error in the log), still NOT verified on a real job. F69 added (three rework copies drifted: stale status, clip length, cost), proposal scores S5/O4/D5 for Michele to review; Patch C built, test_scene_rework.py 65 PASS (sandbox, fakes), NOT deployed, NOT run on a real rework. Scoreboard in section 8 not recomputed (manual, last 2026-10-09).

Update 2026-10-22 (midday): F69 deployed (2041128), still NOT verified on a real rework. F68 real test on job 4374ebc4 FAILED to use the per-scene script (word counts 15-16 vs limit 14, twice, no fact error) -> single-text fallback worked as designed (invariant: no job lost). Patch D built (soft margin 2, 3 attempts), test_scene_script 75 PASS, NOT deployed. Scoreboard in section 8 not recomputed.

Update 2026-10-22 (11:10): Patch D deployed (5443fa0); second real test a7e7ef2b still fell back to single_text (spoken split gave 5 sentences, not 6): F68 real test still FAILED, fallback worked (no job lost). Patch E built (stop added, sentence named, sentences logged), test_scene_script 78 PASS, NOT deployed.

Update 2026-10-22 (11:20): Patch E deployed (befc2ae); third real test, draft 32245700: F68 first real PASS on the main criterion (`narration_mode == per_scene`, 6 sentences, no fallback). Sync not yet clean (sentence 2 spills 2.21 s; tighten pass invisible in the log). Patch F (log only) built, NOT deployed. F68 stays open until a listening check and a clean sync.

Update 2026-10-22 (11:30): Patch F deployed (20ca01d); fourth real test c75f022c per_scene; tighten rewrite rejected by the fact check (lost 'in vendita'): fact check worked as designed (invariant: no false claim spoken). Patch G (tighten prompt keeps mandatory words), test_scene_script 79 PASS, NOT deployed. F68 still open.

Update 2026-10-22 (11:40): Patch G deployed (21572d8); fifth real test 6e3d0d40 per_scene; tighten rewrite rejected only because an unflagged sentence was shortened (fact check not involved). Patch H (allow shortening) was built in a sandbox, NEVER deployed and is now WITHDRAWN (superseded by the sentence-driven timeline, backlog 82; production code stays at 21572d8 for scene_script). New observation for F68: text/image misalignment by one scene when a sentence spills > ~2.5 s (kitchen text over bedroom clip): to be handled in the requirements review.

Update 2026-10-23: new row F70 (voice/picture sync drift): hypothesis that the old 5 s grid ignores the 0.5 s cross-fade (voice late up to 2.5 s at scene 6). Calculation covered by test_scene_timing 36 PASS (sandbox, stub audio); NOT run on a real finished video, status: not run. Patch I is calculation only; wiring is Patch J.

Update 2026-10-23 (Patch J): F70 (voice/picture sync) now has a calculation (scene_timing.plan_from_anchors, cross-fade aware) and a word-timing method; sandbox test_anchor_timeline 73 PASS (stub audio, real Whisper output as fixture). Server-side checks still NOT RUN: (1) moviepy MultiplySpeed(final_duration) on a synthetic clip; (2) faster-whisper inside the job flow; (3) one real job with PVS_ANCHORED_TIMELINE=1 watched and listened to (rooms on screen when named, no flash at the cuts, speeds 0.8-1.25). New risk row F71: speech recogniser missing/failing or text not matching the audio -> automatic fallback to the previous modes (covered by E9, E11, E12, E17; S2 O2 D1 accepted until the real test).
Update 2026-10-23 (Patch J server results + Patch K): moviepy MultiplySpeed check on the server = PASS (exact durations, output file 6.250 s). Faster-whisper inside the job flow and the real watched/listened job: still NOT RUN (first real draft 312b283b fell back before the recogniser step because the text was rejected; fallback itself worked, 0 Luma cost). F71 gets a second cause: text rejected twice (length/adjective/anchor) or timing impossible -> fallback (covered by E7, E8, E10; now E7b, E10b, C14b, C14c, C18 for Patch K). test_anchor_timeline 79 PASS in sandbox. Test isolation finding (server, 2026-10-23 14:43): with PVS_ANCHORED_TIMELINE=1 in the server .env, test_scene_script failed (KeyError script_fallback_reason) because it did not clear the flag; first fix was in the wrong place (flag removed BEFORE importing listing_scraper, whose load_dotenv() put it back from the .env) and failed again on the server; fixed by removing the flag AFTER the import and reproduced/verified in the sandbox with a real .env containing PVS_ANCHORED_TIMELINE=1 (lesson: a sandbox without .env hides this class of bug); the failed apply was rolled back by the block, nothing was committed.
Update 2026-10-23 (afternoon/evening, Patch L deployed 128ac4d, Patch M built): two drafts fell back to per_scene (first room at 11.5 s) - invariant "no job lost" held (drafts exist, 0 Luma cost); faster-whisper DID run inside the job flow (first evidence for F71). New row F72 (proposal S4 O5 D2, RPN 40, not ACT): draft creation lasts minutes inside one HTTP request -> browser "Load failed" while the server finishes (operator misinformed; risk of duplicate drafts and paying Claude/TTS twice - it happened, then happened AGAIN after Patch L because the listing read + vision + acceptance (~3 min) were still in the request: lesson = measure the part you leave synchronous). Control: Patch M = preparation tickets in memory, whole pipeline in the background, job created only at the end (a refused listing leaves no job/folder). L1 text-level timing check: first real evidence = it rejected two texts without paying voice (9.6 s / 9.2 s tail after the last room). Tests (sandbox): test_url_draft_background 32 PASS (state machine, wiring order, undefined names, page script node --check), test_anchor_timeline 89 PASS (G1-G10 incl. the real rejected text), test_standard_3b / test_vision_classify updated to look at the worker. NOT run: the real fastapi endpoint after Patch M, a real draft after Patch M, restart during preparation. Scoreboard in section 8 not recomputed.
Update 2026-10-23 (evening, Patch M deployed 0fa06b8, Patch N built): F72 evidence - Patch M tickets: PASS on the first real draft (6cb22349: 1 job, 0 jobs for the 2 rejected texts, no 'Load failed' reported). F70 still FAIL: anchored not achieved (real voice rejected a text the estimate had passed). Patch N (stricter estimate + measured retries not starved) tested in sandbox only (test_anchor_timeline H1-H8, 97/97); real-listing result NOT RUN. Lesson: a retry budget shared between a free check and a paid measurement lets the free check starve the paid one - give each its own counter.
Update 2026-10-23 (night, Patch N deployed, Patch O built): F70 still FAIL on the real draft d0492ebb (anchored not achieved with 5 named rooms; 7 Claude calls, 2 voiced). Invariants held: no job lost (draft exists), no extra jobs, 0 Luma cost. Patch O (max 3 highlights) tested in sandbox only (test_anchor_timeline C1/E3/I1-I5, 102/102); real-listing result NOT RUN.
Update 2026-10-24 (Patch Q built): F70 approach changed to 3 voice blocks fitted to the 5 s clips. Sandbox: test_block_narration 33/33, test_anchor_timeline 102/102. Real audio (pydub/atempo) test and real-listing result: NOT RUN. Rollback commit 86e51ff.
Update 2026-10-24 (evening): Patch Q deployed 5c085eb; draft 41ae5a44 = first non-fallback draft, F70 sync still FAIL by Michele's review (topics out of order inside blocks). Incident: test_batch_redo.py (real job, about USD 2.8) was run by mistake inside a test loop: control: live-API tests (test_batch_redo, test_luma) are excluded from loops. Patch R tested in sandbox only (test_block_narration 49/49); real-listing result NOT RUN.

Update 2026-10-25 (afternoon): Patch R2 deployed 14a6e4f (19 safe suites PASS on the server). First real draft dd4d2b79: R2 sync NOT demonstrated - fallback to per_scene after 6 attempts (false room keyword, closing block slightly too long, feedback lost after a non-JSON reply). F70 (sync) stays FAIL/not demonstrated. Patch R3 in sandbox only (59/59). Real-listing behaviour of R2/R3 = NOT RUN until a draft with narration_mode anchored/blocks exists.

Update 2026-10-25 (evening): Patch R3 deployed 01475ca (19 safe suites PASS on the server, test_block_narration 59/59). Draft 633d3f36: block narration accepted, word check 3/3 rooms inside their window (evidence: job_meta timeline.word_check). F70 (sync as seen in the assembled video) remains NOT RUN until a video is generated and watched by Michele.

Update 2026-10-25 (night): Michele reviewed the zero-cost sync preview of draft 633d3f36: sync OK by eye (F70 sync: PASS on one draft by human review; automatic audio-vs-cut check not built yet; battery of drafts not run). Test plan levels A-F approved (see backlog item 83 update). Patch R4 in sandbox only (test_block_narration 62/62, test_sync_preview 9/9); real effect of the longer last block NOT RUN.

Update 2026-10-25 (night): clip QC with Claude built in the sandbox (test_clip_qc.py 24/24, fixtures from the real defects of job 41ae5a44). Real behaviour NOT RUN: no real Claude answer yet; false-positive/false-negative rate on real clips NOT measured; QC cost accounting NOT done. Planned: qc_validate.py on 41ae5a44, bd3f0f77, 83ca6568 (read-only).

- 2026-10-25 R5: new test_block_robustness.py (R1-R5, simulation of plausible texts, slow ~90 s) PASS in sandbox; test_block_narration E1-E8 PASS (70/70). Evidence level: simulation + replay of real logged sentence lengths. Real-draft test: not run. FMEA row "block narration falls back to per_scene (last block too long)": occurrence confirmed twice in real drafts (R2, d6ca1445); control = joint planner + last-sentence budget; S/O/D proposal to be reviewed with Michele after the real draft.
- Level B URL battery (supplied by Michele 2026-10-25, immobiliare.it/annunci/): 133345168, 130120864, 129258124, 132923242, 132055134, 132223370, 133381578, 132195874, 129644228, 133605094, 127250417, 128111304, 131335508, 132273018, 133826132. Not run yet.

- 2026-10-25 Patch X: test_clip_qc E1-E10 PASS (34/34, unit). Cost rows: QC cost now real usage in the job total; estimate constant is an ESTIMATE. Real validation of prompt v2 / models on labelled clips: not run. QC FMEA row "QC misses a real defect": occurrence CONFIRMED (41ae5a44 s3 missed by QC v1, 2026-10-25); control = prompt v2 + model comparison + labelled set; S/O/D proposal to be reviewed.

## 2026-10-25 - Patch Y tests (units)
- test_tts_sanitize U1-U10: PASS in the sandbox (19/19); not yet run on the server. Real-draft check (no pause after the unit, "metri quadri" in the opening): not run.

- 2026-10-25 (late) CORRECTION: fixtures A6/B1 of test_clip_qc were described as "real defects of 41ae5a44"; scene 3 is not a defect (mirror reflection). They are synthetic unit fixtures only, renamed. Real QC measurement on corrected labels: Haiku 4.5 1 false reject + 2 false flags of 8 clean clips; Sonnet 5.5 0 false rejects + 3 false flags; both found the 2 real defects (flag/reject); Haiku 5.5 invalid answers (token limit). Z1/Z2 added (PASS in sandbox). Re-run after Patch Z: not run.

- 2026-10-25 (late) Patch AA: test_clip_qc E11 PASS in the sandbox (37/37); real-job behaviour of the Sonnet QC: not run.

- 2026-10-26 Patch AB: test_camera_candidates C1-C8 PASS (8/8) in the sandbox; end-to-end camera_test_clips --go with fake providers OK; real Luma clips / real review: not run. FMEA note: narration grammar error "garantono" in a delivered script = new gap (no language check), proposal in backlog; severity for a customer-facing video: high, detection today: none (Michele's ear).

- 2026-10-26 Patch AC: test_italian_check 19/19, test_block_narration F0-F4 PASS (75/75), test_scene_script O24-O27 PASS (83/83) in the sandbox. NOT RUN: the checker on real Italian narrations (false-positive rate unknown), and a real draft after deploy. FMEA: new row "grammar/spelling error in a delivered script" - detection was none (Michele's ear), now an automatic check with fail-open behaviour (a failed check does not block); residual risk: errors the model does not recognise, paths not covered (see status.md).


#### 2026-10-26 (sera) - Patch AD: Italian check now finds unknown words with a dictionary (replaces the detection of Patch AC)
- MEASURED on the server with real texts (blocks 114-118): the whole-text proofreader of Patch AC did NOT find "garantono" in draft 7ff8ec4b, with Haiku 4.5 (also proposed a wrong "contatta"->"contattare" on c4cbba23) and with Sonnet 5.5 (no error reported on any of 10 texts). Cause 1: the parser rejected a reply that showed two JSON blocks (checked=False on 7ff8ec4b). Cause 2 (the real one): asking a model to find a typo in a fluent text does not work.
- Fix: pyspellchecker (Italian, 120k words, new line in requirements.txt) lists the words it does not know (7ff8ec4b: abitativa, contatta, dotazioni, garantono, immobiliare, saba, terrazzato; 4-8 per text, mostly noise); words of the listing / address / agency name and 1-2 letter words are dropped; Claude (same Haiku call, max_tokens 600) judges ONLY those named words. No unknown word = no Claude call. After a fix the re-check asks only about words not already judged fine. Parser now takes the LAST {"errors": [...]} object. Without the package installed it falls back to the old whole-text proofreading (logged).
- Limits: a typo that is itself a real word, and grammar (agreement, missing verb), are not found. Example NOT solved: the closing of 7ff8ec4b "Un giardino terrazzato di 60 metri quadri, contatta Gallo Immobiliare" is a sentence fragment; no spelling check sees it.
- Tests (sandbox): test_italian_check 30/30 (D1-D11 new), all narration suites also PASS with a fake dictionary that flags every word (worst case). NOT RUN: the new detection on real texts (validator block), a real draft after deploy.
#### 2026-10-26 (sera, block 128 on the server): the prompt rule of Patch AE did NOT stop "contatta" -> "contatti" on c4cbba23 (a correct word changed by the model). Michele: "contatta" is fine. Patch AF: (1) deterministic guard in italian_check._inflection_only: a correction that only swaps the final vowel or adds / removes a 2-3 letter ending is ignored (choice of form, not a typo); real typos and a missing accent still corrected (tests D13/D14); (2) blocks mode: the SAVED narration_text now shows the closing as its own sentence ("..., contatta X." -> "... . Contatta X."), as the voice already received it since Patch R4 - only the returned string changes, timeline blocks / audio / sync unchanged (tests C4, C20). NOT changed: the single-text and per-scene-script paths still keep the comma in the closing and send no extra pause (changing the sentence count there would move the sentence-to-scene sync; to decide with Michele). NOT re-measured on the server yet.

#### 2026-10-26 (sera) - Patch AG: ONE camera-movement table (camera_plan.py) + the approved camera movements become the defaults
- Michele chose full consolidation (option A). ROLLBACK POINT: commit 6485919 (deployed, restarted 18:35). Touches the main generation path (movement chosen for every scene), so verified with a real flow test (photo -> analysis -> scene -> Luma prompt, fake providers, zero cost) and not only unit tests.
- FOUND: the table existed in FOUR copies, already drifted: video_generation.SPACE_DEFAULT_MOVEMENT, vision_analysis._MOVEMENT_MAP (the one every URL draft really used: it overrides the scraper's after the photo analysis), listing_scraper._CATEGORY_TO_POV_MOVEMENT (outdoor = walk_toward) and the mirror in ui.html. Drift: "medium" was walk_in_gentle in video_generation/ui.html but walk_in_explore in vision_analysis. Also the scraper's fallback "gentle_arc" is not a real movement (the July 10 bug again).
- NOW: camera_plan.py holds SPACE_DEFAULT_MOVEMENT, ROOM_MOVEMENT, CATEGORY_MOVEMENT and movement_for(space, depth, room). The four users read it (same object, not a copy); ui.html keeps a mirror checked by test_camera_plan.py (T4); every movement named is checked against the UI list (T6) and the Luma prompt tokens (T7); a unit test lists the exact differences from before (D1-D4) and a source scan fails if a literal space->movement table reappears (N1).
- BEHAVIOUR CHANGES (the only ones): facade (room building_exterior, scraper category exterior, UI space "outdoor") -> approach_facade; garden / pool / other exterior / balcony / terrace (scraper category outdoor, UI space "elevated") -> outward_view; medium interiors -> walk_in_explore everywhere (the value URL jobs already got; the manual UI used walk_in_gentle - Michele to say if he wants gentle back); scraper fallback gentle_arc -> walk_in_explore. UI: two new options with Italian labels; reveal_pullback stays selectable but is labelled "sconsigliato" (it is a REVERSE dolly and invented a street in job 83ca6568).
- Drafts already created keep the movements they were created with (stored per scene at draft time): b13657de etc. need a NEW draft to get the new movements.
- NOT DONE: mirror recognition (reflective_surface) in the photo analysis and the large-mirror movement (separate package); the Florence fallback (no room known) gives "approach_facade" for any outdoor photo; vision_analysis._SPACE_CAMERA is a different, legacy concept (camera hints) and was left alone; eco-tier tables (_KLING/_VEO/depth_renderer) have no entry for the two new movements and fall back safely (.get with walk_in_explore / safe default).
- Tests (sandbox): test_camera_plan 20/20 (new), test_room_recognition 31/31 (4 expected values updated), test_camera_candidates 8/8 (C4 updated); all other suites unchanged and PASS, with and without the dictionary. NOT RUN: on the server, a new draft + one real generation (needs Michele's OK, about USD 7.2 + Sonnet QC about EUR 0.06).

### 2026-10-26 Patch AH
- Tests: test_preview_proxy (P1-P11 ffmpeg, W1-W7 wiring) 18/18 PASS sandbox; test_clip_qc A10-A16 PASS (44/44). Server smoke test (Range request, light < full, download = original size) NOT RUN.
- FMEA proposals (not reviewed by Michele): QC false reject of good clip (S3, O3, D2) mitigated by possible_person->flag; preview cache failure (S2, O2, D2) fail-open to original; download must stay original (S8, O1, D2) covered by W2/W5.
