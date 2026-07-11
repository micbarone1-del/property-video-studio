# Property Video Studio — Backlog

_Last updated: July 9, 2026 — removed "Auto maintenance scheduler" (completed and verified — see status.md), renumbered remaining items._

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

## 14. Duration sliders don't support Luma's actual valid durations

**Problem, confirmed real July 10 2026:** manual per-scene duration sliders move in 4s/6s increments (matching Veo's valid durations), never landing on 5s or 9s — Luma's only two valid clip durations. Any manual duration set via these sliders on the Luma tier gets silently snapped/distorted by the backend, with no indication to the user that their chosen value wasn't actually used.

**Scope not yet defined — needs its own look:** should the slider be dynamic based on the currently selected model tier (5s/9s steps for Luma, 4s/6s/8s for Veo), or should snapping be made visible in the UI instead of silent?

---

## 15. idealista.it / casa.it photo extraction doesn't work yet

**Problem, confirmed via real testing July 11, 2026:** both sites return 0 photos consistently (immobiliare.it works reliably). User's hypothesis: idealista's gallery may require a click to expand, which a static page fetch can't do. Unconfirmed for casa.it specifically — may be a different cause.

**What already works correctly:** the "not enough photos, manual upload needed" fallback fires cleanly — this is the safety design working as intended, not a crash.

**Likely real fix, not started:** find each site's internal image-loading API/endpoint rather than parsing the rendered page — a materially different, site-specific investigation, not a quick patch.

---

## 16. Manual narration path has no overrun protection

**Problem, confirmed via code read July 11, 2026:** `_overlay_narration_audio()` in `api_server.py` (the general/manual narration path, separate from the URL-scraper's own narration engine) has no handling at all for narration running longer than the pre-calculated video duration — only documents the "narration shorter" case. The scraper's own engine has a hard ceiling + fade-out safety net; this path does not.

**Not started** — deprioritized behind core pipeline reliability work this session.

---

## Recently completed (see status.md for full detail)

- **Auto maintenance scheduler** — completed and live-tested July 9, 2026. Tiered per-check frequencies via cron, real bugs fixed in the underlying 7-day job cleanup (two separate issues found and fixed), email alerting with cooldown, UI panel with editable recipient list.

## Not backlog items — standing watch items (tracked in status.md, not here)

- Rework edge cases that may surface in specific use cases (no confirmed repro yet).
- Maintenance scheduler tiering behavior — pending one more log confirmation (`tail /tmp/maintenance.log`) after a paste error interrupted the last check.
