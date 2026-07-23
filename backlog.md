# Property Video Studio — Backlog

_Last updated: July 22, 2026 — architecture consolidation (item 38) now fully complete, all 6 items; items 31 (Claude API cost), 37 (Luma general wobble), 39 (full client/property/job library reorganization), 40 (dead-code retirement) all completed; item 32 investigated with diagnostic logging added in place of a guessed fix; item 15 explicitly deprioritized. Numbering gap between 16 and 30 is a known pre-existing inconsistency from an earlier renumbering, not yet cleaned up._

Items are ordered by priority. Each entry includes scope, decisions already made, and open questions still needing resolution.

---

## 1. Automated URL-scraping for photo selection — HIGH PRIORITY — IN PROGRESS

**Scope:** Given a property listing URL, automatically scrape photos instead of requiring manual upload.

**Decisions already made:**
- Priority order for photo categories: exterior → living areas → kitchen → bedrooms → bathrooms → outdoor.
- When scraped photos are insufficient for a category, surface the gap explicitly and require manual upload rather than silently degrading quality or skipping the scene.
- Source sites: start with immobiliare.it, idealista.it, casa.it — plus a "request a new site" workflow for anything else (implemented — see status.md).
- Photo categorization: prefer the site's own image captions/labels; AI vision classification (reusing existing `vision_analysis.py`) as fallback for anything unlabeled/ambiguous.
- Narration/captions: yes, auto-generate from the scraped listing description text (built — see status.md and item 6 below on its architectural separation from the manual workflow).

**Concretely remaining:**
1. Test the same engine against a real idealista.it listing, then a real casa.it listing (see item 15 — still confirmed broken, not started, explicitly deprioritized July 22, 2026).
2. Human-review the auto-generated narration/caption text for quality and pacing.
3. Phase 2 automation (currently Phase 1: auto-populates the editor, human presses "Generate Video" manually).

---

## 2. Multi-job dashboard / concurrent job queue

**Scope:** View and manage multiple jobs running at once, rather than one at a time.

**Open questions:**
- Concurrency target hasn't been checked against fal.ai/ElevenLabs rate limits — needs that check before real scoping.

---

## 3. Portrait/vertical format support — ✅ COMPLETED July 21, 2026

**Was:** blocked on confirming which tiers support portrait output natively, two possible approaches undecided.

**Now built and confirmed working end-to-end** (see status.md, "Portrait/landscape format support" section, for the full real-bug chain this was built in response to): exactly two canonical output formats (landscape/portrait), auto-selected by majority vote across a job's photos with a manual override, wired into every image-upload path including the URL-scraper. Real Luma camera-movement quality issue for portrait clips specifically remains — see item 37.

---

## 4. Human characters

**Open questions:**
- None of the current tiers are validated for realistic human characters. Would conceptually need a Kling-style model added as a fifth tier, but this hasn't been scoped beyond that observation.

---

## 5. Virtual furniture staging

**Scope:** Discussed only. No requirements, approach, or constraints defined yet.

---

## 6. Cost report — DEPRIORITIZED

**Scope:**
- Per-job cost report, grouped by job **and** by rework.
- Dedicated login separate from the main job-creation UI.
- Later phase: reconcile computed/estimated costs against actual invoices paid to each platform.

**Open questions:**
- Invoice reconciliation format/source not yet defined.

---

## 7. Client logo superimposition — ✅ COMPLETED July 22, 2026

**Fully built end to end.** `cost_model.py`: `set_agency_logo()`. New `POST /agencies/{id}/logo` endpoint validates the upload has an alpha channel (clear error if not) and saves it under `clients/{agency_id}/logo.png`. `assemble_property_video()` in `video_assembly.py` accepts an optional `logo_path`, composites bottom-right at full video duration, solid opacity, when present — non-fatal on failure (logs and continues without it, never breaks a delivery). `run_reassemble_only()` resolves the logo automatically from the job's existing `agency_id` (item 39) — no separate per-job field needed. UI: a logo-upload control (client select + PNG file input) added to the cost modal's existing agency-management section. Verified with a real transparent-PNG upload test (alpha detection, persistence, file-on-disk all confirmed).

