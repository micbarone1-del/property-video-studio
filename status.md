# Property Video Studio — Status

_Last verified: July 9, 2026 — full repository audit (July 8) plus live-tested maintenance scheduler feature (July 9). Server and GitHub `main` confirmed in sync throughout via direct terminal verification, not assumption._

---

## ⚠ READ THIS FIRST — Working with Claude in this project

This section exists so a new chat doesn't have to rediscover the same things through trial and error. It documents real environment facts and working patterns, not preferences — verify against live output if anything here seems to have changed.

**Terminal commands must always be given as one complete, ready-to-paste block** — never a fragment requiring manual mid-command editing (e.g. never "insert your token here" in the middle of a URL). If a value like a token needs to go into a command, build the full line with the real value substituted in, and note if a leading space is intentional (keeps it out of shell history on most systems).

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

**Narration-length adaptation — redesigned July 9, 2026 with a hard structural requirement, not a soft tolerance:** initial version used a symmetric ±2s tolerance around the 30s target, which live testing showed could leave narration overflowing past the video's end (34.5s narration against a 30s video — the extra would get cut off mid-sentence). Corrected per explicit requirement: **1s of silence before narration starts, and a hard-minimum 2s of silence after narration ends, before the video ends — overflow past this is never acceptable; running shorter (more trailing silence) is always fine.** This gives a hard ceiling of 27s for actual spoken content (30 - 1 - 2), targeted with a further safety margin (aims for ~25s, not right at the edge). The correction loop only ever triggers on overflow past the ceiling (always corrected, no tolerance) or on narration being unusually sparse (under 15s, extended with real content); anything in between is accepted as-is. A fade-out trim remains as an absolute last-resort safety net if correction rounds still don't get under the ceiling. `generate_narration_matching_duration()` now returns a **complete, ready-to-overlay audio track** (lead silence + narration + trailing silence, padded to exactly 30s total) rather than just the bare narration clip. **Not yet re-tested against this exact redesign** — needs a fresh live run to confirm.

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

## Standing safeguards

- Stale browser cache can cause subtle bugs — hard refresh to verify JS changes.
- **Terminal paste artifacts are a real, recurring hazard** — stray bracketed-paste characters (e.g. `^[[200~...~`) can silently corrupt or no-op a pasted command. If a command's expected output doesn't appear, check for this before assuming something deeper is wrong.
- Repo is public — never commit secrets; `.env` stays gitignored.
- Never paste real credentials (passwords, tokens) into chat as reusable secrets — treat anything that appears here as compromised and rotate it.
