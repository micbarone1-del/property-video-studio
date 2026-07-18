# Property Video Studio — Backlog

_Last updated: July 16-17, 2026 — moved items 14 and 16 to "Recently completed" (confirmed already fixed on inspection, not from this session's work), added items 32-34, updated item 13 with partial progress. Numbering gap between 16 and 30 is a known pre-existing inconsistency from an earlier renumbering, not yet cleaned up — see status.md if it resurfaces._

Items are ordered by priority. Each entry includes scope, decisions already made, and open questions still needing resolution.

---

## 1. Automated URL-scraping for photo selection — HIGH PRIORITY — IN PROGRESS

**Scope:** Given a property listing URL, automatically scrape photos instead of requiring manual upload.

**Decisions already made:**
- Priority order for photo categories: exterior → living areas → kitchen → bedrooms → bathrooms → outdoor.
- When scraped photos are insufficient for a category, surface the gap explicitly and require manual upload rather than silently degrading quality or skipping the scene.
- Source sites: start with immobiliare.it, idealista.it, casa.it — plus a "request a new site" workflow for anything else (implemented — see status.md).
- Photo categorization: prefer the site's own image captions/labels; AI vision classification (reusing existing `vision_analysis.py`) as fallback for anything unlabeled/ambiguous.
- Narration/captions: yes, auto-generate from the scraped listing description text (not yet built — see below).

**Real progress (see status.md for full detail):** core extraction engine (`listing_scraper.py`) built and confirmed working end-to-end on a real immobiliare.it listing — photos, labels, categories, description, price, address all correct. Had to solve a real IP-blocking problem (immobiliare.it blocks this VPS's direct requests) by routing the fetch through the Claude API instead of a direct HTTP call.

**Concretely remaining:**
1. Test the same engine against a real idealista.it listing, then a real casa.it listing — need one real URL from each to validate (untested so far).
2. Photo-count-per-category question — resolved architecturally: now derived from real narration length (5-7 scenes depending on how much the property needs to say), not a fixed placeholder. See status.md.
3. Human-review the auto-generated narration/caption text for quality and pacing — redesigned twice this session, needs a fresh listen/read.
4. **UI integration — phased, human-in-the-loop first (decided July 9, 2026):** a box on the initial UI where the agent pastes a listing URL. **Phase 1:** automation runs the full scrape → narration → scene-count chain and auto-populates the existing narration/scene boxes; the agent inspects and presses "Generate Video" manually. **Phase 2 (later):** fully automatic, no manual step, once Phase 1 is trusted.
5. Optional/deferred: a ~1s fade-to-black buffer at the start/end of the assembled video (`video_assembly.py`), as extra timing safety margin — only if real usage shows it's needed.

**Note:** flagged by the user as needing a full day of focused work — this session covered the core engine; the integration layer above is the remaining work.

---

## 2. Multi-job dashboard / concurrent job queue

**Scope:** View and manage multiple jobs running at once, rather than one at a time.

**Open questions:**
- Concurrency target hasn't been checked against fal.ai/ElevenLabs rate limits — needs that check before real scoping.

---

## 3. Portrait/vertical format support

**Open questions:**
- Blocked on confirming which of the four video-generation tiers actually support vertical/portrait output natively.
- Two possible implementation approaches were discussed previously; neither has been decided.

---

## 4. Human characters

**Open questions:**
- None of the current four tiers are validated for realistic human characters. Would conceptually need a Kling-style model added as a fifth tier, but this hasn't been scoped beyond that observation.

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
- Confirmed via full repo audit: no existing "client/agency" entity in the job model — this requires a new field/dropdown, not an extension of something existing. `video_editor.py`'s legacy path has its own separate logo-overlay code, not directly reusable.

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
- How are target agencies identified — a list you provide, or does the agent search/discover them itself (e.g. via the same immobiliare.it/idealista.it/casa.it sites, browsing agency listing pages)?
- How is each agency's contact email obtained — scraped from their listing/site, or manually supplied?
- **Compliance:** Italian/EU anti-spam and GDPR rules apply to unsolicited commercial email — this needs real legal consideration before any automated sending, not just a technical build. At minimum, likely needs a human-approval step before any email actually goes out, not fully automatic sending.
- Email content/tone — template with the pilot video embedded/linked, or fully custom-written per agency?
- Volume/pacing — how many outreach emails per day/week is realistic without looking like spam or triggering deliverability problems?

**Dependency:** needs item 1 (automated URL-to-video pipeline) fully working first, since the pilot video is its core hook.

**Priority:** not yet placed — flagged as a distinct future initiative, pilot phase, Italy-only for now.

---

## 11. Agent-based final video QC (replace or complement Florence-2)

**Concept:** use Claude's vision reasoning to judge finished video scenes against quality criteria — holistic plausibility checks (does this look like a real, physically coherent room; did 3D parallax warp anything impossible) rather than Florence-2's object-detection-style approach. Would reuse the same quality language already built for photo selection (no people, key room elements present, natural light, well-framed), giving one consistent quality standard across the whole pipeline instead of two different models with two different vocabularies.

**Practical shape:** extract a few representative frames per generated clip (e.g. first/middle/last), send as images to Claude with a QC prompt — same pattern as the photo-quality-ranking feature already built.

**Real trade-off, not yet resolved:** Florence-2 is self-hosted — near-zero marginal cost per check. Every Claude-based QC check is a real, ongoing per-scene API cost. Given QC potentially runs on every scene of every video, this recurring cost is different in kind from the one-time per-property scraping costs elsewhere in this project.

**Suggested next step, not started:** run Claude-based QC in parallel with existing Florence-2 QC on a handful of real scenes (including ones Florence-2 has flagged before) to compare actual accuracy before deciding replace vs. complement vs. leave as-is.

**Priority:** not placed — explicitly framed as a future direction for full automation, not immediate.

---

## 12. Generation kill-switch during development/deployment — ✅ COMPLETED July 11, 2026

**Built:** persistent pause flag (`generation_pause.json`, survives restarts on purpose — an accidental restart can't silently let jobs sneak through), `/admin/pause-generation` + `/admin/resume-generation` endpoints, `/admin/generation-status` for live state + active job count, wired into all three job-start entry points. Visible UI banner + toggle button next to the Maintenance button — deliberately visible so a paused state reads as intentional, not a broken submit button.

**Does NOT do:** true pause/resume of a job already mid-flight waiting on a Luma/Veo API call — that's not technically possible (no way to freeze and resume a live network call). What it actually does: blocks new submissions, and existing jobs can be gracefully stopped (finishes current scene, halts) via the already-working `/stop` mechanism, then resumed after redeploy since stopped jobs retain partial progress.

---

## 13. Real-time queue/progress visibility

**Problem, confirmed real during this session's testing:** progress display showed something like a static "5s" that "makes no sense" during a generation that was actually stuck for several minutes — no way to tell if a job is genuinely progressing, hung, or waiting on something.

**Scope not yet defined — needs a look at the current progress-polling code first** to know whether this is a display bug (wrong number shown) or a genuine lack of granular status (no visibility into which scene/stage is active, elapsed real time, etc.).

**Partial progress, July 13, 2026 — does not close this item.** Rework-specific progress messages now say "Rework: ..." instead of generic text, so a rework in progress is at least distinguishable from a stuck/broken job by message content. The underlying ask — genuine stuck-vs-progressing visibility, elapsed time, granular per-scene/stage state for ANY job (not just reworks) — is still unaddressed.

---

## 15. idealista.it / casa.it photo extraction doesn't work yet

**Problem, confirmed via real testing July 11, 2026:** both sites return 0 photos consistently (immobiliare.it works reliably). User's hypothesis: idealista's gallery may require a click to expand, which a static page fetch can't do. Unconfirmed for casa.it specifically — may be a different cause.

**What already works correctly:** the "not enough photos, manual upload needed" fallback fires cleanly — this is the safety design working as intended, not a crash.

**Likely real fix, not started:** find each site's internal image-loading API/endpoint rather than parsing the rendered page — a materially different, site-specific investigation, not a quick patch.

---

## 30. Depth rendering R&D — REVIVED (potential structural elimination of hallucination)

**Revived July 12, 2026.** Previously paused after `depth_renderer.py` (numpy + opencv pixel-shift reprojection) hit a quality ceiling, and Luma Ray 2 solved the immediate problem more pragmatically. Bringing it back for a strategic reason: **depth-based reprojection cannot hallucinate.** It can only display pixels that exist in the source photograph — it is structurally incapable of inventing a mirror, warping a wall, or dropping leaves from a ceiling. Every prompt-based mitigation (including today's Luma rules tightening) is probabilistic harm reduction; depth rendering is immunity.

**Motivating evidence:** propertyvideo.ai appears to be shipping this successfully, suggesting the earlier failure was an implementation ceiling rather than a fundamental one.

**Likely gap in the original attempt:** raw pixel-shift reprojection produces occlusion holes and stretching at depth discontinuities. Modern approaches pair a much stronger monocular depth estimator (Depth Anything V2, Marigold) with proper inpainting of the disoccluded regions — a materially different technique, not a retry of the same one.

**Not started.** Scope to be defined. Would sit alongside the existing model tiers as a hallucination-free option, not necessarily replacing them.

---

## 31. Claude API (agent) costs and credits not tracked anywhere

**Confirmed gap July 12, 2026.** The URL-scraping workflow makes real, billable Claude API calls — listing extraction, per-photo quality ranking (vision), narration generation, caption generation — and **none of it appears in the cost estimate shown in the UI, the cost tracker, or the maintenance credit monitor.** Only fal.ai and ElevenLabs are tracked.

**Needed:**
- Add Claude API cost lines to `cost_tracker.py` (per-job estimate + actuals), including the rework case.
- Add Claude API credit/connectivity checks to `maintenance_scheduler.py`, alongside the existing fal.ai and ElevenLabs checks.
- Surface both in the UI cost panel and maintenance panel.

---

## 32. Old-job cleanup false negative — 2 jobs stuck past retention

**Confirmed real, July 16, 2026** (maintenance alert): jobs `161dfaf7_rw5a78` and `3c4bea30` are past the 7-day retention cutoff and should have been cleaned up but weren't, despite the same maintenance run reporting 10 other jobs successfully cleaned.

**Investigated, not yet confirmed/fixed.** Both jobs' `job_meta.json` mtime showed only ~2.3 days old — suspiciously close to the last server restart. Working hypothesis: `_load_jobs_from_disk()` may call `_save_job()` for every job on every startup (including ours from an unrelated import test), which would reset the exact mtime the retention check relies on, letting these two jobs' clocks silently reset on every restart regardless of real age. Not yet verified against `_load_jobs_from_disk()`'s actual body — next step before attempting a fix.

---

## 33. Cost reporting UI — confirm + edit for new client/revenue entries

**Requested July 16, 2026.** Add a confirmation popup when adding a new client or revenue entry in the cost reporting UI, and allow editing that info after it's been added (currently, entries appear to be add-only with no confirm step). Not scoped further yet — needs a look at the existing agency/sales entry forms in the 💰 Costi modal first.

---

## 34. Safeguard against destructive commands — CRITICAL, incident-driven

**Incident, July 16, 2026:** a wildcard `rm -rf jobs/*/` was included in a terminal test block, followed by a correction telling the user not to run it — but the correction came *after* the destructive line in the same message, so the whole block had already been copy-pasted as one unit before the correction could be seen. Deleted all job directories except one — roughly 32 property jobs' images/clips/audio/finished videos permanently lost (some finished MP4s survived because they'd already been downloaded locally, outside the repo).

**Required safeguard, before this pattern is allowed again:**
- A destructive/wildcard filesystem command must never appear in the same message as a correction retracting it — the correction must come *before* any pasteable block, never after.
- Prefer move-to-a-dated-backup-folder over hard delete for any bulk `jobs/` cleanup.
- Any command matching `rm -rf` touching `jobs/` needs its own isolated, explicitly-confirmed message — never bundled inside a larger test/patch script.

---

## NEXT MILESTONE — Concurrency + Operator Dashboard

**COST REPORTING IS DONE (July 12, 2026).** Built, tested, deployed, live in the UI:
- cost_model.py: agencies, sales, investment ledger (EUR 4,046.01 imported), seller
  commission (20% of first sale per agency), per-job/per-agency/enterprise reporting
- API endpoints: /agencies, /sales, /reports/enterprise, /reports/agencies,
  /reports/jobs, POST /jobs/{id}/commercial
- UI: 💰 Costi button -> modal with break-even progress bar, cost breakdown bars,
  job mix cards, agency table, sales entry forms, per-job classification dropdown
- Claude API cost tracking: real token usage captured from every Anthropic call in
  listing_scraper.py (Haiku 4.5 = $1/$5 per MTok, verified), folded into job cost
- Verified live: EUR 4,167.21 to break-even = 9.3 packages

**NEXT: Concurrency + operator dashboard.** Goal: minimise time the operator spends
at the PC; they intervene only when needed.

1. **Job queue with configurable concurrency ceiling.** NOTE: the 5-jobs/hour rate
   limit in api_server.py is OURS (self-imposed), not a fal.ai limit. Real constraints
   are fal.ai account concurrency and cost. Within a single job, per-scene generation
   is currently sequential and could run in parallel - real speedup, but multiplies
   concurrent fal.ai calls, so it needs the same ceiling.

2. **Dashboard as an INBOX** - show ONLY what needs the operator. Three states that
   require intervention (confirmed with user):
   (a) awaiting setup review - scraped, scenes+TTS ready, BEFORE any money is spent
   (b) QC flagged / rejected
   (c) failed
   Everything else runs unattended and is just progress.

3. **Executor profile** (for hiring): junior/VA-level QC reviewer. Needs visual
   judgment (spot warped walls, phantom mirrors), Italian, real estate literacy.
   NOT technical. Per-video review fee, not salary.

**STILL OPEN - MAXIMUM PRIORITY (see items 27-29):** QC does not reliably catch
hallucinations. Florence-2 caption-diffing is the wrong instrument for detecting
physical implausibility. Luma prompts were tightened July 12 (real anti-hallucination
constraints added - Luma previously had almost none) but this is probabilistic harm
reduction, not a fix. Agent-based QC (item 11) is the real answer.

## Recently completed (see status.md for full detail)

- **Auto maintenance scheduler** — completed and live-tested July 9, 2026. Tiered per-check frequencies via cron, real bugs fixed in the underlying 7-day job cleanup (two separate issues found and fixed), email alerting with cooldown, UI panel with editable recipient list.
- **Duration sliders don't support Luma's actual valid durations (was item 14)** — checked July 16, 2026 and found already fixed: `getDurationRangeForTier()` already returns Luma's real 5s/9s steps, and `onTierChange()` correctly re-ranges and re-snaps existing sliders when the tier dropdown changes. The original bug report predates this fix; no longer reproducible.
- **Manual narration path has no overrun protection (was item 16)** — checked July 16, 2026 and found already fixed: `_overlay_narration_audio()` already computes narration overflow and extends the trailing pad (with fade) to absorb it. The original bug report predates this fix; no longer reproducible.
- **Rework cost tracking + rework progress labeling** — fixed July 13, 2026. See status.md for full detail (tier-aware pricing bug, running-total display, "Rework:" message prefix).
- **Draft scene-count desync** — fixed July 13, 2026. New `/jobs/{id}/draft/resync` endpoint, gated to draft-status jobs only. See status.md.
- **"Aggiungi pause" no-op bug** — fixed July 16, 2026. See status.md for full detail (suggest_pause_padding() wiring, per-job pause persistence).
- **Legacy rework-endpoint migration** — new `POST /jobs/{id}/scenes/redo-batch` replaces the legacy sibling-directory `/rework` call from the main "Genera video" button's auto-rework path. Deployed and **confirmed working end-to-end via real integration test, July 17, 2026** — see status.md for full verification detail.

## Not backlog items — standing watch items (tracked in status.md, not here)

- Rework edge cases that may surface in specific use cases (no confirmed repro yet).
- Maintenance scheduler tiering behavior — pending one more log confirmation (`tail /tmp/maintenance.log`) after a paste error interrupted the last check.
