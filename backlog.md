# Property Video Studio — Backlog

_Last updated: September 17, 2026 — item 15 (idealista.it/casa.it scraping) reactivated after being deprioritized July 22, 2026, back to its normal priority position (not jumped to top); item 47 (own-brand watermark) built and pushed September 28, 2026 but not yet live-verified; new item 48 scoped (CRM partner API). Content below this line otherwise reflects work through July 24-27, 2026 (see status.md for full detail) — the "Last updated" line itself had gone stale relative to the body content and is corrected here. Numbering gap between 16 and 30 is a known pre-existing inconsistency from an earlier renumbering, not yet cleaned up._

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
1. Test the same engine against a real idealista.it listing, then a real casa.it listing (see item 15 — still confirmed broken, not started; deprioritized July 22, 2026, reactivated September 17, 2026).
2. Human-review the auto-generated narration/caption text for quality and pacing.
3. Phase 2 automation (currently Phase 1: auto-populates the editor, human presses "Generate Video" manually).

---

## 2. Multi-job dashboard / concurrent job queue -- MERGED into NEXT MILESTONE (below), 2026-07-27

This was a thinner, earlier entry describing the same feature scoped in more detail under NEXT MILESTONE -- Concurrency + Operator Dashboard. Consolidated to avoid two separate backlog entries drifting apart for the same feature. Its one open question (concurrency target vs. fal.ai/ElevenLabs rate limits) is now listed there.

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

## 15. idealista.it / casa.it photo extraction doesn't work yet — REACTIVATED September 17, 2026

**Problem, confirmed via real testing:** both sites return 0 photos consistently (immobiliare.it works reliably).

**Likely real fix, not started:** find each site's internal image-loading API/endpoint rather than parsing the rendered page. **Deprioritized July 22, 2026, reactivated September 17, 2026** — back in the active backlog at its original priority position (part of item 1's remaining scope), explicitly not moved to top priority.

**Idea raised by Relinx (CRM partner, item 48), September 29, 2026, NOT scoped:** scraping listing sites at scale from our server risks IP bans; their suggestion is a small local tool the agency runs on its own PC, logging into its own gestionale (e.g. Getrix) via Playwright with the agency's consent, sending cleaned data to us from the agency's own IP. Real concerns before pursuing this: (1) still automated extraction — the target site's terms may forbid it even from the agency's own account; check for an official export/API first; (2) means shipping and maintaining a desktop app per agency, breaking whenever the target site's UI changes; (3) needs a clear credentials/consent story. Treat as a separate, unscoped idea — not a quick fix for this item.

---

## 30. Depth rendering R&D — REVIVED (potential structural elimination of hallucination)

**Concept:** depth-based reprojection cannot hallucinate — structurally incapable of inventing content not in the source photo. Every prompt-based mitigation (including the July 21 human-shadow fix) is probabilistic harm reduction; depth rendering would be immunity.

**2026-07-27 note: this detail existed in an earlier version of this file (July 17, 2026) and was lost during a later doc rewrite -- restored here after being recovered from an earlier session transcript, since this was exactly the kind of information loss this file exists to prevent.**

**Previous attempt:** `depth_renderer.py` -- numpy + OpenCV pixel-shift reprojection. Hit a real quality ceiling (raw pixel-shift produces occlusion holes and stretching at depth discontinuities), and Luma Ray 2 solved the immediate problem more pragmatically, so this was paused rather than abandoned.

**Motivating evidence:** propertyvideo.ai appears to be shipping this successfully, suggesting the earlier failure was an implementation ceiling rather than a fundamental one.

**Proposed modern approach, not yet built:** pair a much stronger monocular depth estimator -- specifically Depth Anything V2 or Marigold -- with proper inpainting of the disoccluded regions. A materially different technique from the original attempt, not a retry of the same one.

**2026-10-27: re-tested on the real scene-1 photo with the existing depth_renderer.py and REJECTED by Michele (not realistic enough; the earlier implementation took months). Closed unless a new reason appears.** (Previously: not started. Scope to be defined beyond the above.) Would sit alongside the existing model tiers as a hallucination-free option.

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

## 35. Premium ~1-minute video template — ✅ COMPLETED July 24-26, 2026 (function-level tested, live scrape not yet run)

**Fully scoped and built.** Manual per-job toggle, URL-scrape only (not the manual upload form). Extended taxonomy with a "main" + expanded-instance structure per room type (not just more of the same 6 categories), outdoor placed both after the facade and at the closing, explicit three-tier fallback (expand large/outdoor rooms -> add new categories like laundry/office/garage -> reuse photos of the same space, in that strict priority order), photo quality/representativeness reusing the existing Claude-vision ranking mechanism unchanged (it already covered both dimensions). See status.md for the complete scope writeup and a real, worth-knowing behavioral note (tier 1 fully exhausts before tier 2 ever runs).

**Built:** extended `EXTRACTION_PROMPT`, `MIN/MAX_SCENES_PREMIUM` constants, `generate_narration_and_derive_scenes()` gained a `premium` parameter, new `select_photos_for_scene_count_premium()` and `build_premium_video_scenes_config()`, `create_job_from_url()` gained a `premium` parameter and `is_premium` job flag, new UI checkbox. A real duplicate-setup-code catch was found and fixed mid-build (shared `_categorize_and_rank_photos()` helper extracted, plus a genuinely dead, zero-caller legacy function deleted).

**Verified:** isolated, zero-cost function-level tests for both the premium selection algorithm (rich/sparse/too-few-photos scenarios) and the premium/standard scene-count range branching, all confirmed correct, including after the dedup refactor.

**Not yet done:** a real, live scrape of an actual listing has not been run -- explicitly deferred by the user, who judged the isolated tests sufficient for now. Worth doing before fully trusting this in production.

---

## 36. Format detection/normalization gaps in other upload paths — ✅ COMPLETED July 21, 2026

**Was:** the landscape/portrait crop-normalization built for the main manual upload path (`create_job`) didn't cover `add_scene`, `resync_draft`, `redo_scenes_batch`'s new-image handling, or `create_job_from_url` (the URL-scraper).

**Now fixed, all five paths covered.** `add_scene`/`redo_scenes_batch` inherit the job's already-decided format (correct — the job's canvas is already locked in); `resync_draft` re-decides via majority vote each time (correct — still pre-generation); `create_job_from_url` now normalizes right after the scraper downloads and places images, before vision analysis runs. See status.md for full detail.

---

## 37. Luma/Veo camera movement — wobbly/exaggerated — FULLY RESOLVED July 27, 2026 (both general and portrait-specific)

**Reported July 21, 2026.** Two related but distinct issues:

1. **General wobble/stepping — ✅ FIXED July 22, 2026.** Root-caused by direct comparison against Veo's already-working `_VEO_MOVEMENT_TOKENS`: Luma's prompts lacked explicit "3D dolly" terminology and foreground/background parallax framing, and had no degree limits at all. All 11 `_LUMA_MOVEMENT_TOKENS` entries rewritten with both, plus a direct negative instruction against the reported artifact ("no stepping or bobbing"). Same caveat as every Luma prompt constraint: a well-reasoned, evidence-based probabilistic improvement, not a guarantee — a real generation test to confirm it's actually smoother has not yet been run by the user.
2. **Portrait-specific — still open.** Root cause understood (see status.md): a 9:16 frame has roughly a third the horizontal field of view of 16:9 for the same shot, so identical movement settings consume proportionally more of the real photographed content before the model has to invent what's beyond the edge. Luma's prompt system still has no way to apply a portrait-specific reduction the way Veo's explicit degree values would allow. Not addressed by the July 22 rewrite — needs its own dedicated pass with empirical tuning against real photos.

**RESOLVED July 27, 2026.** Explicit product decisions ruled out both a flat 2D pan/zoom (not realistic enough for a property walkthrough) and a simple degree-value reduction (unreliable, since movement descriptions are language, not deterministic camera parameters). Fix: confirmed-problematic lateral/turning movements (walk_in_gentle, walk_in_turn_left, walk_in_turn_right, stand_look_around — the 90-degree look-around option, confirmed never used) remapped to walk_in_explore for portrait output, plus an explicit anti-drift prompt constraint layered on top for both Luma and Veo. Composes correctly with the existing small-room remap. Verified via isolated function-level tests (all 4 movements correctly remap, landscape output unchanged, Veo confirmed alongside Luma, small+portrait cascades correctly).

**Confirmed via a real generation test, July 27, 2026** — user ran an actual portrait job with the confirmed-problematic movement; the video went straight (forward dolly) instead of attempting the rotation, exactly as designed.

**Harmonization follow-up, same day, per explicit request to review all prompts across all formats for hallucination risk — three further real findings:**
1. stand_look_around confirmed broken in ANY orientation, not just portrait (direct user feedback after the live test above) — now unconditionally remapped to walk_in_explore regardless of format, and removed from the UI dropdown entirely as a now-redundant duplicate option.
2. step_out_onto had the largest degree values of any movement (Luma 40°, Veo 60°) and was never addressed by the original portrait fix. Added to the portrait remap list (mapped to walk_toward, exterior-appropriate, not walk_in_explore), and harmonized down to 30° for landscape use in both models — Veo's own 60° directly contradicted _VEO_RULES' global "maximum 30 degrees in any direction," a real self-contradiction sent to the model in every single prompt regardless of movement chosen.
3. approach_reveal behaved differently per model for the identical button — Luma described it as forward/toward-the-space, Veo described it as lateral. Aligned Veo to match Luma's safer, forward description, consistent with its role as the small-room fallback movement (used by _SMALL_ROOM_REMAPS).

UI labels updated to match all of the above.

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

1. **Job queue with configurable concurrency ceiling.** The 5-jobs/hour rate limit in api_server.py is OURS (self-imposed), not a fal.ai limit. Real constraints are fal.ai account concurrency and cost. **Open question, merged from item 2 (2026-07-27):** the actual concurrency target has not been checked against fal.ai/ElevenLabs real rate limits -- needs that check before final scoping.

2. **Dashboard as an INBOX** — show ONLY what needs the operator: (a) awaiting setup review before any money is spent, (b) QC flagged/rejected, (c) failed. Everything else runs unattended.

3. **Executor profile** (for hiring): junior/VA-level QC reviewer. Visual judgment, Italian, real estate literacy. NOT technical. Per-video review fee, not salary.

**STILL OPEN — MAXIMUM PRIORITY:** QC does not reliably catch hallucinations. Agent-based QC (item 11) is the real answer; every prompt-level mitigation built so far is harm reduction, not detection.

## 42. Per-scene audio lead/trail buffer -- ✅ COMPLETED AND CONFIRMED July 23-24, 2026

**Reported.** Per-scene voiceover audio started with zero lead-in silence, cutting the first fraction of a second of speech when a video was forwarded through a messaging app.

**Fixed, in two passes:** first added `SCENE_AUDIO_LEAD_SECS`/`SCENE_AUDIO_TRAIL_SECS` (0.5s each) in `video_assembly.py`, then discovered and fixed a much deeper root cause -- moviepy's `.with_audio()` silently ignores an audio clip's `.with_start()` offset unless wrapped in `CompositeAudioClip`, which meant this buffer (and the separate continuous-narration one) was being computed correctly but never actually reaching the rendered file. See item 45 and status.md for the full root-cause writeup.

**Confirmed working in the real world, July 24, 2026:** user confirmed the buffer holds even after the video is sent via email and forwarded through WhatsApp -- the original real-world symptom this item started from.

---

## 43. Audio-only rework -- ✅ COMPLETED AND USED July 23-24, 2026

**Requested**, directly motivated by wanting to test item 42's buffer without paying for video regeneration.

**Built:** `run_redo_audio_only()` in `api_server.py`, new `POST /jobs/{id}/scenes/redo-audio-only` endpoint, new "Rigenera solo audio" UI button. See status.md for full detail.

**Confirmed working:** this real capability is what let item 42's buffer be re-tested and root-caused at zero additional Luma/Veo cost on a real job.

---

## 45. Real root-cause bug: moviepy .with_audio() ignores .with_start() without CompositeAudioClip -- ✅ FIXED July 24, 2026

**Discovered while investigating item 42's real-world report.** Confirmed via an isolated moviepy test: a shifted audio clip attached directly to a video via `.with_audio()` completely ignores its own `.with_start(t)` offset, playing from t=0 regardless. Wrapping the SAME clip in `CompositeAudioClip([clip])`, even alone, correctly respects the offset.

**Real impact:** this silently broke BOTH of this session's lead/trail buffer fixes -- `_overlay_narration_audio()` in `api_server.py` (the continuous-narration track) computed and logged the correct values every time but never applied them, and `video_assembly.py`'s per-scene audio positioning had the identical bug specifically for any job with only one audio-carrying scene (the single most common case), via a `CompositeAudioClip(positioned) if len(positioned) > 1 else positioned[0]` shortcut that bypassed the composite wrapper.

**Fixed** in both locations by always wrapping in `CompositeAudioClip`, regardless of clip count. Verified directly on the real problem job via real audio-volume measurements at 0.1s intervals, and later confirmed by the user in the real world (sent via email, forwarded through WhatsApp, buffer intact).

---

## 46. Real cost-tracking gap: narration regeneration never recorded its own cost -- ✅ FIXED July 24, 2026

**Reported:** "still missing TTS cost estimation when I run a rework."

**Confirmed:** `/jobs/{id}/narration` makes a real, billable ElevenLabs TTS call every time it runs, but never recorded that cost anywhere in `cost_actual`.

