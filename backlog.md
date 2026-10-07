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

**Not started.** Scope to be defined beyond the above. Would sit alongside the existing model tiers as a hallucination-free option.

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

**Still open:** the exact 4-states list Relinx's box refers to (see above); the rights/DPA addendum (above — blocking) -- a first working draft now exists (Claude Doc, built October 6, 2026, covering roles/DPA, sub-processor transfers, publication rights, AI-content liability, retention; explicitly NOT legal-reviewed and not yet sent to Relinx); who pays if this becomes paid; whether partner agencies see the operator review step at all. Resolved and removed from this list: on-demand vs automatic (on-demand), photo hosting (public URLs), volumes (2/day/agency), target agencies (1, then 3 more), Getrix (irrelevant).

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

## Not backlog items — standing watch items (tracked in status.md, not here)

- Rework edge cases that may surface in specific use cases (no confirmed repro yet).
- Maintenance scheduler tiering behavior — pending log confirmation.
