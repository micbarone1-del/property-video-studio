# Property Video Studio — Status

_Last verified: July 9, 2026 — full repository audit (July 8) plus live-tested maintenance scheduler feature (July 9). Server and GitHub `main` confirmed in sync throughout via direct terminal verification, not assumption._

---

## ⚠ READ THIS FIRST — Working with Claude in this project

This section exists so a new chat doesn't have to rediscover the same things through trial and error. It documents real environment facts and working patterns, not preferences — verify against live output if anything here seems to have changed.

**Terminal commands must always be given as one complete, ready-to-paste block** — never a fragment requiring manual mid-command editing (e.g. never "insert your token here" in the middle of a URL). If a value like a token needs to go into a command, build the full line with the real value substituted in, and note if a leading space is intentional (keeps it out of shell history on most systems).

**status.md/backlog.md update cadence (changed July 9, 2026):** don't update these after every small fix within a continuous work session — batch updates to natural checkpoints (a feature/modification is genuinely complete, about to move to the next one), not every individual change. The original per-change cadence was meant to prevent losing context between sessions; batching to checkpoints still serves that without the overhead of rewriting these files after every micro-fix.

**Deployment reality — this matters, it caused a real bug this session:** the app runs via a `screen` session executing `uvicorn` directly (see `start.sh`), **not a systemd unit**, despite that being assumed/documented at one point. `systemctl is-active property-video.service` will not work — there is no such unit. Logs are piped to **`/tmp/property-video.log`** via `tee` inside the screen session, not any file inside the project directory. The correct way to verify the app is actually healthy is an HTTP call to `http://localhost:8000/health` — the same check `start.sh` itself uses.

**Claude's file-reading tools have a hard restriction:** Claude cannot fetch a GitHub URL (raw or blob) unless that *exact* URL has already appeared in the conversation — either typed by the user, or returned by a prior search. Claude cannot construct a plausible-looking URL itself, even by following the exact same pattern as a file that just worked. In practice: **always paste the exact `github.com/.../blob/main/FILENAME` or `raw.githubusercontent.com/.../FILENAME` URL directly**, don't assume Claude can just "go check the repo."

**For files too large for one fetch to return in full** (this repo's `api_server.py` and `ui.html` are both large enough to hit this), the reliable path is:
1. Ask Claude in Chrome (a separate browsing-capable Claude instance, accessible via its own sidebar/extension) to create a Google Doc and paste the raw file content into it via the `raw.githubusercontent.com` URL.
2. Set that Doc's sharing to "Anyone with the link" / Viewer.
3. Paste the Doc's `.../export?format=txt` URL (not the `/edit` URL — that's a JS app shell with no readable text) back into chat for Claude to fetch.
4. **If the export URL 401s even though the Doc is confirmed publicly viewable** (this happened repeatedly this session, likely a Google-side quirk specific to the export endpoint, not a real permissions problem) — skip straight to: in the Doc, **File → Download → Plain text (.txt)**, then upload that .txt file directly into the chat. This sidesteps Google's export permissions entirely and has been 100% reliable when the export URL wasn't.

**GitHub push authentication:** password auth for git operations was removed by GitHub in 2021 and will never work, regardless of which password is tried. A Personal Access Token (classic, `repo` scope) is required, used as `https://username:TOKEN@github.com/...`. Build this as one complete pasteable line with the token substituted in — never leave it as a fill-in-the-blank mid-command. **Treat any token that appears in this chat as burned** — revoke it on GitHub (Settings → Developer settings → Personal access tokens) once done, since it's been exposed in a place that isn't meant to hold credentials.

**Before trusting either GitHub or the server as "current," verify sync in both directions** — this project hit a real 3-commit gap once (docs committed on GitHub but never pulled to the server) that could have caused a bad merge if not caught first:
```bash
cd /var/www/property-video-studio/ && git status && git fetch origin && git log --oneline HEAD..origin/main
```

**Rollback is always available and safe.** Every commit stays in git history; nothing is destructive. To undo a specific commit cleanly: `git revert <hash>`. Always note the current `HEAD` commit hash before a risky deploy so there's a known-good point to reference.

**A stale/cached fetch gave confidently wrong answers once this session** — an early read of `video_generation.py` and `api_server.py` returned old, pre-Luma-integration content with no visible error, leading to an incorrect claim that Luma wasn't integrated at all (it was, and was already the default). The fix was cross-referencing against a live `grep`/`cat` from the terminal, which is authoritative in a way a browser-based fetch apparently isn't always guaranteed to be. **When a code claim really matters, verify it against live terminal output, not just one fetch.**