**Fixed:** reuses the existing `calculate_rework_cost()`/`format_cost_display()` pattern (same one used for scene reworks and item 43's audio-only rework) rather than a new, parallel calculation. Verified the cost math in isolation without triggering a real, billable call.

---

## 44. Investment ledger single-entry management -- ✅ COMPLETED July 23, 2026

**Requested** (track this Claude Pro subscription, €21.96/month, as part of overall investment tracking). **Found:** the investment ledger (`cost_model.py`'s `investment.json`, driving the "Investimento (fisso)" figure) had no way to add a single entry -- only a full-ledger replace, apparently meant for an XLS re-upload workflow that was never built.

**Built:** `add_investment_entry()`/`delete_investment_entry()`, new `GET`/`POST /investment`, `DELETE /investment/{index}` endpoints, a new Investment section in the cost modal. The real Claude Pro entry was added -- its note flags that a new entry is needed each billing cycle to stay current, since there's no automatic recurring-cost mechanism. See status.md for full detail.

## 47. Own-brand "Property Video Studio" watermark on every video — NEW, scoped September 17, 2026

**Requested September 17, 2026.** A permanent brand watermark burned into every generated video, unconditionally — distinct from item 7's client logo, which is optional and per-agency. This is Property Video Studio's own mark, meant to appear regardless of which client the job is for.

**Decisions made (explicit product choices, not assumed):**
- **Position: bottom-left corner** — deliberately the opposite corner from item 7's client logo (bottom-right), so both can be shown at once without overlapping.
- **Asset:** the first file provided was a JPEG with a solid white background — unusable as-is, since JPEG carries no alpha channel and would composite as a white rectangular block rather than a clean overlay. User will supply a proper transparent PNG instead.

**Status, September 28, 2026 — BUILT and pushed, NOT yet live-verified.** Transparent PNG received (first two supplied files had no alpha; the gray-background PNG was keyed out and downscaled to 420px, palette PNG, ~7KB) and stored at `assets/pvs_watermark.png`. `assemble_property_video()` in `video_assembly.py` now composites it as a second, unconditional, non-fatal layer after item 7's client-logo layer: bottom-left, full duration, **fixed 210px width and 40px margin** (not a percentage of frame width — a percentage looked too big on landscape and too small on portrait in side-by-side previews; fixed pixels approved on both). Commit 08906d6, merged and pushed to main. Py-compile OK on the server. **The service has NOT been restarted and no real video has been produced with it yet** — the test (assemble from real archived clips in landscape AND portrait, view a frame, confirm no overlap with a client logo) is still to do. Also committed by mistake: `video_assembly.py.bak_pre_watermark` (harmless local backup, should be removed from the repo).

**Update September 28, 2026:** the watermark stays on all CRM-partner videos (item 48) — these are free videos and the watermark is the advertising. If a paid, watermark-free tier is ever offered it will need a per-partner/per-agency flag; not built, since the watermark is currently unconditional by design.

---

## 48. CRM partner API — video production from Relinx's CRM data — NEW, scoped September 28, 2026, confirmed September 29, 2026

**Context:** the partner is **Relinx**, a real-estate CRM (holds photos, features and descriptions per property). Their customers (agencies) would get property videos produced from Relinx data. Free videos with our watermark (item 47) which get advertised via posting on major platforms. Technical contact on their side: Michele (same first name as us — do not confuse the two in notes). Nothing built yet; no contract, no legal review yet.

**Design principle (architecture discipline, item 38):** the API must be a thin adapter over the SAME job-creation path the manual and URL-scraper flows already use (`create_job()` / `start_generation_for_draft()` in api_server.py, and the same `assemble_property_video()`), NOT a third pipeline. Search for existing equivalents before adding anything.

**Decisions made September 28, 2026:**
- **Human review stays** until auto-QC is trusted (item 11). The partner sees a pending/WIP state until an operator approves. No auto-release for now.
- **Watermark stays** on all partner videos (see item 47 update).
- **Limits and dashboard:** proposed parameters below; they are to be folded into the dashboard design principles (NEXT MILESTONE).
- **Resolved September 29, 2026: on-demand only** (agent clicks a button per listing), not automatic for every listing — confirmed with Relinx.

**Confirmed with Relinx, September 29, 2026 (their answers to our questions):**
1. **Volumes:** 2 videos/day per agency is acceptable to them — but only 1 agency runs at pilot start (see point 6), so this is a generous ceiling relative to real pilot traffic, not a tight constraint.
2. **Photo hosting:** direct public URLs, no authentication — we read them as given in the request package. SSRF protections below still apply since these are still partner-supplied URLs.
3. **Their integration pattern (already in production on their side, same as their Google Calendar push-notification pattern):** they POST a package to our endpoint, we reply immediately with id+status, and separately we call back to one of THEIR endpoints when the video is ready. This matches our design below (POST /v1/videos → 202, then webhook to callback_url) — no redesign needed.
4. **Where it appears / approval:** shows in the property record with what Relinx calls "the 4 states" (referencing a box in their own message we have not seen the content of — **open, see below**). Alert fires when the video arrives; sharing requires an explicit click from the agent/admin (matches our "no auto-release" decision).
5. **Rights/privacy — CONFIRMED REAL GAP, not hypothetical:** Relinx's current agency agreements do NOT cover using photos for third-party video generation or social publication. A dedicated agency-side consent addendum plus a data-processing agreement between us and Relinx are both required before launch. This is a go/no-go blocker for the pilot, not a nice-to-have — needs a lawyer, not something to resolve in chat.
   - **September 30, 2026, Relinx's follow-up:** they state each agency already has a "liberatoria" covering data that is currently public (i.e. already on a listing site), and frame the missing inter-company DPA as minor "since it's data already on the web." **Not accepted at face value** — an existing release for publishing a photo on a portal is a different use than a third party processing it to generate a new derivative video and publishing that on social platforms; we pushed back on this in writing (September 30) and asked them to have their lawyer confirm rather than assume. Still open, still a blocker. **September 30, 2026: deliberately set aside for now** (not resolved, not waived) so technical work can continue — Relinx repeated their "normal release covers it" position once more; this must be closed before real agency data goes live, whenever the two sides pick it back up.
   - **Resolved September 30, 2026:** Relinx never provided their own literal "4 states" list after three requests — instead confirmed OUR proposed 5 states as-is: `queued`, `processing`, `in_review`, `completed`, `failed`. This is now the agreed partner-facing status vocabulary, not a mapping onto something of theirs.
   - Relinx suggested moving quick exchanges to WhatsApp; agreed for speed, but contract and workflow specifics are being kept in writing (email) deliberately.
6. **Target agencies:** 1 agency for the pilot, extending to 3 more afterward based on results (4 total eventually). The global multi-agency cap for that later stage is intentionally NOT set yet (see Proposed limits below).
7. **Getrix is irrelevant to this integration** — dropped. Data comes from Relinx's own CRM, already the single source of truth on the agency side. (The Playwright/local-tool idea Relinx separately floated is a possible future approach for OTHER, non-CRM-integrated agencies — see the note added to items 1/15, not part of this item.)

**Open, not yet answered:** the exact 4 states Relinx's own box refers to (need the literal list/names before finalizing our 5-state model above — a status-vocabulary mismatch would break the integration silently).

**Proposed API (v1, sketch, not final):** Bearer API key per partner, mapped to agencies, hashed at rest, versioned URLs.
- `POST /v1/videos` → 202 `{id, status}`; `Idempotency-Key` header required (no double charges on retry).
- `GET /v1/videos/{id}` → status, progress, signed expiring `video_url` when completed. `GET /v1/videos?external_ref=` looks up by the CRM's own listing ID.
- `DELETE /v1/videos/{id}` (GDPR erasure) — must go through the app's soft-delete/recovery mechanism, never a raw delete under jobs/.
- `PUT /v1/agencies/{external_id}` — name, logo URL (item 7 rules: PNG with alpha), default voice, language.
- Webhooks to partner `callback_url`, HMAC-signed: `video.in_review`, `video.completed`, `video.failed`.
- Create body: `external_ref`, `agency_id`, `property {name, description, features[], language}`, `photos[{url, room_type, order}]`, `options {format landscape|portrait, voice_id, template standard|premium}`, `callback_url`.
- Photos are fetched server-side from partner URLs → SSRF protection (per-partner domain allowlist, image type/size checks, photo-count cap, timeouts).
- **Partner-visible statuses:** `queued`, `processing`, `in_review` (human review pending, shown to the partner as pending/WIP), `completed`, `failed`. Internal states (QC flagged, rework, etc.) are never exposed. A rejected video is either reworked (stays `in_review`/`processing`) or ends as `failed` with a generic reason.

**Finalized pilot limits, September 29, 2026 (supersedes the earlier draft numbers, which assumed multiple agencies from day one):**
- Per agency, daily: **2 videos** (confirmed acceptable by Relinx).
- Per agency, monthly: **40 videos** — deliberately below the 60 a daily max would allow, so even sustained daily maxing forces a checkpoint before month-end.
- Total during pilot: same as per-agency, since only 1 agency is active at pilot start (point 6). The global cap for the later 4-agency stage is an open decision, NOT simply 4x — depends on how the pilot goes and on our own infra capacity, to be revisited then.
- Concurrency: max 2 partner jobs generating at once — a technical safety cap (no real queue exists yet), not a business one; real volume won't stress this.
- Rework: 1 free regeneration per video (reworks cost real money).
- Input: 5 to 15 photos per video; JPEG/PNG/WebP; min 1024px on the long edge; max 15MB each.
- API burst limit: 5 requests/minute (generous headroom at this volume; just guards the server).
- Review SLA: operator review target within 1 business day; alert when the oldest `in_review` item exceeds 24h.
- Retention: source photos deleted 30 days after completion; finished video kept 90 days; download links signed and expiring (7 days, re-issuable).
- Still not validated: real cost per video from cost_model, and fal.ai/ElevenLabs real concurrency limits — that check is still open, see NEXT MILESTONE.

**Dashboard design principles (feed into NEXT MILESTONE):**
1. The operator inbox shows only what needs a human: awaiting review, QC flagged, failed. Everything else is silent.
2. Every item shows its source (manual, scraper, partner name) and its age; oldest-pending is the headline number.
3. Per-partner panel: quota used vs limit (day/month), concurrency in use, spend vs ceiling, rework count.
4. Global panel: queue depth, jobs generating vs the ceiling, spend burn vs the global ceiling.
5. Limits are configuration, editable per partner without a deploy; hitting a limit returns a clear 429 with `Retry-After`, never a silent drop.
6. One shared queue for all sources — no separate path for API jobs.

**Draft terms to raise with the CRM partner (NOT legal advice — needs review by an Italian lawyer before anything is signed):**
- Roles: CRM/agency is the data controller, we are the processor; a data-processing agreement is required. Our sub-processors (fal.ai, ElevenLabs, Anthropic) must be listed, and data may leave the EU, so transfer safeguards (e.g. standard contractual clauses) need checking.
- Photo rights: the partner warrants that the agency has the right to use the photos, to have videos generated from them, and to have them published; people visible in photos are a risk.
- Publication: because we advertise by posting the videos on major platforms, we need an explicit, separate right to publish them with agency consent — this is the point most likely to be contested.
- Accuracy: videos are AI-generated approximations of the property. The agency must review and approve before publishing; we do not warrant that a video is free of hallucinated features. Misleading-advertising rules apply to the agency.
- AI-generated content: check transparency/labelling obligations for synthetic video (EU AI Act). The "generated with Property Video Studio" watermark may help but must be verified with counsel.
- Pilot terms: no uptime SLA, liability cap, deletion of all data on termination, either side can end the pilot at any time.

**Prerequisites / dependencies:** item 47 verified live; the concurrency queue + operator dashboard (NEXT MILESTONE); item 39 (client/property/job library) is the natural home for agency and property records; item 11 (agent QC) is what eventually allows dropping the human review gate. Structured CRM data removes the need for scraping listing sites for these customers, which lowers the urgency of item 15 for this channel.

**Still open:** the exact 4-states list Relinx's box refers to (see above); the rights/DPA addendum (above — blocking) -- a first working draft now exists (Claude Doc, built October 6, 2026, covering roles/DPA, sub-processor transfers, publication rights, AI-content liability, retention; explicitly NOT legal-reviewed and not yet sent to Relinx); who pays if this becomes paid; whether partner agencies see the operator review step at all. The full real pipeline (API receive -> narration -> photo resolution -> vision analysis -> draft) was verified end-to-end for the first time October 7, 2026 using real listing data (Albano Laziale / GIAL) -- surfaced the real bugs listed in status.md's October 7 section (vision misclassification, QC-panel-on-reopen, narration/scene sync) that a live partner integration will hit for real. Resolved and removed from this list: on-demand vs automatic (on-demand), photo hosting (public URLs), volumes (2/day/agency), target agencies (1, then 3 more), Getrix (irrelevant).

**Implementation status, September 30 – October 1, 2026 — core pipeline BUILT and verified end-to-end over real HTTPS; two real pieces still missing before Relinx can actually be connected (see below).**

Built, committed, and tested:
- `partner_api.py` — partner key mechanism (SHA-256 hash at rest, never stores plaintext), separate from `UI_ACCESS_KEY`. `get_current_partner` FastAPI dependency added to `api_server.py`.
- Real bug found and fixed (also benefits item 1/URL-scraping): `classify_uncategorized_photo()`'s Florence-2 fallback was silently broken — it only asked Florence-2 about room *size*, never room *type*, so kitchen/living/bathroom photos always fell through to "uncategorized" (only "bedroom"/"exterior" matched by word-overlap coincidence). Replaced with a direct Claude vision call, same pattern as `rank_photos_by_quality()`. Deliberately limited to the 6 `PRIORITY_ORDER` categories, not the 9 `EXTRACTION_PROMPT` allows, to avoid a value silently vanishing in `_categorize_and_rank_photos()`.
- `_apply_vision_analysis_to_scenes()` extracted from inline code in `create_job_from_url()` into a shared function — both the URL-scraper path and the new Relinx endpoint call the same implementation for camera-movement analysis, per architecture discipline (item 38).
- `POST /v1/videos` — the actual Relinx-facing endpoint. Thin adapter: agency lookup/creation, narration, photo selection (explicit category or Claude-vision fallback), download, captions, scene building, vision analysis — all reusing `create_job_from_url()`'s existing building blocks, no parallel pipeline. Job always stops in internal `"draft"` status (human review before generation, per Michele's explicit decision); external response is `{"id": ..., "status": "in_review"}`. Status mapping (internal → external, to be reused by the future `GET /v1/videos/{id}` and the webhook): `draft`/`awaiting_approval` → `in_review`; `queued`/`running` → `processing`; `done` → `completed`; `failed` → `failed`.
- Two real bugs found only at live-test time (neither caught by `py_compile`, both fixed same session): (1) `Depends` used in the new endpoint's signature but never imported from fastapi — crashed the whole server on startup (`NameError`), caught immediately since the server wouldn't boot, zero live-traffic impact; (2) the global `UI_ACCESS_KEY` middleware (meant for the admin UI) was intercepting `/v1/*` before it reached partner-key auth — fixed by excluding `/v1/*` from that middleware (it still has its own, separate auth via `get_current_partner`, so this is not a security regression).
- End-to-end tested successfully, twice: once against `localhost:8000` directly, once against the real public HTTPS domain — both explicit photo category and the Claude-vision auto-classification fallback confirmed working on real photos.
- Domain: `propertyvideostudioai.com` registered on Hostinger (same account as the server — no transfer needed). `api.propertyvideostudioai.com` A record → `187.77.196.94`.
- `nginx` and `certbot` installed (none existed before — first time this project has needed a reverse proxy). Reverse proxy on port 80 → `127.0.0.1:8000`. Real HTTPS certificate obtained via Let's Encrypt (expires 2026-12-30, auto-renewal already scheduled via `certbot.timer`). HTTP → HTTPS redirect enforced.
- Hostinger VPS firewall (separate from the OS firewall, which has no rules at all — confirmed via `iptables`/no `ufw` installed): default-drops all incoming traffic. Added Accept/TCP rules for ports 80 and 443 (22 and 8000 were already present). Must remember this firewall for any future port this app needs to expose publicly.

**Update, October 1, 2026 (afternoon) -- all remaining pieces built AND verified end-to-end. The API is functionally complete.**

Built, committed, and tested this session:
- **Completion/failure webhook** (`_send_partner_webhook`), hooked into the shared `run_reassemble_only()` convergence point. Verified for BOTH events (`completed` and `failed`) against a real webhook.site receiver -- HTTP 200, correct payload shape. Verified a dead `callback_url` fails safely (caught, logged as a warning, never breaks the job).
- **New-job alert email.** First attempt silently failed (reused `communication.py`'s `send_custom_email()`, which needs `EMAIL_USER`/`EMAIL_PASS` -- never configured in `.env`). Fixed by switching to `maintenance_scheduler.send_maintenance_alert()`, which uses the actually-configured `EMAIL_FROM`/`EMAIL_PASSWORD` and the existing recipient list, with no cooldown baked into the function itself. Verified: a real email arrived with correct property/external_ref/job_id details.
- **`GET /v1/videos/{id}` and `GET /v1/videos?external_ref=`**, plus a shared `_map_internal_status_to_partner_status()` (now also used by the creation response, replacing a hardcoded literal). Caught and fixed a real bug from my own patch here: the status-lookup and download endpoint decorators had been accidentally swapped (status lookup was serving the raw video file, download was returning JSON) -- found only because I tested the actual response instead of trusting a clean compile.
- **Partner-authenticated download**, `GET /v1/videos/{id}/download` -- verified serving a real 13MB file with the correct partner key.
- **A real nginx incident, self-inflicted and fixed same session:** extending the proxy timeout (needed because job creation's multiple sequential Claude calls exceeded nginx's default 60s) was done by overwriting the entire config file, which deleted certbot's SSL block without noticing -- HTTPS was silently down (port 443 refused connections) until caught by testing the public endpoint again, not assumed fine from the earlier "it compiled" success. Rebuilt the config with both the SSL block and the extended timeouts together; verified via a full `curl -v` showing the real 301 redirect and a working HTTPS response.
- **Agency rate limit**, 2 videos/agency/rolling-24h as agreed with Relinx -- precise `Retry-After` header (not a flat guess), counts only successfully-created `source=relinx` jobs (a 422 for too-few-photos doesn't consume quota). Verified: 429 on an agency already over its limit from earlier testing, 200 on a brand-new agency.
- **Partner-keyed agency lookup**, found necessary during rate-limit testing: `create_agency()`'s name-only matching (correct for a human operator typing a name) risks silently merging two real, different agencies that happen to share a name -- a real problem once Relinx's own multiple client agencies are in play. Added `agency_external_id` to the request schema plus `cost_model.create_agency_for_partner()`/`find_agency_by_partner_ref()`, keyed on `(partner_id, external_id)` instead of name; falls back to today's name-only behavior if Relinx doesn't send one. Verified: same external_id with an updated name correctly merges and renames; the SAME name with a different external_id correctly creates a separate agency (the exact collision this exists to prevent).
- **QC-redo path**, confirmed with a real rework (no code change needed -- this was pure verification): a job that went through `/approve` with `redo_scenes` (not `approved_scenes`) still converges on the same shared completion point, and both the webhook and the alert email fired correctly afterward.
- **Partner isolation**, verified with a second real test partner: partner B gets a 403 ("This job does not belong to your account") both for status lookup and for download on partner A's job. An invalid key and a missing key both correctly return 401 over real HTTPS.

**Not yet done -- small, no longer blocking, worth doing before real traffic:**
1. **Real Relinx partner key generated October 1, 2026** (partner_id `pt_54820049`) and handed to Relinx. The earlier test key (`pt_08d67c8d`) has been deactivated.
2. `.bak_pre_*` files have accumulated on the server (10+ from this session alone) -- harmless (untracked, not in git) but worth an `rm` now that the integration is stable.
3. `WEBHOOK_SIGNING_SECRET` is still unset -- webhooks send unsigned. Fine until Relinx confirms how they'll verify a signature.
4. The known `cost_actual` bug (see its own note elsewhere in this doc) affects any job -- Relinx's included -- that goes through QC-approve-without-redo. Deliberately deferred, not a blocker for launch.

**October 2-3, 2026 session -- first real Relinx job tested end-to-end live, three real production bugs found and fixed, plus a new universal release gate:**

- **URGENT, async timeout fix:** `/v1/videos` used to do all the slow work (narration, photo download, captions, vision QC) synchronously inside the request. Confirmed live: Relinx's real client timed out around ~30s and retried 4 times (nginx logged 499s) while our pipeline kept running in the background and actually succeeded each time -- creating 4 duplicate jobs for the same external_ref (job `cc2aead8` plus 3 duplicates, the 3 relabeled `source=relinx_duplicate_retry_2026-10-02` so they don't consume the rate-limit quota, not deleted). Fixed: `/v1/videos` now does only the fast synchronous checks (agency, rate limit, **new idempotency check** -- returns the existing job for a repeat `external_ref` instead of creating a duplicate) and returns immediately with `status=queued`; the slow work moved to a background task (`_build_relinx_job_in_background`).
- **Latent bug found while fixing the above:** `_map_internal_status_to_partner_status()` never actually had `"done"` in its mapping table -- a genuinely finished job fell through to the `"processing"` default. Relinx would have seen a completed video reported as still processing. Fixed, and tied to the new release gate below (a job's external status is `"completed"` only once released).
- **New universal release gate (explicit operator request, not Relinx-specific):** `POST /jobs/{id}/release` -- for ANY job, not just Relinx's. The partner "completed" webhook no longer fires automatically the instant assembly finishes; the operator now reviews the finished video first and explicitly releases it. No UI button built yet for this -- currently triggered via a direct API call on the server. **Open backlog item: build the UI button.**
- **Backend-only bug, not yet fixed:** generating narration (`🎙 Genera voiceover`) on a job reopened from the library can incorrectly try `/draft/resync` and fail with "Job is no longer in draft status" -- `currentJobStatus` (browser-memory) can go stale. Fixed in `ui.html`'s `generateNarration()` by re-checking status fresh from the server before deciding, mirroring the same safety-guard pattern the main "Genera video" button already used. Confirmed this does NOT lose data when it fires -- the narration text itself still saves correctly even when this specific resync sub-step errors.
- **Separate, confirmed-real, NOT yet fixed:** marking a scene for rework (`↺ Rifai questa scena`) only stages it (`sceneUserData[i].rework_open = true`) -- the actual submit happens via the main "Genera video" button, which correctly checks for open rework panels before any narration-reassembly shortcut (confirmed by reading the live code -- no bug there). The real open question is why a real attempt to redo scene 4 together with a narration update didn't visibly reflect scene 4's regeneration -- not fully root-caused this session, revisit with a clean reproduction.
- **Three real, general (not Relinx-specific) video_assembly.py bugs found and fixed, affecting every job that uses the "fade" transition with the PVS watermark (backlog item 47) and/or a client logo (item 7) -- see status.md for the full architecture writeup:**
  1. PVS watermark PNG was palette-mode with a tRNS chunk MoviePy's ImageClip doesn't read as real alpha -- composited as a fully opaque black box. Fixed: asset regenerated as true RGBA, and the loading code hardened to always force `.convert("RGBA")` via PIL regardless of source file mode.
  2. The "fade" transition's manual `with_start()` + `CompositeVideoClip([bg]+result)` approach showed a real ~0.5s solid-black gap at every transition once 3+ real clips were involved (confirmed via frame-by-frame luminosity scanning a real produced video) -- not caching, not perception, reproduced and fixed in isolated tests.
  3. **The real fix took two attempts.** First attempt: moviepy's own `concatenate_videoclips(..., padding=-td, method="compose")` fixed the transition cleanly -- but compositing the watermark/logo onto each clip BEFORE concatenation (to avoid nesting a nother composite around the transition result) broke the watermark's OWN transparency instead, confirmed on real production clips (not caught by an earlier synthetic-color test, which coincidentally didn't reproduce it). **Final fix:** manual numpy alpha-blending via `.transform()` on the final assembled clip, bypassing MoviePy's CompositeVideoClip/mask system entirely for both the watermark and the client logo. Verified clean (varying, correct pixel values, zero black) on the real cc2aead8 production clips end-to-end.
- First real video (`cc2aead8`, Borgo Giuseppe Garibaldi 36, Albano Laziale) successfully released to Relinx October 3, 2026 -- webhook delivered, HTTP 200 confirmed from their real endpoint (`realestate.centroscs.it`).
- Sent Relinx a follow-up email (Oct 3) flagging the delivery and opening discussion on: standard vs premium (~1min) tier choice, who writes per-scene captions, and whether they want more control over narration tone/content (today it's fully AI-written from their description, not editable by them).

---

## 49. Save Relinx's full original photo list on the job (not just the selected subset) -- NEW, scoped October 3, 2026

**Problem, confirmed real:** today only the photos actually SELECTED for the video's scenes get downloaded and kept (`jobs/{id}/images/scene_NNN.jpg`). The full candidate list Relinx sends (every photo + its category, before our selection logic narrows it down) is never stored anywhere -- not on the job, not logged. Confirmed lost for job `cc2aead8` specifically (checked the server log for that request, not there either).

**Why it matters:** no way to audit afterward which photos Relinx actually offered vs. which ones our selection logic picked -- useful for debugging bad selections and for understanding what Relinx's agencies are actually providing.

**Scope (not yet built):** in `_build_relinx_job_in_background()`, store `payload.photos` (the full list with URL + category, as received, before `resolve_uncategorized_photos`/`select_photos_for_scene_count` narrow it) as a new field on the job dict, e.g. `"relinx_photos_offered"`. Low-risk, additive-only change -- no existing logic touched, just one more field written to `job_meta.json`.

---

## 50. Operator notification system (push + email) -- ✅ COMPLETED October 6, 2026

**Problem:** the only alert channel was email, which Michele doesn't check frequently enough for anything time-sensitive (new Relinx job awaiting review, QC-flagged job, failed job). Monitoring is also expected to eventually move to a contractor/student, not stay solely Michele's.

**Built:** `send_ntfy_push()` + unified `send_notification()` (email + push together) in `maintenance_scheduler.py`; topics stored as an editable list (`notification_topics.json`, `GET/POST /maintenance/notification-topics`) so a second person's topic can be added later with no code change. One shared `_notify_operator()` helper in `api_server.py`, used by all 5 hooked call sites (new partner job, QC-gate pause, and all 3 failure points in `_build_relinx_job_in_background()`) plus the existing RED-flag maintenance dispatch -- no per-site duplication.

**Verified:** real push notification sent and confirmed received on-device before considered done.

**Deliberately deferred:** 5 non-Relinx `status: "failed"` sites in the legacy/manual pipeline, each already written inline rather than through a shared function, left un-hooked this pass -- flagged as a known duplication pattern worth consolidating if/when monitoring needs to cover non-Relinx jobs too.

## 51. TTS provider: ElevenLabs → Google Cloud TTS -- ✅ COMPLETED October 6, 2026

**Why:** ElevenLabs ~€300/year flat; Google Cloud TTS covers real volume within its free tier at any voice tier, confirmed against Google's own pricing page. Open-source self-hosting explicitly researched and rejected: best options (XTTS v2, Fish Speech) are non-commercially licensed, commercially-licensed options (Piper) are materially lower quality, and all practical options need a GPU this VPS doesn't have.

**Built:** `voice_generation.py`'s `generate_speech()` branches on a new `TTS_PROVIDER` env var (default unchanged: `elevenlabs`). Both providers share the same break-tag text-building logic and converge on the same noise-gate/export pipeline -- one function, not two. All 5 real call sites across the codebase already route through this one function (confirmed via grep), so no other file needed changes.

**Voice:** `it-IT-Chirp3-HD-Leda`, chosen by generating and listening to 6 real candidates via Cloud Shell, narrowed to 4, final pick by Michele.

**Verified:** a real `generate_speech()` call against the live Google API produced an actual playable MP3 (18.5KB) before considered done. Committed and pushed (`e8801dd`).

**Still open:** ElevenLabs account intentionally not cancelled yet (kept as live fallback, one `.env` line to switch back). A UI toggle for provider selection was discussed and explicitly deferred -- today `.env`-only.

## 52. Camera movement rule fixes -- agreed October 7, 2026, NOT implemented

Three fixes scoped and agreed with Michele, then never written (pulled into narration/Luma work instead):
1. Global motion-intensity default: "Natural pace" -> "Very slow" (slow pace works everywhere, not just large spaces -- Michele's real-world observation).
2. Merge `medium` and `bedroom` space-type movement to both use `walk_in_gentle` (the real distinction is size, not room type).
3. Balcony (`step_out_onto`, "Esci verso") prompt: confirmed real via a manually-category-selected test -- camera moves toward the interior instead of the outward view. Root cause: the prompt says only "pan across the outdoor space," no outward-direction wording. Fix text already drafted.

Also: the frontend/backend drift on the `small` space-type default movement (`ui.html`'s `SPACE_DEFAULT_MOVEMENT_MAP` says `approach_reveal`; `video_generation.py`'s `SPACE_DEFAULT_MOVEMENT` says `subtle_rotate`) -- found October 7, still not fixed.

## 53. QC-approval panel vanishes on reopening a job with scenes still awaiting approval -- found October 7, 2026

**Problem:** `showQcReview()` only runs during the live polling loop right after a job finishes generating. Reopening an existing job later via the library (`editJob()`) never checks whether the job's real status is still `awaiting_approval` and never re-shows the panel -- the approve/redo step becomes completely inaccessible. Confirmed against a real job (`relinx_test_7f7a5127`, left with `awaiting_scenes: {rejected: [1, 5]}` unreachable).

**Scope (not yet built):** on job load, check the real status; if `awaiting_approval`, render the same QC panel shown during live polling. Touches both the load path (`editJob`/`loadJobIntoUI`) and the render path (`showQcReview`) -- not a one-line patch.

## 54. Narration-to-visual scene order sync -- real architecture limit found October 7, 2026

Item 51's scene-order instruction (`scene_category_order`, built the same day) is a soft prompt nudge, not a hard constraint -- verified via a real full-pipeline test that the model follows the source description's own structure more than the category-order hint, so spoken content can land out of step with what's on screen at that point in the video.

**Michele's own diagnosis, confirmed correct:** true sync likely needs narration generated **per scene/category** rather than as one paragraph with an order hint -- a real design change (how/when narration text is built relative to scene selection), not a prompt tweak. Needs its own scoping pass next session: whether to generate narration in one call with per-scene sections, or one short call per scene stitched together, and how that interacts with the existing duration-measurement/extend-shorten correction loop.

## 55. Vision-based space-type classification is unreliable (Florence-2) -- reinforces item 11 with concrete new evidence

October 7: running the real Relinx pipeline twice surfaced the same class of misclassification both times -- a living room (Florence's own caption correctly said "living room") classified as `bedroom`; a balcony (Florence's own caption correctly said "balcony") classified as `large_interior` with movement `stand_look_around`, a movement the codebase already documents elsewhere as broken. Not a one-off: reproduced twice, different photos. Strengthens the case for item 11 (agent-based/Claude-vision QC and classification) being the real fix rather than further tuning of the Florence-2-based classifier.

## 56. Credit/balance monitoring for Google TTS and Luma direct -- requested October 7, 2026, not yet scoped

Michele asked explicitly that both new paid providers (Google Cloud TTS, Luma direct/Agents API) get added to the existing maintenance-routine credit-check mechanism (today covers fal.ai and ElevenLabs). Not yet investigated whether either provider exposes a programmatic balance/quota endpoint -- needed before this can even be scoped, let alone built.

---

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
- **Real root-cause bug fixed: moviepy CompositeAudioClip requirement, breaking both audio buffer fixes** — July 24, 2026. See item 45. Confirmed working in the real world (email + WhatsApp forward).
- **Real cost-tracking gap fixed: narration regeneration cost** — July 24, 2026. See item 46.
- **Premium ~1-minute video template, full scope** — July 24-26, 2026. See item 35 (live scrape test not yet run, deferred by explicit user choice).
- **Operator notification system (push + email), Relinx events** — October 6, 2026. See item 50.
- **TTS provider migrated ElevenLabs → Google Cloud TTS (Chirp3 HD Leda)** — October 6, 2026. See item 51.
- **Client logo sizing normalized (content-bbox crop before resize)** — October 7, 2026.
- **Luma direct (Ray 3.2, Agents API) active in production, fal.ai/Veo fallback preserved** — October 7, 2026.
- **Real bug fixed: `/jobs/from-url` unreachable since Sept 30 (misplaced route decorator)** — October 7, 2026.
- **Narration template (agency name, feature scope, scene-order hint)** — October 7, 2026. See item 54 (scene-order sync needs a real architecture revision, not reliable as built).

## Not backlog items — standing watch items (tracked in status.md, not here)

- Rework edge cases that may surface in specific use cases (no confirmed repro yet).
- Maintenance scheduler tiering behavior — pending log confirmation.

---

## 57. Cost tracking: durable actuals ledger, EUR pricing, live FX -- scoped Oct 8, 2026, NOT STARTED (deliberately behind automation work)

**Why:** costs live only in each job's job_meta.json, so the 7-day cleanup and the Jul 16 deletion erase them (Oct 8: all 17 jobs on disk are October, 12 have no cost_actual).

**Decided:** append-only ledger OUTSIDE jobs/ (date, job, provider, EUR, fx rate used), history before Oct 8 not reconstructed. fx.py with daily ECB rate (server reaches ECB: 1.1177 on Oct 8) replacing hardcoded rates (cost_tracker.py 0.92, listing_scraper.py 0.93, VPS 34.79/mo = $453.69 x 0.92 / 12). Luma direct priced flat $1.20 per 5s clip (tracker prices it as fal Ray 2: ~EUR 1.84 vs ~1.07 real). Google TTS is free tier, so ELEVENLABS_COST_PER_CHAR should be ~0.

**Open:** fal Usage by model (last 7 days) needed to reconcile; Anthropic Jul 3-10 purchase amounts not read.

**Time-sensitive, not code:** add a card in Anthropic Console billing (email Sep 11); ElevenLabs renews Oct 13 ($26.84).

## October 9, 2026 additions (scoped, NOT done unless stated)

### 58. AUTOMATION_TEST_PLAN.md -- reliability test plan for the Relinx/GIAL pilot (scoped, file not yet written)
Format as V2_TEST_PLAN.md (numbered steps, PASS/FAIL). Phase A: simulator script that plays Relinx (requests, duplicate external_ref, webhook receiver) against our API with a "fake provider" switch (OFF by default, env var, never in production). Phase B: a joint test window with Relinx, last week of October (~2-3 days, ~20 requests, ~EUR 350-400 real generation). Phase 1 before it: ~30 listings from >=6 agencies, ~10 of them hard (few/odd photos, long text, missing fields). Every test checks 4 invariants: no job lost; no double cost; final state correct and visible in the library; operator informed. Areas: restart/crash, providers (timeouts, 422), photos/listings, partner API, webhook, costs, queue/load, QC gates, operator/observability. Rework section: interrupt mid-batch, two sequential reworks of the same scene, rework while locked, rework cap reached, interruption during a QC-triggered redo, scene that keeps failing, cap reached mid-batch, single escalation notification, operator reset, 422 must not escalate to a pricier provider. Open: who runs Phase B on our side; Relinx's side contact; success criteria numbers for the pilot.

### 59. Rework hardening -- remaining work after stages 4/4b
(1) put the add-scene endpoint (run_redo_scene, ~line 2644) under the same gate or decide explicitly it is exempt; (2) Luma accepted-then-state=failed still cascades to Veo/LTX -- need real data to know if it means bad input or content block; (3) time cap per rework; (4) set PVS_REWORK_MAX_COST_EUR after backlog 57 (FX/Luma constants); (5) mention rework_incomplete in the startup notification; (6) unify clip/enhanced naming (scene_NNN vs <scene_id>, _lit) and drop duplicate clip copies; (7) third inline run_pipeline argument build (~line 1056) -> _pipeline_kwargs; (8) optional git rm --cached for the tracked file under clients/; (9) live check that a real QC-gated job now records cost.

### 60. Production readiness (open risks, no work started)
DPA/GDPR with providers and Relinx; legal check on labelling AI-generated video; domain + HTTPS; external uptime monitor; provider spend cap and balance alerts; bus factor (solo operator) -> handover tiers: operator (library banner, Riprendi, Risolto), technical (restart, logs, backups), decisions (Michele); remote operator handover Nov-Dec; checkpoint early December.

### 59 (update 2026-10-09, live findings from the first live test of the rework caps)
- A request whose scene ids are all invalid/filtered out (zero valid scenes) still counted as a rework round and ran a reassembly. Fix: gate and count only when the filtered redo list is non-empty; return a clear 400 otherwise.
- Test job zz_test_restart_1 used scene id `s1` (not the normal `sc_xxxxxxxx` format); the server regenerated ids (`_ensure_scene_ids`), so counters keyed on `s1` did not match. Check with a real job that the library edit view sends the true scene ids; if not, key the counters on a stable id that survives that step.
- UI: editing a past job showed 2 scene cards for a 1-scene job and the extra scene was saved into scenes_config (it has no clip; "Riprendi" on that job would generate it and cost ~EUR 1.1).
- UI: after a refused rework (HTTP 429) the "Progress 0% / Ferma questo job" panel stays visible although nothing started.
- Verified live 2026-10-09: refusal message shown in the edit view, library banner + 🛠 row with reason, "Risolto" confirmation dialog. Push/email count at refusal: to confirm.
- AUTOMATION_TEST_PLAN.md written (backlog 58): see that file for per-step status.

## October 9, 2026 -- decisions from the quality/test alignment (scoped, NOT built)

### 61. Video marking: replace the Property Video Studio logo watermark with a text-only "Generated with AI" label
Decision 2026-10-09 (Michele), corrected same day: the label text is ALWAYS English ("Generated with AI"), never localized, whatever the video language. Light grey text, NO shadow (Michele, later same day: a shadow could become a problem), same text style as the current watermark line, same position as the current watermark (bottom-left in today's videos; to confirm if Michele meant bottom-right), no icon/logo. Without a shadow the label can be hard to read on bright walls: the contrast check (Q31, F51) is the safeguard; if it fails, decide a darker grey or another position. We are white label: no Property Video Studio branding on partner videos. The agency logo arrives through the API (same mechanism as onboarding a new agency) and stays a separate optional element; how Relinx sends it (URL in the payload vs one-off upload per agency) is open, RELINX_QUESTIONS Q3. Consequence accepted: no brand advertising on videos (supersedes the earlier "watermark stays as advertising" decision for CRM partner videos). Constraints: legible on bright walls (shadow + contrast check, Q31, F51); applied on every scene and on the final video; check where the watermark is drawn today (watermark code and assembly) and whether a second copy of that logic exists (architecture discipline: search frontend/backend/manual/scraper/legacy before changing). Open: any Relinx legal requirement on the label. NOT built.
### 62. Language as a request parameter (design only; Italian is the only live language)
Decision 2026-10-09. Add `language` to the partner request and the manual flow (fallback: detect from the description). Impacts to design: TTS voice per language, narration prompt per language, number/unit/currency formatting, language-dependent quality thresholds (speech rate, number reading), captions. A language is "supported" only after its golden set of 10 listings passes and a native-level reviewer signs off (F52). No other language is switched on now. Check before building: where language is hard-coded today (narration engine, TTS, captions, UI), in all paths.

### 63. Risk scoreboard and update rule
Request 2026-10-09: monitor FMEA score and test score and update the control plan regularly, like status.md/backlog.md. Scope: move FMEA rows and the test catalogue to data files (CSV), one script generates AUTOMATION_TEST_PLAN.md tables and the scoreboard (total RPN, open ACT rows, open S>=9 rows, tests by status per level, requirement coverage), each review appends a dated scoreboard line. Add the update rule to the project's standing instructions (Michele pastes it into the Project settings; Claude cannot edit them). Until built, the scoreboard in the plan is updated by hand.

### 64. Automating light-bug handling (decision after the pilot)
Evaluate after the pilot with real finding frequencies. Ladder: (a) automatic logging, classification and linking of every Minor finding to its FMEA row; (b) automatic fix only for defects that are deterministic, reversible, low cost and verified by an automatic check (normalize loudness, re-encode, reassemble, regenerate voice only), always inside the rework caps and cost caps; (c) for recurring defects, Claude proposes a code change that Michele approves, with the golden set as regression test. Never automatic: anything touching content/facts, deploys, or data under jobs/. Open: which finding classes qualify, cost ceiling per auto-fix, who reviews the log.

### 58 (update 2026-10-09)
AUTOMATION_TEST_PLAN.md is now an E2E FMEA + control plan + V-model plan (53 failure modes). Companion documents: QUALITY_CRITERIA.md and RELINX_QUESTIONS.md. Reviewers decided: internal phase Michele + Relinx contact, pilot Michele + agency (GIAL). Questions to Relinx NOT yet sent: Michele wants to align internally first. Verified on the server 2026-10-09: GET /v1/videos/{id}, GET /v1/videos and GET /v1/videos/{id}/download exist and video_url uses https://api.propertyvideostudioai.com; contract tests still open.

### 65. Relinx communication package (prepared 2026-10-09, NOT yet sent by Michele)
Files in the repo: RELINX_QUESTIONS.md (short list: webhook HMAC signing, video_url lifetime, agency logo field, privacy/DPA, test dates), QUALITY_SPEC_FOR_RELINX.md (sent for information, not a question), DPA_DRAFT.md (draft between the parties; Michele is an individual supplier; needs a legal review and a check of the real provider terms and retention before sending). Assumptions recorded instead of questions: photos are high-resolution originals with reliable order/categories; the Relinx contact is the test referent; the AI label is always English. Test window: one agreed session running the written scenario protocol plus one reserve date (earlier "2-3 days" was only the 8 October proposal for volume/timing scenarios, to be shortened if the scenarios run in one session). Claude does not send email to Relinx; Michele sends.


### 66. URL-scraper automation for the pilot: standard 6-scene video, acceptance rule, photo choice (scoped 2026-10-12)
Decisions (Michele, 2026-10-12): standard video = 6 scenes / 30 s, one per environment (facade, living, kitchen, bedroom, bathroom, balcony/garden), no extra categories; with a second bathroom or bedroom pick the best. Rejection rule to test: fewer than 5 usable photos or fewer than 4 distinct environment types -> reject with an explained reason (the API must be able to communicate it). Narration opens and closes with the agency name and states sale/rent; captions removed for URL jobs; exterior-only listings rejected with a reason.
Done and verified: selection_report + source_description saved (0dcc5ad), shared photo fetch with fallback (0dcc5ad), truncated URL normalisation (0bdd62d), UI scene-card fixes (69c3af2 and the editJob sequence token, 2026-10-12).
Open: (1) 3B: fixed 6 scenes with speech band 24-28 s (standard only, premium unchanged), best-ranked photo per category with backfill, acceptance check before narration/TTS, failure code `insufficient_photos` plus Italian message; webhook and /v1/videos/{id} reason fields as a separate step after Michele informs Relinx; waiting for Michele's yes/no. (2) Classify each photo with Claude vision to remove the unstable page-read categories (F56). (3) Better facade/balcony choice (ranking criteria; entrance photo labelled exterior). (4) Package 2: one shared TTS/duration implementation (scraper `_measure_tts_duration` vs `narration.generate_narration_audio`, 22.3 s vs 29.5 s seen); decision pending. (5) Thumbnails "?" (empty File on failed image fetch), "Load failed" on Genera voiceover, scraper 400 message cleanup, agency-name extraction from the listing, server-side resync guard. Architecture discipline: before 3B and Package 2, search both paths (manual and scraper, UI and backend) for existing logic.


### 66 (update 2026-10-12, 3B built)
Built: fixed 6 scenes / 30 s for the standard video, speech band 24-28 s, acceptance rule before narration (>=5 usable photos and >=4 environment types), failure_code `insufficient_photos` with an Italian reason in the job and in the 422 reply (URL path). Unit-tested (26 tests); NOT yet run on real listings. Next: (a) re-run Via Giulia, Euclide and the other test listings and have Michele judge them; (b) list every rejection from the ~30 listings and tune thresholds only on that evidence (F60); (c) expose failure_code/failure_reason in the webhook and GET /v1/videos/{id} once Michele has told Relinx (separate step); (d) photo classification with Claude vision and facade/balcony choice remain open; (e) Package 2 remains undecided.


### 66 (update 2026-10-12, evening): photo classification by vision
Built: every photo of a URL listing is classified by Claude vision (see status.md 2026-10-12 evening). Next: (a) re-run Via Giulia and Euclide and have Michele judge; (b) repeatability check: run the same listing twice and compare the categories (F56 is closed only on that evidence); (c) if facade/balcony choice is still weak, improve the ranking prompt per category (exterior: clear building facade from the street, no corridor; outdoor: private balcony/terrace/garden); (d) cost: about one small Claude call per photo (up to 36 per listing), to be read from the job's Claude cost after the run.


### 66 (update 2026-10-12, measured classification)
Prompt v2 deployed after a 9-photo comparison (see status.md): page 3/9, vision v1 6/9, v2 7/9. Open: (a) review of Via Giulia and Euclide re-runs with v2 (6 chosen photos each); (b) more labelled photos from other listings (Michele labels, Claude adds them to eval_photo_categories.py); (c) consider a consensus rule (page label + vision) if v2 keeps missing kitchens/facades that the page labelled correctly; (d) repeatability: same listing twice.

Update 2026-10-12 (night) to item 66: photo categories = A+ (decision Michele). Interior labels from page/CRM are kept; only exterior/outdoor candidates are verified by Claude vision through one shared function (`refine_exterior_outdoor_with_vision`) used by the URL and the Relinx path; whole-listing vision removed. Selection = existing `select_photos_for_scene_count`. Open: review on the 5 test listings (Aurelio, Euclide, Giulia, Pinciano, Trigoria); facade labelled as an interior room is not detected; repeatability run; real Relinx API scenario test.


### 67. annunci.getrix.it as a listing source (2026-10-15, built; live run FAILED: 0 photos; adapter NOT built, one-off manual test used instead)
Requirement: the URL workflow accepts pages from annunci.getrix.it so a premium (~1 min) video can be made for a villa listed there (premium exists only in the URL workflow). Decisions: no site-specific adapter (one extraction path, architecture discipline); relative photo paths are made absolute at the single extraction point; the full-size `_hd` version replaces the `_th` thumbnail through the existing resolution-upgrade table. Open: (a) first real run: does the page reader return the photo paths, which version, how many; (b) the photos have no captions, so categories depend on the vision classification of uncategorised photos; (c) premium never run on a real listing (acceptance rule is not applied to premium); (d) agency name comes from the agency selected in the UI, so "Roma Immobili" must exist as an agency or the narration will not name it; (e) a paid job (about 12 clips) only after Michele and Claude have reviewed scenes and narration. Other portals stay refused until someone asks and a page is checked the same way.

Update 2026-10-15 (afternoon) to item 67: live run through the page reader gave 0 photos (it returns text without the relative photo paths). A direct-read route was prototyped but NOT deployed by decision of Michele (no industrialisation of this site). The villa was handled once, manually, with one Claude vision call on all 27 photos (see status.md); the experiment's result is the reusable asset: a photo-by-photo room/size/depth labelling plus an ordered premium sequence, judged very good on one listing.

### 68. Narration vs scene durations: one rule, measured not estimated (2026-10-15; manual workflow, URL/Relinx workflow and sync built, NOT run on a real generation)
Rule decided from Michele's observation: the blank 1 s + 1 s are added around the scenes, so scenes only need to cover the speech; extra seconds go to the last scene; Luma durations stay 5 or 9 s. Done in narration.py, api_server.py (`_overlay_narration_audio`), ui.html (same rule, one comment points to the other). Open: (a) the URL workflow still derives its scene count from speech + lead + trail (listing_scraper.py) and the per-scene voiceover estimate in ui.html is a third copy: decide with Michele whether to consolidate (touches the main URL path: note rollback commit first); (b) Michele asked whether buffers should be 1+1 s (current) or 2+2 s: one constant pair in narration.py, not decided; (c) a button/step "measure the real voice before generating anything" (tts_timing.py is the prototype, outside the repo) could replace word-count estimates in the UI; (d) first real generation with the new maths still to run. UPDATE 2026-10-15 evening (requirement confirmed by Michele): Luma scenes stay at 5 s ALWAYS (9 s removed from the UI slider and from the server's list: hallucination risk); the app never extends a Luma video. Instead narration.plan_sentence_sync() adds extra silence BEFORE a sentence so it starts on a scene cut when it would otherwise start up to 2 s before it (never moves a sentence earlier, never cuts audio); speech running past the last scene is absorbed by the trailing blank buffer up to 2 s, beyond that the app asks to shorten the text (with an approximate word count) and flags any sentence that opens a scene and spills over 2 s into the next. Tiers: only Luma uses this path (FIXED_SCENE_SECS_BY_TIER in narration.py); eco and Veo-backed tiers keep the old redistribution. Per-sentence timing is stored in job['narration_sync']. Still open: the URL workflow (listing_scraper.py) bakes silence into the audio and derives scenes from speech length, a different mechanism, NOT touched; ui.html keeps its own luma slider range (5/5) as a copy of the server constant; sentence-to-scene assignment is by timing only (no text-to-photo matching); first real generation with this logic not run. UPDATE 2026-10-15 (late evening, requirement confirmed by Michele): the URL and Relinx workflow (listing_scraper.generate_narration_and_derive_scenes, one function behind both endpoints) now use the SAME narration code as the manual one: sentence by sentence TTS with the normal pause (narration.synthesize_sentences / assemble_narration), no more single whole-text TTS call. Standard video: 6 fixed scenes, audio built already synchronised (pause added so a sentence that would start up to 2 s before a cut starts on it); speech band 26-32 s (scenes*5 minus 4 .. plus 2; it was 24-28 with the buffers counted twice), prompt asks for about 29 s / 68-78 words. Premium: measured plain first, scene count = ceil((speech-2)/5) within 11-13, then re-assembled for that count without a second TTS call (at most 13). Jobs now store narration_duration_secs = real speech length (it held the VIDEO length before, so the UI said 'ATTIVA (30s)') and narration_sync (per-sentence plan, null if the audio was trimmed afterwards). Correction of an earlier note: the URL flow no longer bakes silence into the audio (removed 2026-07-21); the real differences were the whole-text TTS, the buffers counted inside the scenes and the 24-28 s band. Still open: (a) premium 'tightening' step in generate_narration_and_derive_scenes trims the end of the speech (possibly the closing line) to save one scene whenever the speech needs more than 11 scenes: pre-existing, unchanged, to be reviewed with Michele; (b) the safety-net trim for a standard speech still above 32 s cuts at a natural pause and can drop the closing line; (c) sentence-to-scene matching is by timing only, not by what each sentence says; (d) the first real URL job with the new code is not run yet; (e) the voice starts when the first scene starts (the 1 s blank before it is NOT used by the speech, only the 1 s after the last scene is, as overflow): by design from 2026-07-21 (WhatsApp trims the first second of previews), to confirm with Michele whether a small early start is wanted.

### 69. Luma mirrors and bathroom camera (2026-10-15, rule built, not verified on a real clip)
Mirror rule added to `_LUMA_RULES` (people/figures/camera operator forbidden in any reflection). Open: verify on a real bathroom clip; consider a less rotating movement for small rooms with mirrors. Camera notes from Michele to turn into rules later: stairs should climb only a little; roofs/terraces seen from above should have a drone effect; facades should approach (enter) rather than pull away; hallway/stairs and facade/opening movements need their own treatment. Not started.
Update 2026-10-15 (night): Michele reported the shadow of the camera operator in a clip (rework requested and received). Rule `_NO_OPERATOR_TRACES` added once and used by BOTH `_LUMA_RULES` and `_VEO_RULES`: every shadow stays as in the photo, no new shadow, no shadow/silhouette/reflection of a photographer, camera operator, camera or tripod on floor, wall, ceiling, window or mirror (item 74, built, unit-tested at source level, NOT verified on a real clip). The same prompt is used by direct Luma, fal Ray 2 and Veo, so the wording cannot differ between them.

### 70. fal.ai still in use; USD 20 invoice (2026-10-15, CAUSE FOUND in the evening, fix built in item 74 -- not deployed)
Michele received a USD 20 fal invoice. fal is still called for: AI image upscaling (aura-sr), video upscale (Topaz) when enabled, vision captions (Florence-2 in vision_analysis), depth, watermark removal, and as fallback for Luma direct (Ray 2 via fal, USD 2 per 1080p 5 s clip) and Veo/LTX. Do not conclude the cause before reading fal's usage by model and the server log. Open: decide which of these to remove, and whether the villa draft script should send do_video_upscale=false.
**Cause found (2026-10-15, 21:30-22:00, from the server log, a screenshot of the Luma billing page and cost_tracker.py).** The direct Luma API answered `HTTP 402 RATE_LIMIT.BUDGET.EXCEEDED` (not enough credits) and generation switched silently to fal.ai Luma Ray 2 at 1080p, and for one clip on to Veo 3.1: in the log window since the 18:05 restart, 7 clips = 0 from direct Luma, 6 `luma-ray-2-fallback`, 1 `veo-3.1-fallback`. cost_tracker.py already documented that fal Ray 2 at 1080p costs USD 2.00 per 5 s clip (a 10-clip video = USD 20), against USD 1.20 per clip on the direct API (Luma billing page, 7 Oct 2026 lines). The invoice (USD 20, paid 15 Oct 18:48) is consistent with this; the 6 clips of job 83ca6568 plus its rework alone are about USD 14-15 at that rate, but the exact split of the invoice is NOT verified (fal dashboard 'usage by endpoint' not seen). Image upscaling is NOT the driver: 28 `[Enhance]` log lines (about 14 images, under USD 0.50). The older invoice may well have the same cause (not verified). Luma side: balance was about USD 0.40 before Michele's manual USD 10 top-up (21:39); auto-reload was ON but did not fire (threshold/amount to be checked in Luma > Billing > Auto-Reload > Configure; the error code says BUDGET, so a spend cap is also possible). Status: the silent switch is now visible and optional (item 74); the Luma account settings are Michele's to fix.


### 71. Camera movement and new environments requested by Michele (2026-10-15, scoped, NOT started)
Source: the villa premium test (Roma Immobili, released manually by Michele after his own camera/sequence adjustments) and his review of the clips. Extends item 52 (October 7 camera fixes, still not implemented: do them in the same pass, they touch the same tables) and item 69 (mirror rule).
Requests, in his words/intent:
1. **Stairs.** A new environment. The camera must climb only a little ("sali poco"); today stairs are labelled `hallway` (vision rules: "entrance hall, corridor, stairs landing") and get `walk_through` (a long forward dolly), which over-travels on stairs.
2. **Panoramic exteriors seen from above (roofs, roof terraces, wide terraces).** A new environment with a "drone effect". Today these fall under `elevated` (`step_out_onto`, a balcony-style outward move) or `outdoor` (`reveal_pullback`).
3. **Facades and entrances: the camera must move TOWARD the building (enter it), not away.** Today `outdoor` -> `reveal_pullback` is a reverse dolly (moves away, "reveals" the exterior) -- the opposite. In the standard video the facade is always scene 1, so this change affects every job, not only premium.
4. **Sequence feedback:** Michele started the premium video from the aerial/drone-like exterior and then the building (he swapped the first two scenes by hand); consistent with the opening rule "first = facade, else a different exterior" (item 66) but the ORDER between an aerial view and the facade is not yet decided as a rule.
Constraints and what already exists: one shared vocabulary, no parallel copies. The room labels live in `_ROOMS`/`_SIZES`/`_DEPTHS` (vision_analysis.py), the space->movement tables in `_SPACE_MAP`/`_MOVEMENT_MAP` (vision_analysis.py) and `SPACE_DEFAULT_MOVEMENT` + the movement prompt tables (video_generation.py), plus `SPACE_DEFAULT_MOVEMENT_MAP` in ui.html (already drifted: `approach_reveal` vs `subtle_rotate`, item 52). Any new environment must be added in all of them in one change, and the whole-listing vision prompt (select_test.py / villa_pick.py, outside the repo) derives movement from the same tables. Luma direct only accepts 5 s clips from an image; the 2026-10-08 lesson for `step_out_onto` (camera drifted back into the interior) shows that wording of the direction matters, so every new movement needs a real test clip (about USD 1.20 each) on real photos before it becomes a default.
Open questions for Michele: (a) are stairs and panoramic exterior new ROOM labels (visible in the UI and in the photo classification) or only new movements for existing labels; (b) for facades: straight approach, slight orbit, or approach with a rise; (c) what "drone effect" means in motion terms (slow rise, descent, orbit, forward flight); (d) test photos: the villa originals are kept in `/var/www/pvs_eval/villa_photos/`; (e) priority against the Relinx pilot: since the facade is scene 1 of every standard video, change its default only after an A/B on real facades.
Status: not started; nothing built. First step when picked up: one real test clip per new movement on 2-3 real photos each, reviewed by Michele, then the shared tables.

### 72. Reorder scenes on an existing job (2026-10-15, scoped, NOT started)
Asked by Michele: in the job screen the drag handle is missing; the existing drag and drop (ui.html `onDragStart/onDrop`, `.sc-drag-handle`) only exists in the photo upload form BEFORE a job is created. For the villa test the order had to be swapped from the terminal (`SWAP` variable in villa_job.py).
Scope: (1) draft job: allow drag in the job view and save the new order through the draft resync endpoint; (2) finished job: reordering does not need new clips, only a re-assembly, but it moves sentence/scene alignment so the narration sync (item 68) must be recalculated and the voice regenerated or re-padded. No cost for clips. Open: what happens to per-scene captions/overrides on reorder (follow the scene, as in the upload form), and whether reorder after generation is worth it versus swapping before generation. Status: not started.

### 73. Premium narration: scene-count tightening trims the speech (2026-10-15, found while reading the URL workflow, NOT started)
In listing_scraper.generate_narration_and_derive_scenes, after the scene count is derived, a 'tightest fit' step cuts the audio (at a natural pause) down to what fits one scene fewer. With the current arithmetic the speech that needs more than the minimum number of scenes always exceeds what one fewer scene holds, so the step runs every time and removes up to about 4.9 s from the END of the narration, where the closing line inviting the viewer to contact the agency usually is. Not introduced today (it existed with the old buffer maths), but premium videos are exposed to it. Options to decide with Michele: remove the step (accept a bit more trailing silence), keep it only when the cut stays inside the closing pause, or shorten via the model instead of cutting audio. Status: not started.


### 74. Silent fal.ai fallback made visible; clip preview after a rework (2026-10-15, DEPLOYED f690d99; live-checked 2026-10-22 on one rework; banner on a REAL fallback NOT verified)
Requirement (Michele, "metti avviso in rosso su UI se si usa FAL"): any clip made on fal.ai instead of the direct Luma API must be visible. Built, rollback point 7fdb7ba:
1. `generate_video_single` writes a sidecar `<clip>.mp4.model.json` (model, tier, fal_substitute, reason, time) after every successful clip (module `clip_provenance.py`, no fal import, never raises). `GET /jobs/{id}` now returns `fal_usage` (read-only summary: fal clips, scene numbers, models, reason, estimated USD on fal vs the direct price, level `fal` or `high` when Veo/LTX). No job state is changed.
2. ui.html: a red banner `#fal-warning` above the progress area, filled on every job fetch (poll and the three loads); plain text; names the scenes, the model, the reason (for example "Luma diretto: HTTP 402 - crediti o budget Luma esauriti") and the estimated cost.
3. `FAL_FALLBACK_ENABLED` in .env (default true = unchanged behaviour). `false` = on a direct Luma failure the clip stops with a clear error and NO fal call is made (same `return False` path as the existing bad-input stop). Michele chose to keep the fallback on for now; the switch is for later.
4. Prices defined once in cost_tracker.py (`LUMA_RAY2_FAL_USD_PER_CLIP` 2.00, `LUMA_DIRECT_USD_PER_CLIP` 1.20, Veo per second) and `clip_price_usd(model, secs)`; the job cost table now reads the same constants (values unchanged, tested). Job cost ACCOUNTING is not changed (see item 76).
5. Preview bug fixed: `/jobs/{id}/clip/{n}` always served `scene_NNN.mp4`, but a rework writes the new clip under its new scene_id, so the UI kept showing the OLD clip (found on job 83ca6568, Michele saw no preview of the reworked scene). Now one shared resolver (`clip_provenance.clip_file_for_scene`: scene_id file first, then legacy, the same order as run_reassemble_only).
6. Shared prompt rule for operator shadow/reflection (item 69 update).
Tests: test_clip_provenance.py 28 PASS; test_fake_video_cascade.py 13 PASS (V5-V8: 402 with fallback on writes the flagged sidecar; 402 with the switch off makes NO fal call and no file; a later direct success overwrites the note); test_prompt_rules.py R6-R7. NOT done: real clip, real 402, real UI look of the banner, a real rework preview. Pass criteria for the live check: a job generated while Luma direct is refused shows the red banner with the 402 reason; a rework preview shows the new clip.
Open: pre-existing clips have no sidecar (not counted); the jobs list does not show the banner (only the job screen).
Live check 2026-10-22 (job 83ca6568, rework of scene 6): sidecar says `luma-ray-3.2-direct`, `fal_substitute` false; clip written 07:07:52 UTC, final video reassembled 07:09:09, so the rework is in the video. Not verified live: the red banner on a real fallback (costs about USD 2 of fal credit; fake-provider tests only) and the browser preview (a rework changes nothing visible; file dates prove the video has it).

### 75. Job state coherence after a rework (2026-10-15, found on job 83ca6568; FIXED IN CODE 2026-10-22 with item 81, Patch C DEPLOYED 2041128 and restarted, NOT yet run on a real rework)
2026-10-22: a second rework of the same scene REUSED the scene id (`rework_counts: {sc_b774d3a0: 2}`, clip overwritten in place): the rework paths name the new clip differently. URL jobs keep their per-scene status list WITHOUT a scene_id; a rework looks the scene up by scene_id, does not find it, and APPENDS a new entry (job 83ca6568: `total_scenes` 6 but 7 status entries, entry 5 still `qc_verdict: reject`, entry 6 `pass` with the new id). `video_clip_paths` in job_meta.json also still lists the old scene_005.mp4 after a rework although the final video was reassembled from the new clip (verified: final 32.0 s = 6 clips + 2 s buffers; the config's scene 6 id is the new one). Effect today: cosmetic/confusing state, no wrong video. The preview symptom is fixed in item 74. Root cause found 2026-10-22: every first-generation status entry has `index` and NO `scene_id`, the three rework copies looked a scene up by `scene_id` only, so EVERY rework (not only the second) appended a twin entry for the same scene, and the library (`find(s.index === i)`) kept showing the first, stale one (`reject`). Fix (item 81): `scene_rework.update_scene_status` matches by scene_id, then by index, updates in place, sets the scene_id, and repairs twins already created by the old code; a successful video rework sets `qc_verdict` to `pass`. NOT changed: `video_clip_paths` is written only by the first generation and no code reads it back (checked by grep 2026-10-22: the reassembly reads the clip files by scene id), so it is left as is on purpose.

### 76. Cost model prices the luma tier at the fal Ray 2 rate for every clip (2026-10-15, found, NOT started)
cost_tracker prices tier `luma` at USD 2.00 per 5 s clip (EUR 1.84), the fal Ray 2 price, whether the clip came from direct Luma (USD 1.20 = about EUR 1.10) or from the fallback. So estimates and `cost_actual` over-state a normal direct clip by about 67% and are right only for fallback clips. Rework record of job 83ca6568 shows video EUR 1.84. Open decision for Michele: price each clip by the model that really made it (use the sidecar from item 74) - touches cost accounting, which had three duplicate implementations before (2026-07/21 session), so it needs a full sweep and his explicit go-ahead.

### 77. Narration written per scene for the standard URL/Relinx video (2026-10-22, "Patch B" DEPLOYED b5d2cdc and server restarted 2026-10-22 ~10:05; unit-tested; NOT yet run on a real job)
Requirement (Michele, "ok spec"): standard video = 6 scenes x 5 s, ONE fact-checked sentence per scene, written knowing the room each scene shows; still ONE continuous voice track (shared narration code), each sentence starting on its scene cut. Scene 1 = opening (agency, sale/rent, type, zone, 12-13 words); scene 2 = GENERAL facts (size, plot, levels, condition; works on any photo, the living room extends the facade); scenes 3-5 = the room shown, a detail only if the listing text states it; scene 6 = last space + closing naming the agency (up to 17 words, may use the 2 s trailing buffer). Price never spoken. Floors never named (a photo's floor is unknown); floors come with premium via the stairs scene (rooms before the stairs photo = lower floor, after = upper, assuming reliable photo order). One living-room scene only; a second one is a test question (more time = more cost).
Built: `scene_script.py` (prompt, parse, FACT CHECK, spill check); `listing_scraper._write_standard_scene_script` (2 Claude attempts, the second told why the first was rejected), `_tighten_scene_script` (one rewrite of ONLY sentences spoken >0.8 s past their scene, one more TTS, kept only if valid and not worse), `standard_scene_slots/standard_scene_sequence` (the ONE definition of scene -> category, also used by the scenes-config builder). URL and Relinx workflows now select the standard photos BEFORE the narration (always 6 scenes) and reuse that selection. Premium or no 6-scene sequence = single-text path unchanged. If the script is rejected twice or Claude fails, the job continues with the single text; the job stores `narration_mode` and `narration_script_fallback`.
Fact check (heuristic, not a proof): numbers and number words must be in the listing text; risky feature stems (piscina, giardino, terrazza, box ...) and promotional adjectives only if the listing uses them; no price (also numbers the listing ties to euro), no phone, no floor; sale/rent must match; agency in scenes 1 and 6; max 14 words (17 in scene 6); 6 sentences after the spoken split. It can reject good text (harmless fallback) and cannot catch a wrong claim in words outside its lists: a person listens to the first real jobs.
Tests (sandbox): test_scene_script.py 74 PASS, other 13 suites PASS. Deployed: apply block 489 on the server, 14 suites PASS there, commit b5d2cdc pushed, restart 490 OK (HTTP 200, `narration_mode` in the running code, no Traceback). NOT run: real Claude script, real TTS, real job (a draft job from a URL costs a few Claude/TTS calls, no Luma): this is the pass criterion. Rollback point f690d99.
Open: second living-room scene; premium (stairs, floors, 2 scenes per sentence, item 73); scrape structured features instead of free text; a stronger model than Haiku for this call if scripts are weak.


**Real test 2026-10-22 ~10:35 (draft job 4374ebc4 from the Immobiliare URL, Claude/TTS cost only) -- FAILED to use the per-scene script.** The fact check found NO fact error; the only problems were word counts: `scene 1: 16 words, maximum 14`, `scene 2: 16 words, maximum 14`, `scene 4: 15 words, maximum 14`, twice in a row (Haiku 4.5 does not count words). The job fell back to the single-text narration (`narration_mode` single_text, reason "rejected by the fact check twice"), whose sync is poor (sentence 1 spills 2.6 s into scene 2, sentence 2 spans scenes 2-4). Word count is only a proxy for seconds; the real check is the measured audio (spill + one tighten pass).
**Patch D (2026-10-22, built in the sandbox, NOT deployed, NOT run on a real job):** prompt targets lowered (opening/general AT MOST 12 words, room AT MOST 10, closing AT MOST 15) with the instruction to count words; `scene_script.SOFT_WORDS = 2` (validate rejects only above limit+2, message still says the base maximum); 3 Claude attempts instead of 2 (each retry is told why). test_scene_script.py 75 PASS (V5/V7 rewritten for the margin, O5b new, O6-O8 for 3 attempts). Pass criterion: a new draft from the same URL gives `narration_mode == "per_scene"`. If Haiku still fails, next step is a stronger model for the script only (cost to be agreed).
**Patch D deployed 5443fa0 (restart ~10:55). Second real test, draft a7e7ef2b: STILL single_text.** The word-count problem is gone; the new rejection (3 times) was `the text splits into 5 sentences instead of 6 when it is spoken`: the spoken-sentence splitter (narration.split_into_sentences) only splits at . ! ? followed by a capital letter, so a sentence with no final stop, ending in ; or :, or starting with a digit is merged with its neighbour. The old message did not say which sentence. **Patch E (built, NOT deployed):** `parse()` adds the missing final stop (also replaces a trailing ; : ,), validate names the sentence that does not start with a capital letter, and each rejected attempt now logs the problems AND the sentences, so the next failure is diagnosable. test_scene_script 78 PASS (sandbox). Pass criterion unchanged.
**Patch E deployed befc2ae (restart ~11:07). Third real test, draft 32245700: `narration_mode == per_scene`, no fallback (2026-10-22 11:08, Claude/TTS cost only, ~EUR 0.05 Claude).** Six sentences, one TTS pass, no warnings, speech ends 30.74 s. BUT the sync is not clean: sentence 1 ends 5.98 s (0.98 s past its scene), sentence 2 starts 6.36 s and ends 12.21 s (2.21 s past scene 2, into scene 3). Both are above the 0.8 s spill tolerance, so the tighten pass should have run; the log shows no trace (the old code returned None silently when the rewrite was rejected). **Patch F (built, NOT deployed):** log only, no behaviour change: why the rewrite is unusable (not 6 sentences / changed a protected sentence / fails the fact check) and the outcome of the second measurement. Open question until the next run: did the rewrite fail, or was it measured and judged not better?
**Patch F deployed 20ca01d (restart ~11:17). Fourth real test, draft c75f022c: per_scene again (attempt 1 rejected for 'scene 6: contains more than one sentence', attempt 2 accepted). Cause of the missing tightening FOUND from the new log:** the rewrite WAS received (sentences too long [(0, 0.81), (1, 1.64)]) but it dropped 'in vendita' from sentence 1, so the fact check rejected it (correctly) and the first script was kept. **Patch G (built, NOT deployed):** the tighten prompt now carries MUST-KEEP rules (sentence 1 keeps in vendita/in affitto and the agency name, sentence 6 keeps the agency name and the invitation to contact). test_scene_script 79 PASS (sandbox). **Michele's requirement (2026-10-22 11:13, to be handled AFTER this development cycle):** be more flexible with sentence length; 5 s per scene is too tight to describe a room. Review the 'one sentence = one 5 s scene' model (sentences spanning scenes? more or fewer scenes than sentences? longer clips?) before further tuning limits.
**Patch G deployed 21572d8 (restart ~11:25). Fifth real test, draft 6e3d0d40: per_scene (attempt 1 rejected: 'scene 6: contains more than one sentence'). Tighten pass now ran and the rewrite KEPT 'in vendita' (Patch G works) but was rejected because Claude also shortened the unflagged sentence 6.** Result kept: first script, sync 1.5 / 2.67 / 1.19 s over. **Structural finding for the requirements review:** because sentence 2 ends at 12.67 s, sentence 3 (the kitchen sentence) starts at 15.0 s = scene 4 (bedrooms): text and image are out of step by a whole scene; the voice talks about the kitchen over the bedroom clip. This is the cost of 'one sentence = one 5 s scene' with natural speech of 4-6 s per sentence. **Patch H (built in sandbox, NEVER deployed, WITHDRAWN 2026-10-23, superseded by item 82):** an unflagged sentence may change in the tighten rewrite if it only gets shorter (cannot worsen the sync; the audio is re-measured and the rewrite is adopted only if no worse). test_scene_script 80 PASS (sandbox). Expected effect: the tighten pass can finally be adopted; still a patch on the model, not a fix of it.
### 82. Sentence-driven timeline: the voice decides the length of each scene (2026-10-23, requested by Michele; Patch I = calculation only, Patch J = wiring NOT started)
**Why:** the fixed 5 s per scene model is wrong (natural sentences are 4-6.5 s; kitchen text over the bedroom clip) and the old sync ignored the 0.5 s cross-fade between clips (`video_assembly` overlaps clips by `TRANSITION_DURATION` = 0.5 s, so scene k starts k x 0.5 s earlier than the 5 s grid says: voice late by 0.5 s at scene 2 up to 2.5 s at scene 6; also overflow was computed against 30 s instead of 27.5 s). Michele: "questo ritardo di 2,5 s spiega molti fallimenti di sincronia visti in passato". NOT yet confirmed on a finished video (hypothesis from the code).
**Decisions (Michele, 2026-10-23):** (1) the voice stays ONE track; (2) text = one sentence per scene, or one sentence over two consecutive scenes (Claude decides, max two such per video, default one per scene); (3) each sentence decides its scene length; each ~5 s Luma clip is sped up/slowed to its slot, speed limits 0.8-1.25 (0.8x watched, imperceptible); (4) NO hard cuts (a 4 s cut showed a white flash; luminosity data flat, probably player artefact, to re-check on an assembled video) and NO 10 s Luma clips (fear of hallucinations); (5) Plan B: if a sentence still does not fit after slowing, a 7th 5 s clip (extra photo of the same room, ~USD 1.20) may be added, ONLY after asking Michele; (6) total video 24-36 s accepted; (7) the voice may run over the cross-fade, but the sync calculation MUST account for the overlap; (8) durations come from the REAL measured mp3 (pydub), not from estimates; (9) new behaviour only for the URL/Relinx standard video, flagged in the job; the manual workflow (per-scene voiceover, `clip_seconds_for_audio`) stays unchanged unless Michele decides otherwise.
**Patch I (built, calculation only, NOT wired to any job, no behaviour change):** `scene_timing.py` (`plan_timeline`: sentence lengths + groups + source clip lengths -> per clip start/duration/speed, per sentence voice start, silence `gaps_ms` before each sentence, problems list; model: sentence starts exactly on the cut = middle of the overlap; pause 380 ms shrinks to >=100 ms near the slow limit; short sentences get extra silence so the clip is not sped above 1.25; too-long sentence reported, plan stays exact). `narration.assemble_narration(..., gaps_ms=)` optional, default behaviour unchanged. `test_scene_timing.py` 36 PASS (sandbox, stub audio).
**Michele's refinement (2026-10-23, after Patch I was deployed, fe50448):** the requirement is NOT "one sentence per scene" but "when the voice NAMES a room, that room is on screen" (words synchronised with scenes, sentences free). Not every room has to be named (no time in a standard video), but when one is named, especially with a special feature, it is named at the right moment. "Poi raffiniamo le regole vedendo i risultati dei test."
**Word timing test (server, 2026-10-23, job 6e3d0d40 narration.mp3, 30.42 s):** local `faster-whisper` ("small", CPU, int8) gives a start/end for every word: 59 words, 7.7 s to listen, model loads in 1.6 s, cost zero, last word ends 30.26 s. Spelling is NOT trusted (parquet->"parche", quadro->"quadri"): the recognised words are aligned to the known text and only their times are used. The installed `av` is too old for faster-whisper's own file reader (TypeError `metadata_errors`): the audio is decoded with pydub and handed over as an array (no upgrade of `av`, which could break other things). ElevenLabs timestamps were NOT needed (ElevenLabs is also to be dropped for cost); Claude cannot listen to audio, the recogniser does.
**Simulation on the real timings of 6e3d0d40 (no cost):** that text (written for 5 s grids) would give 4 of 5 scenes outside the 0.8-1.25 speed limits (rooms 2.4 s apart, 8 s of property data before the first room). Allowed spacing between two room phrases (middle clip): 3.5-5.75 s = about 9-14 words. The method works, the old text did not follow the rule.
**Patch J (built in sandbox, NOT yet deployed, OFF by default):**
- 2026-10-23 UPDATE: Patch J deployed (fb3b876), flag ON. First real draft (312b283b) fell back (see status.md): prompt asked word positions an LLM cannot count, opening too long, two rooms in one sentence, retry blind to its own text. Patch K (sandbox only) changes the prompt to one natural flow with a duration requirement (28 s target, 32 s max, 56-66 words, hard limit 72, short opening, a room about every 11 words) and objective positive adjectives when supported by the listing. OPEN (requested 2026-10-23): adjectives derived from the PHOTO analysis (luminoso, elegante, funzionale from what the picture shows) need a new vision pass per selected photo (~6 small calls per job) feeding the narration prompt and the fact check: scope and cost to be decided, shows the previous text on retry, logs words/seconds/pace/text. Still to verify on the server: a draft that is NOT a fallback, then a real generation watched and listened to. Open: real words/s of the voice (to be read from the new log line).
- 2026-10-23 UPDATE (afternoon): Patch K deployed (b5c9a08); Patch L deployed (128ac4d): L1 text-level timing check before TTS/Whisper (`scene_script.estimate_timing_problems`, same solver, 2.2 words/s, tolerance 1.0 s) - worked on the first real draft (2320769d: two texts rejected without paying voice). L2 (job stub) still gave "Load failed" because reading the listing + vision + acceptance take ~3 min inside the request, and Michele does not want a job per refused listing. Patch M (sandbox, NOT deployed): preparation TICKETS in memory (`INTAKES`) instead of jobs; everything after the quick checks runs in the background; the job + folder are created only at the end; refused/failed = ticket only; last-room rule explained to the model (at most ~11-12 words after the first word of the last room, invitation <= 7 words); 3 attempts. Open: photo-derived adjectives (vision pass) unscoped; per-job Claude cost counter (process-wide today); tickets are lost at a restart (accepted); the textual reasons of refused listings are only visible in the page message and the log.
- 2026-10-23 UPDATE (evening): Patch M deployed (0fa06b8): tickets worked (one job only). Draft 6cb22349 still fell back: the estimate used all 3 attempts before any measured feedback. Patch N (sandbox, NOT deployed): estimate 2.05 words/s + tolerance 0.5 s, prompt rule against rooms named back to back, 7 Claude calls / 3 voiced texts / 2 estimate-only retries so the measured retry actually happens. Open: still needs a real run; if it keeps failing, next candidate is a deterministic text skeleton (fixed word budget per room) instead of free LLM text.
- 2026-10-23 UPDATE (night): Patch N deployed; draft d0492ebb still per_scene (5 rooms in 28 s do not fit). DECISION (Michele): name only 2-3 highlight rooms, not all. Patch O (sandbox, NOT deployed): `MAX_ANCHORS = 3` hard rule + prompt with highlight positions per scene. Open: real-listing verification; photo-derived adjectives still undecided.
- 2026-10-24 UPDATE: Patch O real result = still fallback (8e4856b8). DECISION (Michele): video leads, voice adapts (dubbing logic); freeze-frame/zoom unacceptable; levers = pause between blocks, tempo, plan B clip speed. Patch Q (sandbox, NOT deployed, rollback 86e51ff): 3 narration blocks of 2 scenes fitted to fixed 5 s clips. Open: real audio test of stretch_audio/assemble_blocks on the server, ONE real draft from the San Saba listing, then removal of superseded anchored code (_anchored_narration, build_anchored_prompt, estimate_timing_problems, MAX_ANCHORS, plan_timeline/gaps_ms).
- 2026-10-24 UPDATE (evening): Patch Q deployed (5c085eb): first non-fallback draft 41ae5a44, but sync wrong INSIDE blocks (topics out of order). Patch R (sandbox, NOT deployed): 2 sentences per block, one per scene, room named by its own sentence, silence between the two sentences puts sentence 2 on its cut, 5 anchors. Open from Michele (2026-10-24): (a) QC "still wrong, was it updated with Claude?" (to clarify which QC), (b) camera movement per environment in the standard video (item 71/52 not started), (c) odd pause between "metri" and "quadri" in the TTS (not investigated), (d) remove superseded anchored code after Patch R is verified.
- `scene_timing.plan_from_anchors`: ONE calculation. Anchors = time of the first word of the phrase that names a room. Preferred cut = word start - 0.35 s (picture fully visible just before the word); a cut may fall 1.0 s earlier or 0.4 s later; unnamed scenes take the space in between; all cuts are solved exactly (interval propagation) so every clip stays inside 0.8-1.25 or the plan is reported as impossible with seconds over; the video may extend up to 8 s past the voice if the text is short. Cross-fade overlap = `scene_timing.TRANSITION_SECS`, which `video_assembly` now IMPORTS (its own copy `TRANSITION_DURATION = 0.5` is gone).
- `word_align.py` (known text <-> recognised words, interpolation for mis-heard words, phrase finder), `word_timing.py` (faster-whisper wrapper, never raises, returns None -> fallback), `scene_script.build_anchored_prompt / parse_anchored / validate_free_text / build_anchor_feedback`; the per-sentence fact check was extracted into `_fact_problems` and is now used by BOTH `validate` (per-scene script) and `validate_free_text` (no duplicate).
- `listing_scraper._anchored_narration` (max 2 Claude attempts; after TTS + word timing the plan is calculated; if it is outside the limits the model is told in seconds/words what to change; any failure -> the previous modes, reason in `timeline_fallback_reason`). Switch: env `PVS_ANCHORED_TIMELINE=1` in `.env` + restart; default OFF; standard 6-scene only (premium and manual unchanged).
- Job stores `timeline` (mode anchored, targets per clip, cuts, speeds, anchors, offsets, coverage) and `timeline_fallback`, in BOTH job creators (URL and Relinx). `run_reassemble_only` (the ONE assembly path) passes `scene_target_secs` only when targets == scenes == clips; `assemble_property_video` applies `MultiplySpeed(final_duration=target)` per clip (nothing cut). Regenerating the narration clears `timeline`.
- Tests (sandbox): `test_anchor_timeline.py` 73 PASS (includes the real Whisper output of 6e3d0d40 as fixture and a 300-case random property test: no valid timeline is ever reported impossible); all other suites unchanged and passing. NOT tested in the sandbox: moviepy `MultiplySpeed` on a real clip, faster-whisper in the job flow, a real Luma video: server tests after deploy.
- Unused code kept on purpose, to decide later: `scene_timing.plan_timeline` and `narration.assemble_narration(gaps_ms=)` (Patch I, sentence-driven) are not called by production; remove or keep once the anchor method is proven.
- Found while reading `assemble_property_video`: the "+1 s tail on the last scene" (`if i == len(clips) - 1`) can never be true (it is evaluated before the clip is appended); dead code, left untouched.
- Known limits: if the user edits the scenes (adds/removes/reorders) the timeline is not applied (count check) or no longer matches the text; a rework of one scene keeps its slot (speed is recomputed from the real clip length); no automatic 7th clip (plan B still needs Michele's confirmation, not built).
**Rollback point:** production HEAD 21572d8 (Patch G).
### 78. Luma billing safeguards (2026-10-15, found, NOT started)
Luma balance reached about USD 0.40 with auto-reload ON but not firing (threshold/amount unknown, set in Luma > Billing > Auto-Reload > Configure; error code was BUDGET.EXCEEDED so check a spend cap too). Sizing: one standard video = 6 clips = USD 7.20 on direct Luma, so about 30 test listings = about USD 216. Proposed (not built): a Luma balance check like credit_monitor.py does for fal, with an alert below a threshold; set the auto-reload threshold to at least USD 10 and the amount to USD 20-30 before the Immobiliare batch.

### 79. kie.ai price comparison (2026-10-16, research only, NOT adopted, no code changed)
No Luma Ray on kie.ai (our main path has no equivalent). Veo 3.1 Fast 1080p USD 0.325 per video (our assumed fal cost about 0.50 per 5 s, from cost_tracker, not re-checked: about 35% cheaper); Veo 3.1 Quality 1.275 (assumed fal about 1.00: dearer); Veo Lite 0.175. Other looks (need a side-by-side test): Kling 3.0 about 0.07 per second, Seedance 2.5 0.085, Wan 3.0 0.04. ElevenLabs/Topaz named without price. Risks: reseller, no SLA, its own review says stability can lag first-party APIs, media kept about 14 days, HTTP 429 not queued, community support, failed jobs said to be free (confirm). The review is an affiliate article; tracker data 2026-08-05. Idea, not decided: kie.ai Veo Fast as the CHEAP fallback instead of fal Luma Ray 2 (USD 2.00 per clip); different look, banner must say so; needs a test clip, their refund/retention terms and Michele's go-ahead.

### 80. Hostinger VPS checks (2026-10-22)
Hostinger PHP-vulnerability e-mail: the server has no PHP (nginx is active, unrelated): nothing to do. Malware Scanner active and clean (89,352 files, 0 malicious); "Automatic malware removal" stays INACTIVE on purpose (a false positive could quarantine files under jobs/). Hostinger keeps weekly snapshots; our nightly jobs backup is on the SAME disk, so it does not cover a lost disk/VPS; the USD 12/month daily-backup upgrade is to reconsider before production use for Relinx. Firewall has 6 rules; ports 8001-8003 still to close (existing item).

### 81. ONE rework engine instead of three copies (2026-10-22, requested by Michele "B, piu' solido"; Patch C DEPLOYED 2041128, server restarted 2026-10-22 ~10:35, unit-tested, NOT yet run on a real rework)
Problem (architecture discipline): `run_redo_scene`, `run_redo_scenes_batch` and `run_redo_audio_only` repeated the same steps (voiceover, clip length, source photo with legacy-name migration, enhance, clip, scene status, cost record) and the first generation and the narration endpoint repeated pieces of them. Real drift found by reading, not only by values: (1) scene status looked up by scene_id while first-generation entries only have `index` -> twin entries and a stale `reject` (item 75); (2) clip length after a rework used 4-8 s rounded UP, the first generation uses 6-20 s rounded to nearest, so a scene whose voiceover needs 12 s got an 8 s clip back (only scenes with their OWN voiceover, i.e. manual jobs; URL/Relinx jobs use one continuous track and are not affected); (3) the "fold the rework into cost_actual" block existed 4 times (3 runners + the narration endpoint); (4) `run_redo_scene` (used when a scene is added) had no rework-budget bookkeeping and failed the job on a bad clip, the batch skipped the scene and reported it: two behaviours for one job.
Built: `scene_rework.py` (pure, all outside calls injected): `clip_seconds_for_audio` (the single clip-length rule, now also used by the first generation, identical result for every audio length 0.1-39.9 s, tested), `find_source_image`, `update_scene_status`, `record_rework_cost` (used by the three runners AND the narration endpoint), `redo_scenes` (the engine). In `api_server.py`: `_run_redo` is the ONE runner (lock release, budget count/begin/end, reassembly once, `_rework_after`), `run_redo_scene` / `run_redo_scenes_batch` / `run_redo_audio_only` are 1-line wrappers. Behaviour kept on purpose: add-scene stays strict (a failed clip fails the job, no budget count), batch and audio-only skip and report, audio-only never touches video, URL/Relinx scenes (no per-scene voiceover) make no TTS call.
CHANGED on purpose, for Michele to veto: rework clip length for scenes with their own voiceover now follows the first-generation rule (6-20 s) instead of 4-8 s: a rework can cost more than before for a long voiceover (longer clip) but no longer cuts the voiceover. A successful video rework sets the scene's `qc_verdict` to `pass` (before: left the stale `reject`).
Tests (sandbox, no network): test_scene_rework.py 65 PASS (clip rule vs the old first-generation rule for 399 audio lengths; cost record identical to the old block for 4 tiers x with/without `cost_actual_raw`; engine with fake TTS/video for URL-style, voiceover, batch with failures, strict, audio-only; twin repair; source checks and an undefined-name check on api_server.py); the 14 earlier suites PASS. NOT possible in the sandbox: importing api_server.py (no fastapi), so the wrappers are checked by reading the source and by a name check, not by running them. NOT run: a real rework on the server. `test_batch_redo.py` is a live integration test that spends real Luma/ElevenLabs money: not run, not part of the apply block.
Verification still to do (after deploy): one real rework of ONE scene on a finished job (cost about USD 1.20 on direct Luma): same scene count in the job's status list, scene no longer `reject`, `cost_actual` grew by the expected amount, final video reassembled. Rollback point: b5d2cdc.
Open: item 76 (price per real model) stays separate on purpose (cost accounting, needs Michele's go-ahead); `video_clip_paths` left as is (written only, never read; see item 75).


### 83. Standard video: camera movement and QC fixes requested by Michele (2026-10-25, scoped, NOT started)
Requirements, in his words/intent (confirm in plain language before any code; each new movement needs a real test clip, about USD 1.20 each, reviewed by Michele):
1. **Facade (scene 1 of every standard video): the camera must APPROACH the building, not move away.** Today outdoor -> `reveal_pullback` is a reverse dolly (item 71 point 3). Shared tables to change in one pass: `_SPACE_MAP`/`_MOVEMENT_MAP` (vision_analysis.py), `SPACE_DEFAULT_MOVEMENT` + the movement prompt tables (video_generation.py), `SPACE_DEFAULT_MOVEMENT_MAP` in ui.html (already drifted, item 52).
2. **Garden / balcony: the camera must look toward the landscape / the open view, not point at an object such as a column** (the wording of the outward direction matters, see the 2026-10-08 `step_out_onto` lesson, item 52.3).
3. **Remove reflections in mirrors and shadows** (the mirror/operator-shadow rule of items 69 and 74 point 6 exists; Michele says reflections and shadows still appear: find which clips and whether the rule reaches the standard URL path).
4. Stairs and the drone effect on roofs: PREMIUM only, later (item 71 points 1-2).
5. **Per-scene video QC is wrong in two ways (Michele 2026-10-25):** (a) it reports an INTERIOR in a clip when an exterior had already been correctly selected; (b) it reports hallucination when there is none. Open: which QC code and prompt produces these verdicts (Claude vision? Florence? a separate check?), whether it was ever updated to use Claude vision (item 11, "Agent-based final video QC"), and the false-positive rate on the existing clips (a labelled sample from Michele would be needed). Nothing investigated yet.

- 2026-10-25 UPDATE (afternoon): Patch R2 deployed (14a6e4f) but the first real draft (dd4d2b79) fell back to per_scene after 6 attempts (see status.md: false room hit on "servizi", closing block 0.365 s too long, non-JSON reply erased the feedback). Patch R3 (sandbox, 59/59, not deployed) fixes the feedback loss and the "servizi" keyword. Item 83 (QC + camera): QC finding from job 41ae5a44 (full job with video): the per-scene QC is NOT Claude - it captions first/last frame with Florence-2 and matches keywords. Scene 5 balcony rejected as "interior" (frame classed interior from words like walkway/brick wall although the space type was already outdoor/elevated); scene 2 kitchen flagged "structural hallucination" although stored first-frame captions of photo and video contain no keyword (the hit was in the last frame, whose caption is not stored); scene 3 had a REAL change (double bed -> two single beds, sliding door -> door with handle) that the QC passed. Proposed (awaiting Michele's confirmation): Claude vision compares photo + first + last frame, JSON verdict, never overrides the known space type, stores both captions; first tested read-only on existing clips (no new Luma).

- 2026-10-25 UPDATE (evening): Patch R3 deployed (01475ca); draft 633d3f36 = first real success of sentence-level block sync (details in status.md). Open decision (Michele): real generation of 633d3f36 now (~USD 7-8) vs first apply camera/QC changes of item 83 and generate once. A "reuse clips from another job" tool was considered (would save ~USD 6 on a test) but it touches job state/cost and the old clips carry the old camera prompts: not built, needs Michele's confirmation. Item 83 QC: stored captions must include BOTH first and last frame; the QC must never override the known space type.

- 2026-10-25 UPDATE (night): Michele approved the robustness test plan (levels A offline/failure injection, B battery of 15-20 real-listing drafts (cents, no Luma), C zero-cost renders with automatic audio-vs-cut check, D his review of 5 videos, E one real end-to-end ~USD 7-8 after camera/QC, F regression/duplicate sweep; gates: >=90% non-fallback within 6 attempts, median <=3, 0 room violations, drift <=0.3 s, review >=4) and the QC-with-Claude and camera requirements of item 83 exactly as written (facade = straight approach; garden/balcony = outward, eyes on the landscape; first 2 test clips on the San Saba photos 0 and 5, ~USD 2.40 per round, reviewed by him before any default changes). FLUIDITY idea (his feedback: repeated pauses make the voice less fluid): the second sentence of every block is anchored at a fixed time, so the voice waits up to 1.5 s; anchor only the sentences that name a room (max 3) and let the others flow; needs design, after QC and camera. Patch R4 (sandbox): closing invitation as its own sentence + light preview copy.

- 2026-10-25 UPDATE (night, QC): item 83 point 5 BUILT in the sandbox (see status.md "Clip QC with Claude"), not deployed. To do after deploy: (1) run `python3 qc_validate.py 41ae5a44 bd3f0f77 83ca6568` (read-only) and compare old vs new verdicts with Michele's labels: scene 2 kitchen of 41ae5a44 should pass, scene 5 balcony should pass, scene 3 bedroom (double bed -> two single beds) should be reject/flag; (2) measure the real Claude cost per clip and decide the cost accounting (estimate in cost_tracker.py still Florence-based, actual cost does not include the QC calls); (3) decide whether Haiku is accurate enough or the QC needs a stronger model.

- 2026-10-25 R5 (details in status.md): remove superseded `scene_timing.plan_blocks` (+ BLOCK_*/END_* windows) after R5 is verified on real drafts. Open: if the real battery shows the last clip at the 0.8 floor often, widen the lever (tempo up to 1.15 for the last block only) or lower the last-sentence budget; keep the best attempt (not only the last) if single failures persist; feed the REAL sentence-length distribution (battery) back into test_block_robustness.py. Level B of the test plan: 15 immobiliare.it URLs received 2026-10-25 (stored in AUTOMATION_TEST_PLAN.md).

- 2026-10-25 QC v2 (Patch X): validate prompt v2 and models on the labelled clips: 41ae5a44 s3 = defect (must be flag/reject), s2 and s5 = clean (pass), 83ca6568 s5 = shadow (reject), s1/s2 = clean (pass). Need MORE labelled clips (Michele to label from the library) before trusting any model. Then set the default QC model and the estimate constant.
- 2026-10-25 duplicates found: `USD_TO_EUR` is 0.93 in listing_scraper.py and 0.92 in cost_tracker.py (same concept, two values): consolidate (touches every cost figure: needs Michele's go-ahead).
- 2026-10-25 spoken length: the block planner counts WRITTEN words (2.1 words/s) while numbers/abbreviations are spoken longer ("mq. 60" = "metri quadri sessanta"); measure on the URL battery and estimate in spoken words (expand digits/abbreviations) in the last-sentence budget and prompt.
- 2026-10-25 whole project still on Haiku 4.5 (claude-haiku-4-5-20251001); Haiku 5.5 is priced 10x lower per token: test narration/JSON compliance on the battery before changing `listing_scraper.MODEL`.

## 2026-10-25 - Spoken units / abbreviations (Patch Y, sandbox-tested, not deployed)
- Done in Patch Y: "mq"/"m2"/"m²"/"metri quadrati" -> "metri quadri" in `voice_generation.spoken_units` plus `scene_script.NUMBERS_RULE`.
- Open: (a) expand other abbreviations/numbers the same way (c.a., P.T., ordinals, "3000" read as a number) in the same function; (b) make the sentence-length estimate count spoken words (uses the same expansion) so the last-sentence budget is accurate; (c) check on a real draft that no pause appears after the unit.

- 2026-10-25 (late) CORRECTION: the labelled set of the QC item above was wrong for 41ae5a44 s3 (it is one bed reflected in a mirror, NOT a defect). Corrected labels: 41ae5a44 s0-s5 all clean; 83ca6568 s0 = invented street (real defect), s5 = shadow (real), s1-s4 clean. Next: apply Patch Z (mirror rule, max_tokens 1200), re-run the 3-model comparison, then decide the default model (data so far favours Sonnet 5.5 for fewer false rejects; cost about EUR 0.054 per video) and update CLIP_QC_EST_EUR_PER_CLIP. Candidate (not built): Haiku first, Sonnet only as second opinion on flag/reject. Need more labelled clips from Michele, especially REAL defects (only 2 so far).

- 2026-10-25 (late) DECISION: QC model = Sonnet 5.5 (Patch AA). Open: re-measure false reject/flag rate on the first real jobs; collect more REAL defect clips (only 2 labelled); consider Haiku 5.5 (about 12x cheaper) once its answers are reliably valid (needs max_tokens > 1200 or shorter inventory).

## 2026-10-26 - Camera + mirror plan (approved by Michele, test round approved) and narration language check
- Camera plan: (1) facade -> `approach_facade`; (2) garden/pool/courtyard (room garden, pool, other_exterior) -> `outward_view`, balcony/terrace -> `outward_view` instead of step_out_onto; (3) mirror/large glass facing the camera -> almost static `subtle_rotate` + `_LUMA_MIRROR_RULE`. Adopt (change defaults in ONE table, derived everywhere) only after Michele reviews the 3 test clips (camera_test_clips.py --go, ~USD 3.60/round). Open: movement per ROOM (facade vs garden), today both map to space `outdoor` -> `reveal_pullback`.
- Mirror recognition in the photo analysis (ROOM_PROMPT): add `reflective_surface: none|small|large` (mirror, mirrored wardrobe, glass door seen frontally); a mirror counts as a flat wall for depth, never as another room; pass the value to the Luma prompt and to the QC as known context. Not built.
- Consolidate the 3 movement tables into one source (video_generation.SPACE_DEFAULT_MOVEMENT) with a test that the UI mirror equals it. Not built (needs Michele's go-ahead for touching the shared path).
- PROPOSED (needs Michele's OK, not built): narration language check inside the generation loop: after validate_blocks passes, one cheap Claude call (Haiku) lists misspelled/ungrammatical Italian words with the fix; any finding goes back to the model as feedback like the room-word check (so timing is recomputed). Optional deterministic second layer: Italian dictionary check. Alternative: Sonnet for the narration (about 7x the narration cost).

- 2026-10-26 Patch AC (language check) built in the sandbox, see status.md. To do after deploy: (1) run the read-only validator on the stored narrations of the last drafts (expect "garantono" flagged on 7ff8ec4b, measure false positives on the others); (2) after the next real drafts, look at the log lines "Italian check:" to see how often it fires; (3) optional second layer: a deterministic Italian dictionary check; (4) re-check the rewrites of the single-text correction pass and the tighten pass.


### 2026-10-26 (sera) - Patch AD: Italian check now finds unknown words with a dictionary (replaces the detection of Patch AC)
- MEASURED on the server with real texts (blocks 114-118): the whole-text proofreader of Patch AC did NOT find "garantono" in draft 7ff8ec4b, with Haiku 4.5 (also proposed a wrong "contatta"->"contattare" on c4cbba23) and with Sonnet 5.5 (no error reported on any of 10 texts). Cause 1: the parser rejected a reply that showed two JSON blocks (checked=False on 7ff8ec4b). Cause 2 (the real one): asking a model to find a typo in a fluent text does not work.
- Fix: pyspellchecker (Italian, 120k words, new line in requirements.txt) lists the words it does not know (7ff8ec4b: abitativa, contatta, dotazioni, garantono, immobiliare, saba, terrazzato; 4-8 per text, mostly noise); words of the listing / address / agency name and 1-2 letter words are dropped; Claude (same Haiku call, max_tokens 600) judges ONLY those named words. No unknown word = no Claude call. After a fix the re-check asks only about words not already judged fine. Parser now takes the LAST {"errors": [...]} object. Without the package installed it falls back to the old whole-text proofreading (logged).
- Limits: a typo that is itself a real word, and grammar (agreement, missing verb), are not found. Example NOT solved: the closing of 7ff8ec4b "Un giardino terrazzato di 60 metri quadri, contatta Gallo Immobiliare" is a sentence fragment; no spelling check sees it.
- Tests (sandbox): test_italian_check 30/30 (D1-D11 new), all narration suites also PASS with a fake dictionary that flags every word (worst case). NOT RUN: the new detection on real texts (validator block), a real draft after deploy.
- 2026-10-26 (sera, block 128 on the server): the prompt rule of Patch AE did NOT stop "contatta" -> "contatti" on c4cbba23 (a correct word changed by the model). Michele: "contatta" is fine. Patch AF: (1) deterministic guard in italian_check._inflection_only: a correction that only swaps the final vowel or adds / removes a 2-3 letter ending is ignored (choice of form, not a typo); real typos and a missing accent still corrected (tests D13/D14); (2) blocks mode: the SAVED narration_text now shows the closing as its own sentence ("..., contatta X." -> "... . Contatta X."), as the voice already received it since Patch R4 - only the returned string changes, timeline blocks / audio / sync unchanged (tests C4, C20). NOT changed: the single-text and per-scene-script paths still keep the comma in the closing and send no extra pause (changing the sentence count there would move the sentence-to-scene sync; to decide with Michele). NOT re-measured on the server yet.

### 2026-10-26 (sera) - Patch AG: ONE camera-movement table (camera_plan.py) + the approved camera movements become the defaults
- Michele chose full consolidation (option A). ROLLBACK POINT: commit 6485919 (deployed, restarted 18:35). Touches the main generation path (movement chosen for every scene), so verified with a real flow test (photo -> analysis -> scene -> Luma prompt, fake providers, zero cost) and not only unit tests.
- FOUND: the table existed in FOUR copies, already drifted: video_generation.SPACE_DEFAULT_MOVEMENT, vision_analysis._MOVEMENT_MAP (the one every URL draft really used: it overrides the scraper's after the photo analysis), listing_scraper._CATEGORY_TO_POV_MOVEMENT (outdoor = walk_toward) and the mirror in ui.html. Drift: "medium" was walk_in_gentle in video_generation/ui.html but walk_in_explore in vision_analysis. Also the scraper's fallback "gentle_arc" is not a real movement (the July 10 bug again).
- NOW: camera_plan.py holds SPACE_DEFAULT_MOVEMENT, ROOM_MOVEMENT, CATEGORY_MOVEMENT and movement_for(space, depth, room). The four users read it (same object, not a copy); ui.html keeps a mirror checked by test_camera_plan.py (T4); every movement named is checked against the UI list (T6) and the Luma prompt tokens (T7); a unit test lists the exact differences from before (D1-D4) and a source scan fails if a literal space->movement table reappears (N1).
- BEHAVIOUR CHANGES (the only ones): facade (room building_exterior, scraper category exterior, UI space "outdoor") -> approach_facade; garden / pool / other exterior / balcony / terrace (scraper category outdoor, UI space "elevated") -> outward_view; medium interiors -> walk_in_explore everywhere (the value URL jobs already got; the manual UI used walk_in_gentle - Michele to say if he wants gentle back); scraper fallback gentle_arc -> walk_in_explore. UI: two new options with Italian labels; reveal_pullback stays selectable but is labelled "sconsigliato" (it is a REVERSE dolly and invented a street in job 83ca6568).
- Drafts already created keep the movements they were created with (stored per scene at draft time): b13657de etc. need a NEW draft to get the new movements.
- NOT DONE: mirror recognition (reflective_surface) in the photo analysis and the large-mirror movement (separate package); the Florence fallback (no room known) gives "approach_facade" for any outdoor photo; vision_analysis._SPACE_CAMERA is a different, legacy concept (camera hints) and was left alone; eco-tier tables (_KLING/_VEO/depth_renderer) have no entry for the two new movements and fall back safely (.get with walk_in_explore / safe default).
- Tests (sandbox): test_camera_plan 20/20 (new), test_room_recognition 31/31 (4 expected values updated), test_camera_candidates 8/8 (C4 updated); all other suites unchanged and PASS, with and without the dictionary. NOT RUN: on the server, a new draft + one real generation (needs Michele's OK, about USD 7.2 + Sonnet QC about EUR 0.06).

### 2026-10-26 (after AH) open items from the 6dddfd66 review
- Luma fidelity: clip invents elements (dining chair) and leaves the space of the photo. Ideas: stronger prompt wording; end keyframe = crop of the photo. Needs a budgeted test on the living-room scene (EUR ~1.1-1.84/clip). Decision: Michele's budget approval pending.
- Job total: price each Luma clip by the real model used (clip_provenance, direct USD 1.20) instead of fal USD 2.00. Cost logic: needs Michele's explicit OK before code.
- Verbless sentences: VERB_RULE (prompt) is in AH; an automatic check (LLM on stored texts) is NOT built; measure first.
- Download endpoint has its own copy of the range-serving code (now only that one remains besides `_serve_mp4_file`): consolidate later.
- Preview cache `jobs/<id>/preview_cache/` is never cleaned (small); check against the `/diagnostics` auto-cleanup rule before adding any cleanup.

### 2026-10-26 Luma fidelity experiments (budget EUR 10 max, Michele)
- Goal: clip must not leave the space of the photo or invent items (dining chair on 6dddfd66 living room). Candidates: (1) stronger prompt wording; (2) end keyframe = crop of the photo. Test on ONE scene, 1-2 clips per variant (~EUR 1.1 each direct), stop at EUR 10 total; report cost after each run. Not started.
- (2026-10-26 AK) End-frame experiments: plan = same scene, variants base / strict prompt / endframe, then a second scene type; judge: no invented items, stays inside the photo, motion looks like a camera move not a digital zoom, price. Production switch (PVS_END_FRAME or UI option) only after Michele sees the clips.

## 2026-10-27 - anchor / camera direction (from the first full job 26d7a774)
- [open] Re-test the criteria v2 on a real job (cost about EUR 6.6): check that anchors are far, central, fixed and worth seeing, and that no door/fixture/railing is chosen.
- [open] Facade (approach_facade) is static: no camera move at all. Decide a movement for facades that cannot invent (anchor = the entrance / the building centre?), test.
- [open] Bedroom (walk_in_gentle) drifts toward a mirrored wardrobe: wire the mirror flag (reflective_surface) into the generation call, or test an anchor-based lateral/arc move whose anchor is never a mirror.
- [open] Outdoor/balcony: the anchor must be the distant view; if Claude answers a near object the filter drops it (today's outward_view text).
- [open] Clip QC with the anchor ("the camera should have moved toward X; is X closer and nothing new?").
- [open] Manual UI path does not carry the anchor (scenes created by hand keep today's movement).
- [open] Cost: the UI estimate is still a third copy of the backend rates (now equal, test-guarded); consider an endpoint that returns the estimate.
- [open] Preview of scene 5 did not start in the QC approval screen of job 26d7a774: diagnose preview_cache.
- [open 2026-10-27] Photo selection: check on real jobs that the bedroom pick now shows a bed directly; consider checking single-candidate categories and a pool larger than 6; empty apartments rely on page description.
- [open 2026-10-27] Fallback target (balcony/glass door in the centre) when no anchor: decide after the multi-property test.
- [open 2026-10-27] Multi-property test run to reach "good enough": several listings with different characteristics (furnished, empty, no balcony, villa, studio), review each clip.
- [open 2026-10-27] subtle_rotate leaves the first frame in bathrooms (villa e1dccbd4 scene 4): replace with a short anchor push-in when an anchor exists (test one clip first, about EUR 1.10).
- [open 2026-10-27] Selection backfill: when a category is missing the second photo comes from "exterior" first (two facades). Prefer an interior/view photo; needs the order of the backfill in select_photos_for_scene_count / premium.
- [open 2026-10-27] Premium: entrance/hall and stairs scenes (standard excludes them); photos labelled living but classified as hall are now dropped from standard.
- [open 2026-10-27] Narration single_text fallback is still forced onto the scene grid (long gaps, 0.16 s above the 32 s limit); decide whether it should be a plain continuous track.
- [open 2026-10-27] Re-run the villa-type listing (no sale/rent word) to confirm the per-scene / anchored mode now passes.

### AX - 2026-10-27 - testing strategy and open items
- Strategy: golden set of real listings checked at draft stage (cents), movement x room-type clip matrix only when camera rules change (about EUR 1.10 per clip), 2-3 full jobs per release as acceptance. Add one line to golden_listings.txt for every new listing type that shows a problem.
- TODO: temperature=0 (approved); outdoor window-view scene must use outward_view; backfill order must not give a second facade; UI wrong-job status and QC panels; UI costs; Generated with AI label; run-all-tests script; inspect hall check on empty flat c9099c46 scenes 0-1.

### 61 update 2026-10-27: label image replaced (see status AY). OPEN: check it on a real video, bright and dark walls; install Poppins or choose a font; decide darker grey if illegible on bright walls; check whether a second watermark copy exists in the reassemble path.

### AZ 2026-10-27: TTS cost rate by provider (OPEN, to confirm): one rate per TTS_PROVIDER used by cost_tracker (3 places) and the UI estimate; Google Chirp 3 HD USD 30 per 1M characters. Also: remove or fix immobiliare_it_claude.py (duplicate extractor).

2026-10-27 OPEN: job 9615333c, Luma invented a second foreground palm during a walk_in_explore push-in and changed the room. Clip QC returned reject (correct). Prevention not built: (1) A/B prompt test about 2.2 EUR, needs approval; (2) room analysis flag for large foreground vegetation near the camera path. Also open: label size, hall check protection by page caption, single infra forecast number.

2026-10-27 plant test, job 9615333c scene 0: variant still generated (1.10 EUR), result to be judged by Michele on the clip; no prompt change made in production yet. Infra cost is now read from the server (see BB in status.md). Open: decide whether tests count in the rolling job count; label size to verify on a real frame.

2026-10-27 label width 420 accepted for now by Michele on one real frame; darker grey only if it proves too faint. Plant test: the still clip showed no palm but a flat 2D movement, judged unusable by Michele; photo used by the clip being checked; target variant not run yet (1.20 EUR left of the 10 EUR cap).

2026-10-27 foreground risk rule deployed (see BD in status.md). Open: golden set run to count how often the flag fires; if it fires on many scenes decide whether to tighten the question wording; one clip is the only video evidence; label contrast unverified.

2026-10-28 DECISION: launch scope limited to reliable apartment types, empty apartments excluded if not reliable (see PRODUCT DECISION in status.md); detection method and partner-API reply to be scoped. Room recognition = label first, vision as fallback; open question: apply the same rule to the exterior/outdoor check. Open bug: vuoto draft voice 24.96 s below the 26 s floor (per_scene mode).


## 2026-10-28 — Launch scope v1 (draft) and the furnished question
- Draft scope: apartments including monolocali; villas and lofts stay in the pipeline but are not promised; listing photos must meet the acceptance rule (provisional minimum 12 photos, required rooms not yet implemented); room labels from the feed first, Claude vision only when the label is missing or other.
- Furnished requirement: SUSPENDED to measure-only on 2026-10-28. Reason: Michele estimates at least half of GIAL sale listings are empty, so rejecting them would remove most of the pilot feed. The gate stays in the code and is switched by PVS_FURNISHED_ENFORCE.
- To decide with data: (1) share of empty listings in the GIAL feed, measured with the measure-only field furnished_status; (2) one paid test video on an empty listing now free of the stairs bug (about EUR 6.6); then keep empty flats in, or enforce and tell the client up front.
- Relinx spec note: failure_code unfurnished and the message Annuncio non supportato: appartamento non arredato only appear when enforcement is on.
- Open: a posteriori failure policy (notify, hold for review, try again, close as not feasible); partner API reply text; exterior/outdoor label-first question; step_out_onto in production; temperature 0 for judgment calls; draft_check fix for refused drafts; gitignore for *.bak_*.


## 2026-10-28 — scene facts: open items
- Not done: second length pass in the per-scene fallback (option 1 of the earlier proposal); deferred because the facts fixed the vuoto case. Revisit if a thin listing still falls back below 26 s.
- Tighten: view facts should say what is seen (alberi, edifici, cielo), not what place it is (piazza, cortile); add more materials to the banned words (cemento, pietra, mattoni).
- Consider adding material stems (terracott, cotto, graniglia) to the validator feature list in scene_script so a material that is in neither the listing nor the facts is rejected.
- Larger sample before calling it stable (more listings, repeated runs); measure the cost of the facts call on its own; decide if a stronger vision model is worth it.
- Show scene_facts in the review UI so a person can compare them with the photos.


## 2026-10-28 — decisions and open items after the scene facts
- Decision for Michele: accept or reject curato nei dettagli and similar emphasis when the listing does not say it (stem curat). Today it is accepted.
- Facts: the cheapest vision model still describes views loosely (vista luminosa); consider a stronger model once the cost of the call is measured on its own.
- Next area: partner error paths on the fake instance (port 8001, faults.json): not enough photos, narration failure, clip failure with the fallback off, provider quota. Check the four invariants of the test plan on each.

## 2026-10-28 (sera) — difetti del primo video a pagamento e punti aperti
- P1 (requisito concordato con Michele, NON costruito): un job con clip fallite non assembla mai parzialmente. Si ferma in revisione con l'elenco delle scene fallite e le scelte; una guardia all'assemblaggio rifiuta una clip mancante. Niente fermo-immagine (non accettabile). Test: clip fallita -> stato visibile, nessuna scena persa in silenzio.
- P2 (concordato, NON costruito): dopo il tetto di 300 s di Luma continuare a seguire la STESSA generazione (fino a 900 s) invece di abbandonarla; registrare l'id; il costo reale deve includere le generazioni perse/fatturate.
- P3 (concordato, NON costruito): movimento di default per spazio esterno non riconosciuto = minimo/lento (quasi fermo o lento verso un'ancora); approach_facade solo per la vera prima facciata.
- P4 (concordato, NON costruito): viste aeree/drone e monumenti non visti dall'immobile non contano come spazio esterno privato ne' come scena di chiusura (prompt del classificatore).
- Aperto: foto senza etichetta: la regola "living solo con divano" del prompt del classificatore manda le stanze vuote in "other". Irrilevante finche' Relinx invia le etichette; rischio per altre fonti.
- Aperto: chiedere a Relinx conferma di etichette e una sola versione per foto nell'API, risoluzione degli originali, se arrivano mai duplicati.
- Aperto: limite voce 26-32 s senza tolleranza (32.008 s fallisce); errori di plurale (camere per una camera) non intercettati dal validatore; frasi riempitive quando l'annuncio e' scarno; fallback per_scene senza controllo di lunghezza.
- Aperto: confronto Luma vs altri modelli su 2-3 foto problematiche (facciata con alberi, ecc.), circa 8-12 EUR, DOPO P1-P4.
- Aperto: riconciliare la fattura Luma con cost_actual (le chiamate perse sono fatturate).
- Aperto: backup dei job: conservare per capacita' invece che 30 giorni (prima leggere backup_jobs.sh e le dimensioni degli archivi).
- Aperto: batch immobiliare: 6 annunci non ancora creati (limite 5 job/ora per IP); video completi su d8ba3cf0 e sulla bozza vuota eed70d53 in attesa di P1-P4.
- Aperto: rilevamento duplicati per contenuto; test_partner_errors (W2/W3); decisione sullo stem `curat`; criterio arredato solo in misura (PVS_FURNISHED_ENFORCE=0).

## 2026-10-28 (sera, aggiornamento) — P1-P4 costruiti, NON verificati su video reale
- P1, P2, P3, P4 sono nel codice (dettagli in status.md BJ) e provati solo con test e risposte finte. Restano aperti finche' un video a pagamento non li conferma: prossimo passo = un video reale (d8ba3cf0), poi controllo di cost_actual contro Luma.
- Aperto (nuovo): se Luma fattura una generazione in stato "failed", oggi non e' contata; verificare sull'estratto conto.
- Aperto (nuovo): un job con fallback fal attivo che passa a fal dopo un timeout Luma paga due chiamate e la prima non e' contata (in produzione FAL_FALLBACK_ENABLED=false, quindi caso non attivo).
- Aperto: il minimo per un esterno non riconosciuto e' subtle_rotate; se fosse ancora poco curato, valutare un lento avvicinamento a un'ancora (PVS_ANCHOR) dopo il confronto con altri modelli.


## BK — 2026-10-29 — voci aperte emerse dalla causa radice dell'albero sbavato
- Calibrare il giudizio di qualita' Claude vision (measure-only) sulle foto reali: confrontare i verdetti salvati in selection_report.photo_quality con la qualita' dei clip; solo dopo, valutare PVS_QUALITY_ENFORCE=1. Prerequisito per scartare: sostituire una foto scartata con un'altra candidata della stessa categoria (oggi la scena resterebbe corta). Soglia 800 px (lato lungo) e' una scelta mia, da confermare.
- Upscale aura-sr: provare un job GIAL completo con upscale_images=False e confrontarlo coi video gia' fatti; poi decidere il default. Il flag e' oggi fisso a True alla creazione dei job da URL e partner (api_server): da rendere configurabile per la prova.
- Rimozione watermark per le foto da scraping: la nostra rimozione sbava le zone coperte (albero di cc33f8af). Da cercare un metodo migliore o accettare il watermark visibile solo in prova; non toccare il percorso API.
- Correzione luce: sposta i colori (ulivo verso il blu). Da migliorare piu' avanti; per ora resta.
- Percorso partner: in caso di foto insufficienti il job_dir viene cancellato con shutil.rmtree (api_server, flusso partner), mentre nel percorso da URL la patch L/M non cancella piu' nulla sotto jobs/. Divergenza tra i due percorsi: da allineare (decisione di Michele sul rischio).
- Pannello QC: numerazione scene 0-based contro elenco 1-based.
- Rifai: la rimozione watermark nel Rifai non riusa il file della prima generazione (nome per posizione, rischio scena spostata): puo' costare una seconda rimozione. Possibile ottimizzazione solo con un controllo certo che la foto sia la stessa.
- Filtro foto di Relinx/GIAL: lo scarto delle copie con bande esiste solo nello strumento di prova (relinx_pilot_check); il percorso API reale riceve foto pulite (verificato su cc2aead8), nessuna regola equivalente li' per scelta.


## BL — 2026-10-29 (pomeriggio) — voci aperte
- Motivo del fallimento esposto al cliente/partner: GET /v1/videos/{id} e il webhook "failed" portano solo lo stato; serve un campo con codice e frase leggibile (es. foto insufficienti per qualita'). Cambio al contratto API (campo opzionale, compatibile): in attesa di OK di Michele (lingua, nome del campo, da dire a Relinx).
- Calibrazione del giudice di qualita' sulle foto di tutti i job (Claude reale, pochi centesimi per circa un centinaio di foto uniche): vedere quali verdetti escono e confrontarli a occhio con le foto. In attesa di OK di spesa.
- Foto cattiva scartata nella selezione = meno candidate; se il filtro dovesse scartare troppo, si riduce con PVS_QUALITY_ENFORCE=0 senza cambiare codice.
- Prova senza upscale su un annuncio GIAL reale (1307, attico 110 mq, Albano): serve rendere configurabile il flag upscale_images alla creazione del job (oggi fisso a True per URL e partner). Preparare dopo questo deploy.


## BM — 2026-10-29 (sera) — voci aperte
- Comunicare a Relinx i due nuovi campi (failure_code, failure_message) con l'elenco dei codici; il messaggio di "unfurnished" e' in italiano mentre gli altri sono in inglese: decidere la lingua dei messaggi pubblici.
- Calibrazione del giudice: lanciare prima la simulazione (nessuna spesa), poi --run --max ~120 con tetto, guardare i fogli di miniature insieme a Michele. Nota: il giudice usa Haiku 4.5 (il modello economico); se i verdetti sono deboli, provare un modello piu' forte solo per questo giudizio.
- Prova GIAL 1307 con upscale spento: avviare l'istanza di prova 8002 con PVS_UPSCALE_DEFAULT=0 e lanciare l'annuncio con relinx_pilot_check; confrontare con i video gia' fatti. Nessuna spesa reale senza OK di Michele.


## BN — 2026-10-29 (sera) — voci aperte
- Lanciare la prova di controllo (--degrade-test 6 --run, circa 0.03 EUR, 24 chiamate) e leggere i risultati con Michele; solo se le copie peggiorate sono riconosciute e gli originali non danno falsi allarmi, riattivare PVS_QUALITY_ENFORCE (rimuovere la riga =0 dal .env) per soft/blocky.
- Rivedere con Michele il ruolo di portal/agency dopo il lavoro reale GIAL (provvisorio). Il prompt del RANKING penalizza ancora il watermark sul soggetto: coerenza da decidere.
- Il test sulle foto di job passati non contiene foto cattive vere: raccogliere esempi reali di foto sfocate/a blocchi (da annunci futuri) per una calibrazione piu' onesta.


## BO — 2026-10-29 (sera) — voci aperte
- Rilanciare la prova di controllo con il nuovo prompt (stesse foto, circa 0.033 EUR). Soglia per riattivare lo scarto (proposta, da confermare con Michele): copie peggiorate riconosciute in blocco >= 16 su 18 e 0 falsi allarmi sui 6 originali. Se la pixelazione resta invisibile al giudice: provare un modello piu' forte solo per questo giudizio (costo da stimare).


## BP — 2026-10-29 (sera) — voci aperte
- Confrontare altri modelli come giudice con la stessa prova (--model claude-haiku-5-5, poi claude-sonnet-5-5 se serve): scegliere il modello solo se supera la soglia (16/18 e 0 falsi allarmi su 6). Usare un modello diverso in produzione per il solo giudice richiede un costo per modello nel contatore Claude (oggi un solo prezzo, quello di MODEL): da fare PRIMA di cambiare il modello del giudice, altrimenti il costo mostrato sarebbe sbagliato.


## BQ — 2026-10-29 (sera) — voci aperte
- Rilanciare la prova con la riga ANSWER su tre modelli: claude-haiku-4-5-20251001 (produzione), claude-haiku-5-5, claude-sonnet-5-5 (costo totale stimato circa 0.13 EUR). Se solo un modello non-default supera la soglia: prima il conteggio del costo per modello, poi il cambio.
- Lettura troppo permissiva del JPEG a blocchi da parte di Sonnet: se resta dopo la riga ANSWER, rafforzare la definizione di "blocky" (banding o blocchi visibili al ritaglio a 100% anche se lievi) e ripetere la prova, controllando i falsi allarmi sugli originali.


## BR — 2026-10-29 (sera) — voci aperte
- Rieseguire la prova di controllo con il codice a due modelli (python3 calibrate_quality.py --degrade-test 6 --run --cap 0.15, circa 0.05 EUR): attesi 18/18 e 0 falsi allarmi; se confermato, proporre a Michele di togliere PVS_QUALITY_ENFORCE=0 dal .env (riattiva lo scarto di soft/blocky).
- Controllare il costo dei calcoli Claude di vision_analysis.py: chiama ls._track_claude(resp) (conteggio al prezzo del modello predefinito) E somma il proprio costo per use_model in usage_out: possibile doppio conteggio o prezzo sbagliato (non toccato, solo segnalato).
- Provare altre foto reali cattive quando capitano, per allargare il campione (oggi 6 foto con danni sintetici).


## BS — 2026-10-29 (sera) — voci aperte
- Lanciare python3 calibrate_quality.py --blockiness (gratuito) e leggere la distribuzione sulle 101 foto vere: fissare PVS_BLOCKINESS_MAX tra le foto vere e le copie a blocchi (la 5f44c77a deve risultare sopra il limite, nessuna foto vera buona sopra).
- Michele guarda i 12 "soft" delle 101 foto vere: se sono davvero sfocati il giudice e' affidabile sulla sfocatura; se alcuni sono buoni, valutare di far scartare solo se i DUE modelli concordano, accettando di perdere recall.
- Poi: ripetere la prova di controllo (--degrade-test 6 --run, circa 0.05 EUR) e, se la copia 5f44c77a viene presa e i falsi allarmi restano zero, proporre a Michele di togliere PVS_QUALITY_ENFORCE=0.