**Not yet done:** no real client logo has actually been uploaded and tested through a real video generation yet — the plumbing is confirmed correct end-to-end at the code level, but the visual result (does it look right, positioned well, right size) hasn't been eyeballed on a real output video.

---

## 8. HLS preview streaming — LOW PRIORITY

**Scope:** Segment the preview video for faster playback start, without touching the downloadable file.

**Decisions already made:**
- Original assembled MP4 stays untouched for `/download`.
- Only `/clip/` preview path changes to serve HLS-packaged segments.
- One rendition is sufficient — range-streaming (already implemented) already partially addresses this.

---

## 9. YouTube auto-upload — LOW PRIORITY

**Scope:** Discussed only. No requirements defined yet.

---

## 10. Agency outreach agent — Italy, pilot phase

**Concept:** a separate agentic tool (genuinely agentic — finds targets, acts, adapts — not a fixed script) that targets Italian real estate agencies for business development: finds a real, live listing from a target agency, runs it through the automated URL-to-video pipeline (item 1) to produce a real pilot video from their own actual property, then sends the agency a personalized outreach email showcasing it.

**Scope not yet defined — open questions:**
- How are target agencies identified — a list you provide, or does the agent search/discover them itself?
- How is each agency's contact email obtained?
- **Compliance:** Italian/EU anti-spam and GDPR rules apply to unsolicited commercial email — needs real legal consideration, likely a human-approval step before any email actually goes out.
- Email content/tone, volume/pacing not decided.

**Dependency:** needs item 1 fully working first.

---

## 11. Agent-based final video QC (replace or complement Florence-2)

**Concept:** use Claude's vision reasoning to judge finished video scenes against quality criteria — holistic plausibility checks rather than Florence-2's object-detection-style approach.

**Real trade-off, not yet resolved:** Florence-2 is self-hosted, near-zero marginal cost. Every Claude-based QC check is a real, ongoing per-scene API cost.

**Priority:** not placed — framed as a future direction for full automation, not immediate. This remains the real, structural answer to hallucination detection — every prompt-level mitigation (including the July 21 human-shadow fix and the July 22 Luma movement rewrite) is probabilistic harm reduction, not detection.

---

## 12. Generation kill-switch during development/deployment — ✅ COMPLETED July 11, 2026

**Built:** persistent pause flag, admin endpoints, visible UI banner. See status.md for full detail.

---

## 13. Real-time queue/progress visibility

**Problem, confirmed real:** progress display can look static/stuck with no way to tell if a job is genuinely progressing, hung, or waiting.

**Partial progress only (July 13, 2026):** rework-specific progress messages say "Rework: ..." so a rework in progress is at least distinguishable by message content. The underlying ask — genuine stuck-vs-progressing visibility, elapsed time, granular per-scene/stage state for ANY job — is still unaddressed.

---

## 15. idealista.it / casa.it photo extraction doesn't work yet — DEPRIORITIZED July 22, 2026

**Problem, confirmed via real testing:** both sites return 0 photos consistently (immobiliare.it works reliably).

**Likely real fix, not started:** find each site's internal image-loading API/endpoint rather than parsing the rendered page. Explicitly deprioritized by the user — lower value than other open items right now.

---

## 30. Depth rendering R&D — REVIVED (potential structural elimination of hallucination)

**Concept:** depth-based reprojection cannot hallucinate — structurally incapable of inventing content not in the source photo. Every prompt-based mitigation (including the July 21 human-shadow fix) is probabilistic harm reduction; depth rendering would be immunity.

**Not started.** Scope to be defined. Would sit alongside the existing model tiers as a hallucination-free option.

---

## 31. Claude API (agent) costs and credits not tracked anywhere — ✅ COMPLETED July 22, 2026

**Was:** the URL-scraping workflow's real, billable Claude API calls (listing extraction, photo ranking, narration, captions) were captured (`claude_usage`) and stored on the job dict, but never actually folded into the displayed cost estimate/actual — invisible in the UI cost panel.

**Now fixed.** `estimate_job_cost()`/`calculate_actual_cost()` in `cost_tracker.py` accept an optional `claude_cost_eur` parameter (0.0 default, manual jobs unaffected), folded into the total and returned as its own `claude_eur` field; `format_cost_display()` shows it as a line when present. `ui.html`'s cost panel already generically renders whatever lines the backend sends, so no frontend change was needed. Verified with a real computation confirming the total increases by exactly the added amount. See status.md for full detail.