---

## Architecture — live production pipeline

**Backend:** FastAPI (`api_server.py`).

**Auth:** Conditional — gated by `X-Access-Key` header against a `UI_ACCESS_KEY` environment variable if one is set; open access if unset.

**Video generation (`video_generation.py`) — four tiers, all implemented and live:**
- **`eco`** — Lyra 2.0 zoom + Topaz upscale. ~€0.045–0.125/clip.
- **`luma`** — Luma Ray 2. **Current default.** ~€0.46/clip. Confirmed via real testing: genuine 3D parallax, no warping, including on a bathroom photo that previously broke both depth rendering and Veo. Falls back to Veo Fast on failure.
- **`premium`** — Veo 3.1 Fast, native 1080p. ~€0.80/clip.
- **`premium_veo`** — Veo 3.1 Standard. ~€1.60/clip. Built specifically to avoid the circular/internal transition problem. Falls back to Veo Fast on failure.
- **Kling: fully removed from all functional code** — no live references remain.

**Narration-first workflow:** fully implemented — draft-mode job creation, `/jobs/{id}/narration`, `/apply-durations`, `/reassemble-with-narration`, `/start-generation`. TTS generated and measured before video generation; durations confirmed before any video cost is incurred.

**Job model:** single-directory-per-job, stable `scene_id`s, job locking. New rework endpoints (`redo_scene`/`add_scene`/`delete_scene`) use strict scene-index bounds. The old sibling-directory `/jobs/{id}/rework` endpoint is legacy, kept only for old in-flight jobs.

**Test isolation:** `jobs/_test_scratch/` + `/test-scratch/` endpoint.

**Assembly:** `video_assembly.py` — MoviePy, explicit bitrate control.

**Watermark removal:** `watermark_removal.py` (fal.ai) — strips source-listing-site watermarks from uploaded photos.

**QC:** `vision_analysis.py` (Florence-2).

**Video library / job browsing UI:** confirmed implemented in `ui.html` (a "Cronologia video" section with grouped job history, status legend) — independently code-verified July 9, not just reported.

---

## NEW — Automated URL-scraping for photo selection (in progress, July 9, 2026)

**Module:** `listing_scraper.py` — supersedes the earlier `immobiliare_it.py` (direct BeautifulSoup scraping) and `immobiliare_it_claude.py` (single-site version), both now obsolete and candidates for deletion once this is confirmed stable.

**Core mechanism:** rather than a direct HTTP request from this server, extraction happens via a Claude API call using the `web_fetch` server tool (requires `anthropic` package + `ANTHROPIC_API_KEY` in `.env`, plus the `web-fetch-2025-09-10` beta header). This is not a workaround for convenience — direct `requests.get()` calls to immobiliare.it from this VPS return a confirmed 403 (IP-based blocking, not a header/User-Agent issue — verified by testing full realistic browser headers, which made no difference, and confirming the same URL loads normally from a real residential browser). The Claude API fetch runs from Anthropic's infrastructure, not this VPS, sidestepping that block. Rough cost: ~$0.02/listing on Haiku 4.5 (web_fetch itself has no per-call fee, only token cost for fetched content).

Because extraction works by Claude reading the page **semantically** rather than via hardcoded CSS/DOM selectors, one script covers all three initially-scoped sites (immobiliare.it, idealista.it, casa.it) rather than needing a separate adapter per site.

**CONFIRMED WORKING (live-tested against a real client listing, July 9 2026):**
- Fetch + extraction on immobiliare.it: 45 real photos correctly separated from floor plans/agent photos, each with its real Italian label and a sensible category (22 outdoor, 7 living, 4 bedrooms, 4 bathrooms, 3 kitchen, 2 exterior, 3 uncategorized on the test listing).
- Description, price, and address all extracted correctly.
- **Vision-QC fallback for uncategorized photos** — genuinely confirmed working, not just compiling: resolved 1 of 3 uncategorized photos on the real test (down to 2). The `analyse_input()` schema assumption noted below turned out correct enough for at least this case.
- **Photo selection + gap detection** — confirmed: default 1-per-category selection produced zero gaps on the test listing.
- **Download + watermark removal** — confirmed: all 6 selected photos downloaded and had watermarks successfully removed via the existing `watermark_removal.py`, no fallback-to-raw needed.
- **Narration/caption auto-generation** — built (`generate_narration_from_description()`): generates a continuous Italian narration script plus a short on-screen caption per scene from the scraped description, via a plain Claude API text call (no web_fetch needed here, description text is already in hand). Not yet independently confirmed by a human reading the actual generated Italian text for quality/accuracy — only confirmed that it runs and returns structured output.

