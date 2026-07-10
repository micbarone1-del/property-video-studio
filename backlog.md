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

- **Auto maintenance scheduler** — completed and live-tested July 9, 2026. Tiered per-check frequencies via cron, real bugs fixed in the underlying 7-day job cleanup (two separate issues found and fixed), email alerting with cooldown, UI panel with editable recipient list.

## Not backlog items — standing watch items (tracked in status.md, not here)

- Rework edge cases that may surface in specific use cases (no confirmed repro yet).
- Maintenance scheduler tiering behavior — pending one more log confirmation (`tail /tmp/maintenance.log`) after a paste error interrupted the last check.
