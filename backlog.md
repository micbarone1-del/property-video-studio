# Property Video Studio — Backlog

_Last updated: July 21, 2026 — added items 36-41 (portrait/landscape format normalization gap closed, Luma camera-movement quality issue, architecture consolidation project with items 1-4 done, library reorganization by client/property/job, remaining dead-code cleanup, maintenance credit-check retry). Numbering gap between 16 and 30 is a known pre-existing inconsistency from an earlier renumbering, not yet cleaned up._

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
1. Test the same engine against a real idealista.it listing, then a real casa.it listing (see item 15 — still confirmed broken, not started).
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

## 7. Client logo superimposition — LOW PRIORITY

**Scope — fully defined, ready to build:**
- Position: bottom-right corner. Duration: full video. Opacity: solid.
- Storage: one logo per agency client via `clients/{client_slug}/logo.png` + a `clients.json` manifest. MVP: manual file drop + manual JSON edit, no upload UI needed yet.
- Job creation gets a Client dropdown populated from `clients.json`; job stores `client_slug` so reworks reuse the same logo.
- Format validation: multi-format accepted, but any upload without an alpha channel is rejected with a clear error.
- Compositing: single `CompositeVideoClip` addition in `video_assembly.py`'s `assemble_property_video()`.
- Confirmed distinct from `watermark_removal.py` (removes source-site watermarks; this adds the agency's own logo).
- **Note July 21, 2026:** should be scoped together with item 39 (client/property data model work), since both need a real "client" concept beyond the existing cost-reporting `agency_id`.

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

**Priority:** not placed — framed as a future direction for full automation, not immediate. This remains the real, structural answer to hallucination detection — every prompt-level mitigation (including the July 21 human-shadow fix) is probabilistic harm reduction, not detection.

---

## 12. Generation kill-switch during development/deployment — ✅ COMPLETED July 11, 2026

**Built:** persistent pause flag, admin endpoints, visible UI banner. See status.md for full detail.

---

## 13. Real-time queue/progress visibility

**Problem, confirmed real:** progress display can look static/stuck with no way to tell if a job is genuinely progressing, hung, or waiting.

**Partial progress only (July 13, 2026):** rework-specific progress messages say "Rework: ..." so a rework in progress is at least distinguishable by message content. The underlying ask — genuine stuck-vs-progressing visibility, elapsed time, granular per-scene/stage state for ANY job — is still unaddressed.

---

## 15. idealista.it / casa.it photo extraction doesn't work yet

**Problem, confirmed via real testing:** both sites return 0 photos consistently (immobiliare.it works reliably).

**Likely real fix, not started:** find each site's internal image-loading API/endpoint rather than parsing the rendered page.

---

## 30. Depth rendering R&D — REVIVED (potential structural elimination of hallucination)

**Concept:** depth-based reprojection cannot hallucinate — structurally incapable of inventing content not in the source photo. Every prompt-based mitigation (including the July 21 human-shadow fix) is probabilistic harm reduction; depth rendering would be immunity.

**Not started.** Scope to be defined. Would sit alongside the existing model tiers as a hallucination-free option.

---

## 31. Claude API (agent) costs and credits not tracked anywhere

**Confirmed gap.** The URL-scraping workflow makes real, billable Claude API calls not reflected in the cost estimate, cost tracker, or maintenance credit monitor. Only fal.ai and ElevenLabs are tracked at the per-job level (the maintenance credit *monitor* does now check Claude API connectivity, per status.md — this item is about per-job cost attribution specifically, a separate thing).

---

## 32. Old-job cleanup false negative — 2 jobs stuck past retention

**Confirmed real** (maintenance alert): two jobs past the 7-day retention cutoff weren't cleaned up.

**Investigated, not yet confirmed/fixed.** Working hypothesis: `_load_jobs_from_disk()` may reset the mtime the retention check relies on, on every server restart. Not yet verified against that function's actual body.

---

## 33. Cost reporting UI — confirm + edit for new client/revenue entries

**Requested.** Add a confirmation popup when adding a new client or revenue entry in the cost reporting UI, and allow editing after. Not scoped further yet.

---

## 34. Safeguard against destructive commands — ✅ ADDRESSED July 17, 2026

**Built:** absolute behavioral rule (Claude's persistent memory + should be in Project custom instructions), independent nightly backup (`backup_jobs.sh`, outside the repo, 30-day retention, immutable timestamped snapshots).

**Still open — a related but separate concern:** doesn't cover accidental *manual* deletion via the UI (scene-removal button has no confirmation prompt), or make the app's own automated 7-day cleanup non-destructive (still a hard delete, not move-to-recovery-folder).

---

## 35. Auto-scraping for 1-minute videos on premium properties

**Requested.** Some premium properties should get a longer (~1 minute) auto-scraped video instead of the standard ~30s format.

**Not scoped yet — open questions:** what defines "premium," does this replace or supplement the standard format, photo-count implications, narration pacing at longer length, cost/pricing implications.

**Dependency:** builds on item 1 — same engine, different target length.

---

## 36. Format detection/normalization gaps in other upload paths — ✅ COMPLETED July 21, 2026

**Was:** the landscape/portrait crop-normalization built for the main manual upload path (`create_job`) didn't cover `add_scene`, `resync_draft`, `redo_scenes_batch`'s new-image handling, or `create_job_from_url` (the URL-scraper).

**Now fixed, all five paths covered.** `add_scene`/`redo_scenes_batch` inherit the job's already-decided format (correct — the job's canvas is already locked in); `resync_draft` re-decides via majority vote each time (correct — still pre-generation); `create_job_from_url` now normalizes right after the scraper downloads and places images, before vision analysis runs. See status.md for full detail.

---

## 37. Luma camera movement — wobbly/exaggerated, and worse specifically in portrait

**Reported July 21, 2026.** Two related but distinct issues:

1. **General:** Luma's POV movement tends to be wobbly, with exaggerated manual-camera-style movement/steps simulating a person walking in, rather than a smooth dolly-in. Not yet investigated or fixed. Needs a look at `_LUMA_MOVEMENT_TOKENS`' actual prompt language and likely a rewrite toward explicit "smooth dolly" phrasing.
2. **Portrait-specific, root cause understood (see status.md):** a 9:16 frame has roughly a third the horizontal field of view of 16:9 for the same shot, so identical movement settings consume proportionally more of the real photographed content before the model has to invent what's beyond the edge — confirmed on a real client photo even at the gentlest available intensity. Luma's prompt system has no numeric degree value to simply reduce (unlike Veo's `_VEO_MOVEMENT_TOKENS`, which does have explicit "maximum X degrees"). Likely direction: add an explicit portrait-specific caution phrase to the prompt when the job's `output_format` is portrait. Needs empirical tuning against real photos — a probabilistic prompt-level mitigation, same caveat as the rest of `_LUMA_RULES`, not a guaranteed fix.

Both deserve a dedicated pass rather than a quick patch — treating as a real, multi-iteration piece of work.

---

## 38. Architecture consolidation — full assessment delivered, items 1-4 done, 5-6 remaining

**Context:** a full architecture assessment (delivered as `architecture_assessment.md`, July 21, 2026) found this codebase has real, recurring duplication along two fault lines — manual vs. URL-scraper workflows, and legacy vs. new rework model — after three separate bugs this week were each caused by exactly this pattern (buffer constant, cost calculation, redo-button routing).

**Done:**
1. `/approve`'s QC-rejection redo path migrated off the legacy `run_rework()` onto the batch redo mechanism.
2. `listing_scraper.py`'s own lead/trail buffer checked against the new WhatsApp-trim-fix values — confirmed already safe, no fix needed.
3. Format-detection/normalization wired into `create_job_from_url()` (see item 36).
4. `run_assembly()` and `run_reassemble_only()` (near-duplicate "assemble the video" implementations) fully consolidated into one function, `run_assembly()` deleted, confirmed via a real end-to-end generation test.

**Not yet done:**
5. **Two confirmed UI-orphaned legacy paths, not yet deleted:** `POST /jobs/{id}/scenes/{scene_id}/redo` (the endpoint specifically — its underlying function `run_redo_scene` is still genuinely needed by `add_scene` and must stay) and `POST /jobs/{id}/rework` (confirmed via direct grep: zero references anywhere in `ui.html`). Both are safe deletion candidates, ready for a future session.
6. **The real, larger project:** `listing_scraper.py`'s narration/scene-duration derivation is a fully separate implementation from `narration.py`'s, sharing no code. Genuinely unifying these is the biggest, most valuable remaining piece — should be scoped as its own dedicated effort, not squeezed in alongside other work.

---

## 39. Library reorganization — by client / property / job, not "main job + reworks"

**Requested July 21, 2026.** The job-history/library UI's old grouping (main job + sibling rework entries) no longer applies now that reworks happen in-place on the same job (see item 38). User wants it reorganized around clients → properties → jobs instead, in line with how cost reporting already thinks about agencies.

**Real context gathered, not yet scoped into a build plan:**
- An `agency_id`/`agencies.json` concept already exists (built for cost reporting — `cost_model.py`), so "client" has a real foundation.
- **No "property" entity exists anywhere in the data model.** A property is currently just an implicit `property_name` string on each job — there's no way to link multiple jobs (e.g. an original video plus a later rework, or the same property re-shot months later) to one property record.
- This is a real data-model addition (a new `properties.json`-style entity, presumably), not a UI-only reorganization. Needs proper scoping: does a job get explicitly assigned to a property at creation time, or inferred/matched somehow? Can a property have multiple clients over time (e.g. re-listed with a different agency)? Should item 7 (client logo) and this share the same client concept?

---

## 40. Retire remaining dead legacy redo/rework code

**Confirmed safe candidates, not yet executed (see item 38, point 5):** `POST /jobs/{id}/scenes/{scene_id}/redo` endpoint (function stays, endpoint doesn't need to) and `POST /jobs/{id}/rework` + its `run_rework()` function, both confirmed to have zero remaining callers in `ui.html`. Low-risk cleanup, ready whenever there's a session to spend on it.

---

## 41. Maintenance credit-check retry logic — low priority

**Context, July 21, 2026:** a maintenance alert reported "Claude API: FAILING" despite a confirmed-healthy account ($18 balance, and the exact same check passed cleanly when re-run moments later). The check (`credit_monitor.py`'s `get_anthropic_status()`) makes a real API call with no retry — a single transient network/API blip at the exact check interval produces a false alert indistinguishable from a real problem.

**Proposed, not built:** retry once before declaring failure. Low priority — this specific instance is confirmed resolved with no code change; only worth doing if false alerts become a recurring nuisance.

---

## NEXT MILESTONE — Concurrency + Operator Dashboard

**COST REPORTING IS DONE (July 12, 2026).** Built, tested, deployed, live in the UI — see status.md for full detail. **Cost model itself was significantly corrected July 21, 2026** (real per-second, resolution-aware Luma/Veo pricing, replacing a flat rate that undercharged Luma by ~4x) — see status.md.

**NEXT: Concurrency + operator dashboard.** Goal: minimise time the operator spends at the PC; they intervene only when needed.

1. **Job queue with configurable concurrency ceiling.** The 5-jobs/hour rate limit in api_server.py is OURS (self-imposed), not a fal.ai limit. Real constraints are fal.ai account concurrency and cost.

2. **Dashboard as an INBOX** — show ONLY what needs the operator: (a) awaiting setup review before any money is spent, (b) QC flagged/rejected, (c) failed. Everything else runs unattended.

3. **Executor profile** (for hiring): junior/VA-level QC reviewer. Visual judgment, Italian, real estate literacy. NOT technical. Per-video review fee, not salary.

**STILL OPEN — MAXIMUM PRIORITY:** QC does not reliably catch hallucinations. Agent-based QC (item 11) is the real answer; every prompt-level mitigation built so far (including the July 21 human-shadow fix) is harm reduction, not detection.

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
- **Architecture consolidation, items 1-4** — July 21, 2026. See item 38.
- **Human shadow/silhouette Luma prompt fix** — July 21, 2026. See item 37 for the remaining, unfixed general camera-movement issue.

## Not backlog items — standing watch items (tracked in status.md, not here)

- Rework edge cases that may surface in specific use cases (no confirmed repro yet).
- Maintenance scheduler tiering behavior — pending log confirmation.