**Watermark removal — different default than manual uploads:** scraped photos come from a public listing portal and are highly likely to carry that portal's own watermark. Unlike manually uploaded photos (where watermark removal is an opt-in toggle, since an agent's own photos usually aren't watermarked), removal is the **default, not optional**, for every scraped photo — implemented in `download_and_dewatermark()`. If removal itself fails, falls back to the raw downloaded image rather than dropping the photo, but flags this clearly (`watermark_removed: False` + an error note) so a failure doesn't silently ship a possibly-watermarked image.

**Real bug found and fixed in `watermark_removal.py` itself (July 9, 2026) — affects ALL photos, not just scraped ones:** `fal-ai/image-editing/object-removal` is a whole-image diffusion edit, not a masked inpaint — confirmed via live testing that it does not preserve input resolution/aspect ratio (a 1440x900 input came back 1328x800 — a genuinely different aspect ratio, not just scaled down). This means every manually-uploaded photo that went through the watermark-removal toggle before today was silently getting reshaped too. Fixed with two changes: (1) now passes the model's own `aspect_ratio` parameter with the closest matching preset to the real input shape, and (2) guarantees the final output matches the original's exact pixel dimensions via a resize-back step, regardless of what the model actually returns. Not yet re-tested against a live photo since the fix — needs confirmation.