---

## 32. Old-job cleanup false negative — investigated, diagnostic logging added (not a guessed fix)

**Original hypothesis disproven, July 22, 2026:** `_load_jobs_from_disk()` was suspected of resaving every job on every server restart, resetting the mtime the 7-day cleanup relies on — checked directly against the function's actual code and confirmed **false**, it's read-only, never calls `_save_job()`. The two originally-reported stuck jobs are gone from disk now (real-world impact was a delay, not a permanent block). Since there's no reproducible evidence left to diagnose with confidence, added targeted diagnostic logging instead of guessing at a fix: the `/diagnostics` cleanup loop now flags (via `log.warning`) any job whose `created_at` is meaningfully older than its file's mtime while that mtime is still within the safe window — the precise stale-mtime signature — without logging anything for ordinary jobs. If this recurs, there will be real evidence to work from.

---

## 33. Cost reporting UI — confirm + edit for new client/revenue entries — ✅ COMPLETED July 22, 2026

**Fully built.** `cost_model.py` adds `update_agency()`/`update_sale()` (partial-update, only touches fields explicitly passed). New `POST /agencies/{id}`/`POST /sales/{id}` endpoints. UI: adding a client or sale now asks for confirmation before submitting; agencies get an edit button (prompt-based, matching the lightweight pattern used for inline client creation); a new individual Sales list was added (previously sales were only shown aggregated per-agency, with no way to see or edit a single entry at all) with edit/delete controls. Verified with real functional tests (agency notes edit + revert, a temporary test sale created/updated/deleted cleanly).

---

## 34. Safeguard against destructive commands — ✅ ADDRESSED July 17, 2026