**NOT YET TESTED — needs real verification before trusting in production:**
- **idealista.it and casa.it** — same code path, but zero real listings tested against either yet. Needs a real URL from each.
- **Image resolution upgrade heuristic** (`try_upgrade_resolution()`) — now reports whether it actually found a higher-res variant (`resolution_upgraded: true/false` per photo, printed in the test script's summary) instead of silently succeeding either way — this visibility fix was just added and hasn't itself been re-tested yet.
- **Photo-selection defaults** (`select_photos()`, how many photos per category a real video needs) — currently defaults to 1 per category as a placeholder, not a confirmed product requirement. Needs a real decision (e.g. should living areas/bedrooms get 2-3 while kitchen/exterior stay at 1?).
- **Narration quality** — generates successfully but the actual Italian text quality/accuracy hasn't been human-reviewed yet.

**"Request a new site" workflow:** implemented — any URL from a domain outside `SUPPORTED_DOMAINS` gets logged to `scraper_site_requests.json` (domain + example URL + timestamp) and returns a clear "not supported yet, upload manually" response, rather than guessing at an unfamiliar site's structure.

**NOT YET BUILT:** the actual integration into job creation — there's no `/scrape-listing` API endpoint yet, and no "paste a listing URL" input in `ui.html`. This session produced and tested the extraction/selection engine; wiring it into the live job-creation flow is the next layer, deliberately not started until the engine itself is confirmed solid on all three sites.

**Standard automated video format — decided July 9, 2026:** 6 scenes × 5s = 30s exactly. Important finding behind this: Luma Ray 2 (the default tier) only accepts 5s or 9s clips — nothing else — so a proposed 4s-per-scene or 6s-per-scene format would both actually snap to 5s anyway. 6 scenes × 5s maps 1:1 onto the 6 already-built categories with zero snapping distortion.

**Narration-length adaptation — REDESIGNED again July 9, 2026, per explicit guidance to not estimate timing from word/character count:** the earlier "fix narration to a pre-decided 30s/6-scene box via a correction loop" approach was replaced with a cleaner design: write ONE natural narration (no artificial length target), measure it ONCE with real TTS, then DERIVE how many fixed 5s scenes the video needs (narration + 1s lead + 2s trail, rounded up) — `generate_narration_and_derive_scenes()`. This is simpler (usually 1 TTS call, max 2, vs. up to 3 before), cheaper, and — importantly — this is what finally answers the long-standing "how many photos per category" question: it's now derived from how much the real property content needs to say, via `select_photos_for_scene_count()`, rather than a fixed placeholder. Bounded between 4-8 scenes (20-40s video). Not yet re-tested against this newest redesign — needs a fresh live run.

**Scene-count range tightened, July 9, 2026, per explicit requirement to stay "roughly 30s":** narrowed from an initial 4-8 scenes (20-40s) to 5-7 scenes (25-35s), anchored on 6 scenes/30s as the common case. The correction logic is now symmetric — a single shorten pass if narration would need more than 7 scenes, a single extend pass (real description content only) if it would need fewer than 5 — rather than just clamping scene count afterward, which could otherwise leave several trailing scenes playing with no narration if a listing's real content happened to be sparse.

**Deferred idea, not yet built — a fade in/out buffer at the assembly stage:** discussed as a possible additional safety margin — e.g. 1s of fade-to-black at the very start and end of the assembled video — to absorb any small residual timing mismatch, on top of (not instead of) the lead/trail silence already built into the audio track. Would be implemented in `video_assembly.py` once scene clips have well-defined final durations, not in the scraper itself. Not started — explicitly framed as an "if needed" fallback, not a current requirement.

**Real bug found and fixed, July 9, 2026 — `build_standard_video_scenes_config()` was silently dropping scenes:** confirmed via a live test where 7 photos were correctly selected (exterior got 2, since scene_count derived to 7) but only 6 scenes_config entries were built — the function only ever took `photos[0]` per category, never updated after the scene-count redesign to handle a category having multiple selected photos. Fixed: now iterates every selected photo, one scene per photo. Minor known limitation, not yet addressed: when a category has 2+ photos, they currently share the same on-screen caption text (captions are generated per-category, not per-photo) — cosmetic, not functional.

**Excess trailing silence fixed, July 9, 2026:** rounding scene count up to the next 5s boundary could leave far more than the intended ~2-3s of trailing silence if speech was only just over the previous boundary (confirmed: 27.7s speech needing 30.7s total rounded all the way up to 35s, leaving 6.3s of dead air). Now checks for this and prefers a small trim to fit the lower scene count instead of accepting a whole wasted extra scene, whenever the excess would exceed ~4s.

**Narration objectivity tightened, July 9, 2026:** confirmed via live output that "don't invent facts" wasn't strong enough to stop the model adding unjustified subjective/promotional adjectives (e.g. calling Morlupo — a small town — "prestigiosa," and earlier calling a kitchen "moderna" when the description never said so). All narration/caption/shorten/extend prompts now explicitly instruct staying factual and objective, matching only the tone and specific claims actually present in the source description rather than adding marketing-style embellishment. Not yet re-tested — needs a fresh run to confirm the tightened prompts actually stop this pattern.

**Photo quality ranking — built, addresses a real gap:** previously, when a category had multiple candidate photos, selection just took whichever was listed first with zero quality judgment. `rank_photos_by_quality()` now sends candidates (capped at 6 per category to bound cost) to Claude as actual images with a scoring prompt covering the agreed criteria: no people visible, key room-defining elements present (bed for bedroom, sink/counter for kitchen, etc.), natural light, and a fuller/more spacious frame — the last one also serves a practical purpose beyond aesthetics, since a fuller frame gives Luma more real visual information to work with, reducing hallucination risk in cropped/ambiguous areas. Falls back to original order if the ranking call fails. **Not yet tested against a live listing with real multi-photo categories** — needs a fresh run to confirm both this session's fixes.

**Test artifacts now auto-copy to stable, predictable filenames** (`test_narration.mp3`, `test_<category>_<NN>.jpg` in `jobs/_test_scratch/`), overwritten on every run — replaces the earlier fragile approach of manually globbing `/tmp/tmp*_full_track.mp3` in a separate shell command, which silently failed at least once this session when multiple leftover temp files from earlier runs matched the same glob pattern.

**Image softness after watermark removal — still the same known characteristic, not a new regression:** confirmed exact dimension match (see earlier fix), but the underlying model still regenerates the whole image via diffusion, which can look slightly softer than the original regardless of matching pixel dimensions. The previously-discussed mask-based alternative (`fal-ai/object-removal/mask`) would address this properly but needs watermark-location detection built first — not started, would improve every photo in the app (not just scraped ones) if pursued.

**`/test-scratch/` endpoint now also serves audio** (`.mp3`/`.wav` with correct `audio/mpeg`/`audio/wav` content type) — needed to actually listen to generated narration test files in-browser, same fix pattern as the earlier image content-type bug.

**`build_standard_video_scenes_config()`** — converts a selection + captions into the exact `scenes_config` format the existing job pipeline expects (caption, empty per-scene voiceover since narration is a continuous track applied at assembly time, space_type, pov_movement, duration, local image path). ASSUMPTION FLAGGED: the category→space_type mapping (exterior/outdoor/living/kitchen→"large", bedrooms/bathrooms→"small") is a reasonable default, not independently re-verified against `video_generation.py`'s full valid space_type vocabulary this session.

**Still not built:** the actual orchestration — a single endpoint that takes a URL and does everything automatically (scrape → select → download/dewatermark → narration-match → create job → trigger real Luma generation → assemble with narration overlay) end to end with no manual steps. This is the next concrete piece once narration-length adaptation is confirmed working on a real test.


Built in response to backlog item "Auto maintenance scheduler." Fully deployed, live-tested, and confirmed working — not just written.

**Architecture:** `maintenance_scheduler.py`, triggered by cron every 5 minutes. Each individual check runs on its **own** interval (tracked in `maintenance_last_run.json`), not a single fixed frequency — a 5-minute health check would be pointless run daily, and a destructive cleanup running every 5 minutes would be reckless. Current intervals:

| Check | Interval | Reasoning |
|---|---|---|
| `service_status` | 5 min | HTTP check against `/health` — outages need fast detection |
| `disk_usage` | 30 min | |
| `stuck_jobs` | 30 min | |
| `credits` | 1 hr | `credit_monitor.py` already alerts directly per-job; this is a backup net |
| `fallback_rate` | 1 hr | Log-scans for Luma/Veo fallback spikes (possible upstream fal.ai issue) |
| `test_scratch_size` | 6 hr | Low urgency |
| `cleanup_verification` | 24 hr | **The only check with a real destructive side effect** (triggers actual job deletion) — deliberately least frequent |

**Why cron (external), not an in-app background task:** the `service_status` check exists to catch the app crashing. If it were scheduled from *within* `api_server.py` itself, it would die along with the thing it's meant to detect. Running it as an independent, cron-triggered process is what makes it a real check.

**Alerting:** email to every address in `maintenance_alert_emails.json` (editable via `/maintenance/alert-emails` GET/POST, and in the UI's "🔧 Maintenance" panel), throttled to at most one email per hour for an ongoing issue. Uses the same Gmail SMTP credentials as `credit_monitor.py` (`ALERT_EMAIL_FROM`/`ALERT_EMAIL_PASSWORD`) — **important:** the app password must be generated while logged into `video.AI.automated.email@gmail.com` specifically (the bot account `ALERT_EMAIL_FROM` points to), not a personal Google account — this caused repeated `535 Bad Credentials` failures before being caught.

**UI:** "🔧 Maintenance" button in the header (turns red if any check is currently red), modal showing check results + last cleanup summary, editable comma-separated alert-email list.

**Two real, previously-invisible bugs found and fixed while building this** (not hypothetical — confirmed via live test runs):
1. The existing 7-day job cleanup only ever deleted jobs with status `done` or `failed` — anything stuck mid-workflow (`running`, `queued`, `draft`, `awaiting_approval`) accumulated forever regardless of age. Fixed: cleanup now applies to any status, based on `job_meta.json`'s filesystem last-modified time (updated by `_save_job()` on every real state change) rather than the `created_at` field.
2. Job directories with **no `job_meta.json` at all** (orphaned — likely from a job creation that crashed before its first save) were permanently un-deletable, since the cleanup logic required that file to exist just to check eligibility. Fixed: falls back to the directory's own mtime when `job_meta.json` is missing.

Combined, these two fixes cleared **34 stale/orphaned job directories** in production during testing (12 + 22 across two cleanup runs).

**Deployment note:** `cron` was not installed on this VPS at all before this session (`crontab: command not found`) — installed via `apt-get install -y cron` and enabled via systemd (`cron` itself does run as a systemd service, unlike the app).

---

## Present in repo but NOT part of the live pipeline (legacy / standalone)

- **`main.py`, `communication.py`**, and the CLI paths in `video_assembly.py`/`video_editor.py` — self-contained legacy automation (Excel-via-email intake, Drive upload, email delivery). Confirmed disconnected: `communication.py`'s Google API dependencies aren't even in `requirements.txt`. Note: `video_editor.py`'s legacy path has its own logo-overlay support — relevant context for the client-logo backlog item, but not directly reusable (different code path from the live `assemble_property_video()`).
- **`depth_renderer.py`** — sophisticated, complete implementation, but its `measure_depth_score()` auto-routing logic is not called anywhere in `api_server.py`. Kept for reference; Luma Ray 2 solved the problem this was built for.
- **`batch_depth_test.py`, `test_luma.py`** — standalone test scripts, not imported by the live pipeline.
- **`reassemble_fix.py`** — one-off manual repair script hardcoded to a specific past job ID. Candidate for deletion.

---

## Open items

- **Rework edge cases (watch item, no known repro):** flag with a concrete repro when one surfaces.
- **`.env` contents** (auth key presence, API keys) not independently verified — correctly gitignored, not read.
- **Maintenance scheduler tiering** — first manual run correctly fired all 7 checks (expected, nothing had run before). Subsequent 5-minute ticks should show `checks_ran_this_tick` shrinking to mostly `["service_status"]` in `/tmp/maintenance.log` — not yet independently confirmed after a paste error interrupted the verification command; worth a quick `tail -50 /tmp/maintenance.log` check.

---

## July 10, 2026 — Automated URL workflow + generation bug fixes (batch update)

**Root cause of "stuck at scene 0" found and fixed:** `fal_client.subscribe()` had no timeout on any of its 8 calls in `video_generation.py`. Confirmed via standalone `test_luma.py` run (7m34s wall clock, 5.6s CPU — pure network wait with no escape path). Also confirmed from fal.ai dashboard that some requests were failing instantly with 422 errors (wrong duration format, image too large) but those errors were silently swallowed. Three fixes applied to `video_generation.py`:
1. **8-minute hard timeout** on all `fal_client.subscribe()` calls via `_subscribe_with_timeout()` — a stalled queue request now fails cleanly instead of polling forever
2. **Image size cap at 1920×1920** before upload — Luma/Veo reject larger images with a 422 "Image dimensions are too large" error, confirmed from fal.ai dashboard
3. Both the `premium_veo` inline call and the LTX emergency fallback inline call were also wrapped (different indentation pattern than the others — caught in a second pass)

**URL-to-video automated workflow — Phase 1 UI integration built and deployed (July 10, 2026):** "Automated workflow — Start from a listing URL" section now appears in the UI above "Property details." Paste a listing URL, click "🔗 Avvia da URL," and the full chain runs (scrape → vision QC fallback → photo quality ranking → watermark removal deferred to generation → narration + TTS measurement → scene count derivation → job creation) and auto-populates the existing editor — you review and press "Generate Video" manually (Phase 2 full automation is a later step). Human-in-the-loop by design.

**`/jobs/from-url` endpoint (new, `api_server.py`):** all blocking scraper calls wrapped in `asyncio.to_thread()` — confirmed this was missing initially (caused false "server not responding" maintenance alerts during scraping). Cost estimate now computed correctly using same `estimate_job_cost()` as manual jobs. Real per-photo vision analysis (`analyse_input()`) applied to each scraped photo for space_type/pov_movement, replacing a static category-lookup table. Key field name bugs fixed: was using `analysis.get("space_type")` and `analysis.get("pov_movement")` — real keys are `v7_space_type` and `suggested_movement`. Space type normalization added (`large_interior` → `large`, etc.) to match SPACE_OPTS vocabulary.

**Photo selection bugs fixed (July 10, 2026):**
- Outdoor category was silently excluded every time `scene_count < 6` — PRIORITY_ORDER[:scene_count] took the first N by list position, not by availability. Fixed: now drops whichever categories have fewest photos, using list position only as tiebreak.
- Duplicate photo safeguard added: deduplicates candidates by URL before selection.
- Flexible backfilling: missing categories now draw from surplus categories rather than blocking the workflow.

**Camera movement fix (July 10, 2026):** movement values in `_CATEGORY_TO_POV_MOVEMENT` were entirely invented names (`gentle_arc`, `soft_orbit`, etc.) that matched nothing in MOVEMENT_OPTS. Confirmed via UI inspection: the dropdown always showed the first/starred option regardless of category. Fixed with verified real values from MOVEMENT_OPTS. **Two-layer bug:** even with correct values in the static table, the actual vision analysis results were never applied because wrong key names (`pov_movement` instead of `suggested_movement`) meant `analysis.get()` always returned None.

**UI bugs fixed (July 10, 2026):**
- `removeScene()` didn't reindex `sceneUserData`/`sceneAnalysis` after deletion — captions stayed "stuck" at their old index positions. Fixed with a proper reindex pass.
- Cost estimate showed €0 for URL-scraped draft jobs — `updateCostEstimate()` treated any loaded job with `currentJobId` set as a completed rework (charging nothing). Fixed by tracking `currentJobStatus` and only applying the rework-cost logic for genuinely completed jobs. Also added the missing `updateCostEstimate()` call at the end of `editJob()`.
- "Rifai" rework message showed on fresh draft jobs — fixed with `isFreshDraft` check.
- URL input section spacing and placeholder text clarified.

**Watermark removal simplified (July 10, 2026):** eager removal during scraping replaced by pre-checking the existing per-scene `remove_watermark` toggle, which handles it at generation time via the same mechanism manual uploads already use. Eliminates unnecessary fal.ai cost on photos that get rejected before generation.

**Narration objectivity confirmed working:** "prestigiosa," "moderna," and similar unjustified promotional adjectives are no longer appearing in generated narrations after the prompt tightening — confirmed via live output comparison.

**Server restart = generation kill — confirmed pattern, not a code bug:** multiple "stuck" jobs this session were caused by `./start.sh` restarting the server while a generation was in flight. The background task dies silently mid-scene, leaving the job frozen. This is why the kill-switch/pre-deploy check feature (backlog item 12) is genuinely urgent, not just nice-to-have.

---

## July 11, 2026 — Critical generation bug found and fixed, kill-switch built, further scraper testing

**ROOT CAUSE of "stuck at scene 0" finally found and fixed — a real, serious bug in the timeout fix itself:** the `_subscribe_with_timeout()` wrapper added July 10 used `with _cf.ThreadPoolExecutor(...) as executor:` — but `ThreadPoolExecutor.__exit__` unconditionally calls `shutdown(wait=True)`, which blocks the *calling* thread until the original submitted task finishes. Since the underlying fal.ai call was the thing that never returned, `shutdown(wait=True)` just waited forever too, silently defeating the entire timeout. Confirmed via `py-spy` process inspection: a real job was stuck for **hours** inside this exact `shutdown()` call. Fixed by removing the `with` block and calling `executor.shutdown(wait=False)` explicitly, so cleanup never blocks — the orphaned worker thread finishes or dies on its own in the background.

**Separately confirmed: some Luma failures ARE genuinely upstream, not us.** Two real jobs failed after **almost exactly 2402 seconds (~40 min)** with `504 Downstream service unavailable` — too precise to be coincidence, suggesting an internal ~40-min timeout on fal.ai's Luma backend right now. Luma's own status page (status.lumalabs.ai) shows a documented precedent for exactly this failure class ("Dream Machine jobs remained in..." — May 27, 2026, degraded 1 hour) but no active incident was listed as of the last check. Reported to fal.ai support with exact request IDs; auto-refund expected per their policy. **Veo confirmed working reliably** as the practical alternative while this persists.

**Full end-to-end test SUCCESSFUL on Veo (July 11, 2026)** — URL scrape → narration → scene selection → job creation → generation → completed video, entirely clean. First fully successful confirmation of the whole Phase 1 pipeline this session.

**Kill-switch built and deployed:** persistent pause flag (`generation_pause.json`, survives restarts), `/admin/pause-generation` and `/admin/resume-generation` endpoints, `/admin/generation-status` for live state, wired into all three job-start entry points (`create_job`, `start_generation_for_draft`, `create_job_from_url`). Visible UI banner + toggle button next to the Maintenance button — deliberately visible, not hidden admin plumbing, so a paused state never looks like a broken submit button. **Deployment note:** first attempt broke the server entirely (`NameError: name 'app' is not defined` — new code was accidentally inserted before `app = FastAPI(...)`) since `python3 -m py_compile` only checks syntax, not import-time errors. Fixed by moving the block to the correct location and verifying with a real module import before restarting again. **Lesson for future backend changes:** always verify with an actual import test, not just `py_compile`, before restarting.

**Narration/rework false-trigger bug — found and fixed (second occurrence of the same root cause):** `genBtn`'s click handler checked `durationChangedSceneIndices.length > 0 && currentJobId` to decide whether to route to the rework endpoint — true for ANY loaded job with a changed duration, including a fresh draft that's never been generated once. Fixed the same way as the earlier cost-estimate bug: gated on `currentJobStatus !== 'draft'` as well.

**Narration now ends with an invite to contact the agency** — added to `NARRATION_PROMPT`, explicitly without a phone number or email (TTS already excludes those elsewhere in the prompt).

**Confirmed real gap, not yet fixed:** the *manual/general* narration path (`_overlay_narration_audio` in `api_server.py`) has zero protection against narration running longer than the pre-calculated video duration — unlike the scraper's own narration engine, which has a hard ceiling + fade-out safety net. Only handles the "narration shorter" case in its docstring. Flagged, not yet built — deprioritized behind the kill-switch this session.

**idealista.it / casa.it — tested twice each, extraction genuinely does not work yet:** both returned 0 photos on the most recent test (regressed from 1 photo on the first). User's hypothesis: idealista's gallery may require a click to expand, which a static page fetch can't do — plausible but unconfirmed for casa.it's failure specifically. The "GAPS DETECTED — manual upload needed" fallback worked correctly here — this is the safety design working as intended, not a crash. Real fix would likely need finding each site's internal image-loading API rather than parsing the rendered page. Not started — deprioritized behind core pipeline reliability this session.

**Real bug found and fixed:** when a listing has 0 selected photos, caption generation was still running anyway — with no real category list to work from, the LLM invented its own made-up category names instead of returning nothing. Fixed: caption generation is now skipped entirely when there's nothing to caption.

**Real bug found and fixed (unrelated crash, in the test script itself):** `listing_scraper.py`'s `__main__` block still printed gaps using the old dict format (`gap['category']`) after `gaps` was changed to a list of plain strings weeks earlier — crashed instantly whenever a real gap occurred. Fixed.

---

## July 12, 2026 — Critical fixes + cost reporting shipped

**ROOT CAUSE of jobs hanging for HOURS - found via py-spy, fixed.** The `_subscribe_with_timeout` wrapper used `with ThreadPoolExecutor(...)`, whose `__exit__` calls `shutdown(wait=True)` - which blocks the CALLING thread until the stuck task finishes, silently defeating the entire timeout. A real job was stuck inside that exact shutdown() call for hours. Fixed: no `with` block, explicit `shutdown(wait=False)`.

**Muted rework videos - fixed.** Of the three assembly paths, the LEGACY rework path was the only one that never called `_overlay_narration_audio`. Confirmed cause of silent rework output.

**Redo broken on ALL older jobs - fixed.** `run_redo_scene` only looked for `{scene_id}.jpg`; jobs predating that convention store `scene_NNN.jpg`, so redo always failed "No source image found". Legacy fallback + self-heal added.

**Narration longer than video - fixed (5/5 regression tests).** `calculate_scene_durations` snapped durations PER SCENE, so rounding loss multiplied across scenes and nothing re-checked the total. It REPORTED 30s while delivering 25s. Now recomputes the real achievable total and extends until the video genuinely covers the narration.

**Fade in/out padding - built.** `_overlay_narration_audio` now adds blank (black/white per transition_style) padding at start and end with fades, sized to absorb narration overflow. Previously the audio was silently truncated or ended on a frozen frame.

**Rework edits silently dropped - fixed.** Caption/space_type/pov_movement changes had NO tracking, so pressing "Genera Video" saw no pending changes and did a cheap reassembly instead. Added `contentChangedSceneIndices`.

**Luma anti-hallucination prompts - tightened.** Luma had almost NO constraints ("no people, no text overlays") vs Veo's comprehensive scaffold. Added real constraints (no invented rooms/mirrors/falling objects/warping) and reduced forward camera drift. NOTE: probabilistic harm reduction, not a fix - QC still cannot reliably catch hallucinations.

**Generation kill-switch - built.** Persistent pause flag, admin endpoints, visible UI banner.

**COST REPORTING - shipped end to end.** cost_model.py (agencies, sales, investment ledger, seller commission, break-even), API endpoints, UI dashboard with visuals, real Claude API token cost tracking (Haiku 4.5 = $1/$5 per MTok, verified). Live: EUR 4,046.01 invested, EUR 4,167.21 to break-even = 9.3 packages.

---

## Standing safeguards

- Stale browser cache can cause subtle bugs — hard refresh to verify JS changes.
- **Terminal paste artifacts are a real, recurring hazard** — stray bracketed-paste characters (e.g. `^[[200~...~`) can silently corrupt or no-op a pasted command. If a command's expected output doesn't appear, check for this before assuming something deeper is wrong.
- Repo is public — never commit secrets; `.env` stays gitignored.
- Never paste real credentials (passwords, tokens) into chat as reusable secrets — treat anything that appears here as compromised and rotate it.