**Built:** absolute behavioral rule (Claude's persistent memory + should be in Project custom instructions), independent nightly backup (`backup_jobs.sh`, outside the repo, 30-day retention, immutable timestamped snapshots).

**Still open — a related but separate concern:** doesn't cover accidental *manual* deletion via the UI (scene-removal button has no confirmation prompt), or make the app's own automated 7-day cleanup non-destructive (still a hard delete, not move-to-recovery-folder).

---

## 35. Auto-scraping for 1-minute videos on premium properties

**Requested, reaffirmed July 22, 2026.** A dedicated scraping TEMPLATE for premium properties, producing a longer (~1 minute) auto-scraped video instead of the standard ~30s format -- distinct enough from the standard flow to warrant its own template/preset, not just a longer duration on the same one.

**Not scoped yet — open questions:** what defines "premium" (manual flag at job creation? price threshold from the scraped listing? agency-level default?), does this replace or supplement the standard format, photo-count implications (a 1-min video needs meaningfully more scenes/photos than the current ~30s format supports), narration pacing/scene-count-band implications at longer length (the scraper's existing 5-7 scene band -- see item 38 point 6 -- would need a different band for this length), cost/pricing implications (a 1-min video costs meaningfully more in video-generation credits per delivery).

**Dependency:** builds on item 1 — same engine, different target length and template.

---

## 36. Format detection/normalization gaps in other upload paths — ✅ COMPLETED July 21, 2026

**Was:** the landscape/portrait crop-normalization built for the main manual upload path (`create_job`) didn't cover `add_scene`, `resync_draft`, `redo_scenes_batch`'s new-image handling, or `create_job_from_url` (the URL-scraper).

**Now fixed, all five paths covered.** `add_scene`/`redo_scenes_batch` inherit the job's already-decided format (correct — the job's canvas is already locked in); `resync_draft` re-decides via majority vote each time (correct — still pre-generation); `create_job_from_url` now normalizes right after the scraper downloads and places images, before vision analysis runs. See status.md for full detail.

---

## 37. Luma camera movement — wobbly/exaggerated (general fixed July 22; portrait-specific still open)

**Reported July 21, 2026.** Two related but distinct issues:

1. **General wobble/stepping — ✅ FIXED July 22, 2026.** Root-caused by direct comparison against Veo's already-working `_VEO_MOVEMENT_TOKENS`: Luma's prompts lacked explicit "3D dolly" terminology and foreground/background parallax framing, and had no degree limits at all. All 11 `_LUMA_MOVEMENT_TOKENS` entries rewritten with both, plus a direct negative instruction against the reported artifact ("no stepping or bobbing"). Same caveat as every Luma prompt constraint: a well-reasoned, evidence-based probabilistic improvement, not a guarantee — a real generation test to confirm it's actually smoother has not yet been run by the user.
2. **Portrait-specific — still open.** Root cause understood (see status.md): a 9:16 frame has roughly a third the horizontal field of view of 16:9 for the same shot, so identical movement settings consume proportionally more of the real photographed content before the model has to invent what's beyond the edge. Luma's prompt system still has no way to apply a portrait-specific reduction the way Veo's explicit degree values would allow. Not addressed by the July 22 rewrite — needs its own dedicated pass with empirical tuning against real photos.

---

## 38. Architecture consolidation — ✅ ALL 6 ITEMS COMPLETE July 22, 2026

**Context:** a full architecture assessment (delivered as `architecture_assessment.md`, July 21, 2026) found this codebase has real, recurring duplication along two fault lines — manual vs. URL-scraper workflows, and legacy vs. new rework model — after three separate bugs this week were each caused by exactly this pattern (buffer constant, cost calculation, redo-button routing).

1. `/approve`'s QC-rejection redo path migrated off the legacy `run_rework()` onto the batch redo mechanism. ✅
2. `listing_scraper.py`'s own lead/trail buffer checked against the new WhatsApp-trim-fix values — confirmed already safe, no fix needed. ✅
3. Format-detection/normalization wired into `create_job_from_url()` (see item 36). ✅
4. `run_assembly()` and `run_reassemble_only()` (near-duplicate "assemble the video" implementations) fully consolidated into one function, `run_assembly()` deleted, confirmed via a real end-to-end generation test. ✅
5. **Two UI-orphaned legacy paths deleted entirely, July 22, 2026** — `POST /jobs/{id}/scenes/{scene_id}/redo` and `POST /jobs/{id}/rework` (+ `run_rework()`), both confirmed zero remaining callers in `ui.html` before removal. `run_redo_scene()` the function kept (`add_scene()` depends on it). ✅ (see item 40)
6. **`listing_scraper.py`'s narration padding was a genuinely different mechanism, not just a duplicated constant — fixed July 22, 2026.** This was actually causing a real, invisible double-padding bug on every scraped job (silence baked into the audio file, THEN separate blank-video padding added at assembly, which had no way to know the audio was already padded). Now the scraper's buffer constants alias `narration.py`'s shared values, and it stores bare unpadded audio like manual jobs do. The scene-COUNT-derivation logic itself (the 5-7 scene band, correction passes) remains genuinely separate since manual jobs don't need it — a smaller, still-real future unification, not urgent. ✅

**This item is now fully closed** — see status.md's July 21-22 sections for complete detail on all six.

---

## 39. Library reorganization — ✅ FULLY BUILT July 22, 2026 — Client → Property → Job

**Requested July 21, 2026, built July 22, 2026.** Full hierarchy (not just client → job): a property can have multiple independent jobs over time (an original video plus a later, separate reshoot — not just in-place reworks, which don't create a new job entry at all). Client assignable at job creation, still editable after. Space reserved for the future client-logo-overlay feature (item 7).

**Built:**
- **Data model (`cost_model.py`), single shared source of truth with cost reporting, not a separate library-only concept:** new `Property` entity (`properties.json`) — `list_properties()`, `create_property()` (idempotent per name+agency), `get_property()`, `update_property_agency()`. `create_agency()` now reserves a `logo_path` field (item 7, not built yet). New `property_report()` mirroring the existing `agency_report()` pattern — real cost rollup per property, the concrete "cost + library connected" link the user asked for.
- **Job creation (`api_server.py`), both paths:** `create_job()`/`create_job_from_url()` accept an optional `agency_id` and link every job to a Property record, reusing the existing `property_name` field rather than adding a redundant one. `POST /jobs/{id}/commercial` also accepts `property_name` to reassign post-creation. New endpoints: `GET`/`POST /properties`, `GET /reports/properties`. `GET /jobs/` now includes `agency_id`/`property_id` (previously omitted entirely).
- **Frontend (`ui.html`):** both job-creation forms (manual + URL-scrape) gained a "Cliente" dropdown, sharing one fetch function (`populateAgencyDropdowns()`) with the existing cost-modal agency logic — no duplication. `loadLibrary()` fully rewritten as a collapsible Client → Property → Job tree, replacing the stale `_rw`-suffix grouping. Legacy jobs with no `property_id` correctly land in "Nessun cliente → Senza proprietà" rather than erroring or being hidden.

**Real next steps, not yet done:**
- All 11 pre-existing jobs predate this feature and currently show under "Nessun cliente → Senza proprietà" — expected, not a bug, but worth a manual pass to backfill real client/property assignments if that history matters for reporting.
- A real end-to-end click-through by the user (create a job with a client selected, confirm correct grouping in the library) has not yet been performed — recommended before considering this fully closed in practice, not just in code.
- Item 7 (client logo overlay) can now be built on the reserved `logo_path` field with no further data-model work.

---

## 40. Retire remaining dead legacy redo/rework code — ✅ COMPLETED July 22, 2026

**Was item 38 point 5.** `POST /jobs/{id}/scenes/{scene_id}/redo` endpoint (function `run_redo_scene` stays, `add_scene` depends on it) and `POST /jobs/{id}/rework` + `run_rework()` both deleted entirely, confirmed zero remaining callers in `ui.html` before removal, verified via syntax check, AST-level search, live route-registration check, and a real server restart.

---

## 41. Maintenance credit-check retry logic — low priority

**Context, July 21, 2026:** a maintenance alert reported "Claude API: FAILING" despite a confirmed-healthy account ($18 balance, and the exact same check passed cleanly when re-run moments later). The check (`credit_monitor.py`'s `get_anthropic_status()`) makes a real API call with no retry — a single transient network/API blip at the exact check interval produces a false alert indistinguishable from a real problem.

**Proposed, not built:** retry once before declaring failure. Low priority — this specific instance is confirmed resolved with no code change; only worth doing if false alerts become a recurring nuisance.

---

## NEXT MILESTONE — Concurrency + Operator Dashboard

**COST REPORTING IS DONE (July 12, 2026).** Built, tested, deployed, live in the UI — see status.md for full detail. **Cost model itself was significantly corrected July 21, 2026** (real per-second, resolution-aware Luma/Veo pricing, replacing a flat rate that undercharged Luma by ~4x), and now also includes real Claude API cost (July 22, 2026) — see status.md.

**NEXT: Concurrency + operator dashboard.** Goal: minimise time the operator spends at the PC; they intervene only when needed.

1. **Job queue with configurable concurrency ceiling.** The 5-jobs/hour rate limit in api_server.py is OURS (self-imposed), not a fal.ai limit. Real constraints are fal.ai account concurrency and cost.

2. **Dashboard as an INBOX** — show ONLY what needs the operator: (a) awaiting setup review before any money is spent, (b) QC flagged/rejected, (c) failed. Everything else runs unattended.

3. **Executor profile** (for hiring): junior/VA-level QC reviewer. Visual judgment, Italian, real estate literacy. NOT technical. Per-video review fee, not salary.

**STILL OPEN — MAXIMUM PRIORITY:** QC does not reliably catch hallucinations. Agent-based QC (item 11) is the real answer; every prompt-level mitigation built so far is harm reduction, not detection.

## 42. Per-scene audio lead/trail buffer -- ✅ COMPLETED July 23, 2026 (untested end-to-end)

**Reported.** Per-scene voiceover audio started with zero lead-in silence, cutting the first fraction of a second of speech when a video was forwarded through a messaging app -- a genuinely different, previously-unaddressed mechanism from the July 17 continuous-narration WhatsApp-trim fix.

**Fixed:** `SCENE_AUDIO_LEAD_SECS`/`SCENE_AUDIO_TRAIL_SECS` (0.5s each, deliberately smaller than narration.py's 1.0s given a per-scene clip's tighter fixed time budget) in `video_assembly.py`. See status.md for full detail.

**Open question, not yet resolved:** whether 0.5s is actually sufficient for real-world cross-platform re-encoding behavior (WhatsApp/YouTube/email) has not been confirmed by a real test -- only the theoretical AAC-encoder-priming mechanism (much smaller, ~20-25ms) is well understood. See item 43 (audio-only rework) for the cheap way to test this.

---

## 43. Audio-only rework -- ✅ COMPLETED July 23, 2026 (untested end-to-end)

**Requested**, directly motivated by wanting to test item 42's buffer without paying for video regeneration. **Confirmed gap:** the existing redo-batch mechanism always regenerates video for any marked scene -- no way to redo just the audio.

**Built:** `run_redo_audio_only()` in `api_server.py` (mirrors the relevant slice of `run_redo_scenes_batch()` but skips every video-generation step, reuses existing video clips untouched, reassembles via the same shared `run_reassemble_only()`). New `POST /jobs/{id}/scenes/redo-audio-only` endpoint. Cost tracking correctly reflects audio-only (no Luma/Veo charge, only the cheap ElevenLabs one). UI: new "Rigenera solo audio" button next to the main Generate button. See status.md for full detail.

**Not yet done:** a real end-to-end test (mark a scene, click the button, confirm audio changes and video doesn't, confirm cost tracking is correct) has not yet been run.

---

## 44. Investment ledger single-entry management -- ✅ COMPLETED July 23, 2026

**Requested** (track this Claude Pro subscription, €21.96/month, as part of overall investment tracking). **Found:** the investment ledger (`cost_model.py`'s `investment.json`, driving the "Investimento (fisso)" figure) had no way to add a single entry -- only a full-ledger replace, apparently meant for an XLS re-upload workflow that was never built.

**Built:** `add_investment_entry()`/`delete_investment_entry()`, new `GET`/`POST /investment`, `DELETE /investment/{index}` endpoints, a new Investment section in the cost modal. The real Claude Pro entry was added -- its note flags that a new entry is needed each billing cycle to stay current, since there's no automatic recurring-cost mechanism. See status.md for full detail.

## Recently completed (see status.md for full detail)

- **Auto maintenance scheduler** — July 9, 2026.
- **Rework cost tracking + rework progress labeling** — July 13, 2026.
- **Draft scene-count desync** — July 13, 2026.
- **"Aggiungi pause" no-op bug** — July 16, 2026.
- **Legacy rework-endpoint migration (manual "Rifai" button)** — July 16-17, 2026.
- **Narration buffer constant unified across 3 duplicated locations** — July 17, 2026.
- **Real safeguard against destructive commands (backup + absolute rule)** — July 17, 2026.
- **Portrait/landscape format support, full pipeline** — July 21, 2026. See item 3 and status.md.
- **Cost model corrected (real per-second, resolution-aware Luma/Veo pricing)** — July 21, 2026. See status.md.
- **Redo-workflow reliability: button routing unified, stale-poll race condition fixed** — July 21, 2026. See status.md.
- **Architecture consolidation, ALL 6 items** — July 21-22, 2026. See item 38.
- **Human shadow/silhouette Luma prompt fix** — July 21, 2026.
- **Luma general camera-movement wobble fix** — July 22, 2026. See item 37 (portrait-specific issue remains open).
- **Claude API cost folded into displayed cost total** — July 22, 2026. See item 31.
- **Full client/property/job library reorganization** — July 22, 2026. See item 39.
- **Client logo overlay, full end-to-end feature** — July 22, 2026. See item 7.
- **Cost reporting UI confirm+edit for clients/sales** — July 22, 2026. See item 33.
- **Real bug fixed: Client dropdown never actually populated in the browser** (script-order/temporal-dead-zone bug, invisible to all backend-level testing) — July 22, 2026.
- **Per-scene audio lead/trail buffer** — July 23, 2026. See item 42 (real-world sufficiency of 0.5s not yet confirmed).
- **Audio-only rework capability** — July 23, 2026. See item 43 (not yet tested end-to-end).
- **Investment ledger single-entry management, real Claude Pro entry added** — July 23, 2026. See item 44.

## Not backlog items — standing watch items (tracked in status.md, not here)

- Rework edge cases that may surface in specific use cases (no confirmed repro yet).
- Maintenance scheduler tiering behavior — pending log confirmation.
