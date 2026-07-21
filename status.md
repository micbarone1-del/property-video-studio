# Property Video Studio — Status

_Last verified: July 9, 2026 — full repository audit (July 8) plus live-tested maintenance scheduler feature (July 9). Server and GitHub `main` confirmed in sync throughout via direct terminal verification, not assumption._

---

## ⚠ READ THIS FIRST — Working with Claude in this project

This section exists so a new chat doesn't have to rediscover the same things through trial and error. It documents real environment facts and working patterns, not preferences — verify against live output if anything here seems to have changed.

**Terminal commands must always be given as one complete, ready-to-paste block** — never a fragment requiring manual mid-command editing (e.g. never "insert your token here" in the middle of a URL). If a value like a token needs to go into a command, build the full line with the real value substituted in, and note if a leading space is intentional (keeps it out of shell history on most systems).

**status.md/backlog.md update cadence (changed July 9, 2026):** don't update these after every small fix within a continuous work session — batch updates to natural checkpoints (a feature/modification is genuinely complete, about to move to the next one), not every individual change. The original per-change cadence was meant to prevent losing context between sessions; batching to checkpoints still serves that without the overhead of rewriting these files after every micro-fix.

**Deployment reality — this matters, it caused a real bug this session:** the app runs via a `screen` session executing `uvicorn` directly (see `start.sh`), not by manually starting a systemd unit — restart with `./start.sh`, which handles clearing the port and relaunching. Logs are piped to **`/tmp/property-video.log`** via `tee` inside the screen session, not any file inside the project directory. The correct way to verify the app is actually healthy is an HTTP call to `http://localhost:8000/health` — the same check `start.sh` itself uses.

**Correction, July 16, 2026 — the "there is no such unit" claim above was checked directly and is wrong.** `systemctl list-unit-files | grep property` confirms `/etc/systemd/system/property-video.service` genuinely exists and is **enabled** (would auto-start on boot). In practice the app is still actually run via the manual `screen` + `start.sh` path, not through this unit — but since the unit is enabled, a VPS reboot could start its own uvicorn instance via systemd *at the same time* someone manually runs `start.sh`, causing a port conflict or two competing processes. Not yet investigated further (what the enabled unit actually points at, whether it's been triggered) — worth checking before the next reboot rather than assuming it's inert.

**Terminal transfer size limit — found the hard way, July 16, 2026.** Pasting large multi-KB content into Hostinger's browser-based terminal (base64-encoded patch scripts, chunked with `echo -n '...' >> file`) is unreliable above roughly 2-2.5KB per line — confirmed corruption (wrong byte counts after decode) and one full session crash/logout at exactly this size. Small patches (single functions, a few KB) transferred via this method worked fine earlier the same session; only got risky once a single script grew to ~20KB. **Standing rule now: for anything larger than a small patch, don't paste it through the terminal at all** — create the complete file(s) as a download, have the user upload the complete corrected file directly to GitHub (Add file → Upload files, overwriting the same filename), then just `git pull` on the server. This proved completely reliable for files well over 100KB.

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

**Confirmed again, July 21, 2026 — even Claude's OWN web_fetch of these exact doc files returned stale, cached content once**, showing a July 8 version when the real, live file (confirmed via direct terminal `cat`) was already at July 12. Same lesson, reinforced: for anything that matters, verify against the live server directly, not a fetch — including when Claude is checking its own prior work.

**Anchor-matching for code patches has a recurring, specific failure mode: missed blank lines.** This codebase consistently uses double blank lines between many statements/blocks (not a universal rule, but common enough to catch people out repeatedly this session). Multiple patches failed on the first attempt purely because an anchor assumed a single blank line where the real file had two. Standing practice: when a patch anchor fails to match, check for this specific issue first (`cat -A` on the real lines) before assuming anything more complicated is wrong.

**`grep` for a function call can silently miss real call sites if the function is passed by reference rather than invoked directly** — e.g. `asyncio.to_thread(some_function, ...)` has no literal `some_function(` substring, so `grep "some_function("` finds nothing even though it's genuinely called there. This tripped up the same search pattern at least three separate times this session (`assemble_property_video`, `enhance_image`, `generate_video_single`). Standing practice: when checking "does anything call X," grep for the bare name first, without requiring a trailing `(`.

---

## Architecture — live production pipeline

**Backend:** FastAPI (`api_server.py`).

**Auth:** Conditional — gated by `X-Access-Key` header against a `UI_ACCESS_KEY` environment variable if one is set; open access if unset.

**Video generation (`video_generation.py`) — four tiers, all implemented and live:**
- **`eco`** — Lyra 2.0 zoom + Topaz upscale. ~€0.045–0.125/clip.
- **`luma`** — Luma Ray 2. **Current default.** Confirmed via real testing: genuine 3D parallax, no warping. Falls back to Veo Fast on failure. **Real cost corrected July 21, 2026 — see that section; the old €0.46/clip figure was wrong by roughly 4x.**
- **`premium`** — Veo 3.1 Fast, native 1080p.
- **`premium_veo`** — Veo 3.1 Standard. Built specifically to avoid the circular/internal transition problem. Falls back to Veo Fast on failure.
- **Kling: fully removed from all functional code** — no live references remain (one dead prompt-assembly branch, `_generate_kling`, still exists in `video_generation.py` but nothing routes to it).

**Narration-first workflow:** fully implemented — draft-mode job creation, `/jobs/{id}/narration`, `/apply-durations`, `/reassemble-with-narration`, `/start-generation`. TTS generated and measured before video generation; durations confirmed before any video cost is incurred. **Note (July 21, 2026): this entire system is separately reimplemented in `listing_scraper.py` for URL-scraped jobs — see the "Architecture assessment" section below. The two do not share code.**

**Job model:** single-directory-per-job, stable `scene_id`s, job locking. **As of July 21, 2026, only ONE assembly implementation remains** (`run_reassemble_only`, used by first-time generation, QC-approval, and every redo/rework path) and **only ONE redo/rework mechanism remains reachable from the UI** (`POST /jobs/{id}/scenes/redo-batch`) — see "Architecture assessment" for the full consolidation history. Two endpoints from the old model (`POST /jobs/{id}/scenes/{scene_id}/redo`, `POST /jobs/{id}/rework`) still exist in the backend and are confirmed UI-orphaned (nothing in `ui.html` calls either), but have not yet been deleted.

**Test isolation:** `jobs/_test_scratch/` + `/test-scratch/` endpoint.

**Assembly:** `video_assembly.py` — MoviePy, explicit bitrate control. **Canvas is now dynamic** (landscape 1920×1080 or portrait 1080×1920), driven by each job's `output_format` — see the portrait/landscape section below.

**Watermark removal:** `watermark_removal.py` (fal.ai) — strips source-listing-site watermarks from uploaded photos.

**QC:** `vision_analysis.py` (Florence-2).

**Video library / job browsing UI:** confirmed implemented in `ui.html` (a "Cronologia video" section with grouped job history, status legend) — independently code-verified July 9. **Note (July 21, 2026): the "main jobs and reworks" grouping this relied on is stale** — it was built for the old sibling-directory rework model (parent job + `_rwXXXX` sibling entries), which no longer exists now that reworks happen in-place on the same job. The user has asked for this reorganized around clients/properties/jobs instead — see backlog item 39, not yet started.

---

## July 21, 2026 — Portrait/landscape format support, a major cost-model bug, redo-workflow reliability fixes, and a full architecture consolidation pass

This was the single largest day of work on this project to date. Summarized by theme; see git history for exact commits.

### Portrait/landscape format support (real client-driven bug chain)

**Original symptom:** a client's portrait photos came out visibly warped/distorted in Luma-generated video. Root-caused through several layers, each one real and each one only partially explaining the symptom until the next was found:

1. **`aspect_ratio` was hardcoded to `"16:9"` on every Luma/Veo call**, regardless of the real input photo's orientation. Fixed: `_detect_aspect_ratio()` in `video_generation.py` now picks the closest of Luma's real supported presets (confirmed via fal.ai docs: 16:9, 9:16, 4:3, 3:4, 21:9, 9:21) or Veo's `"auto"` mode. This alone did NOT fully fix the problem —
2. **`video_assembly.py` still force-stretched every clip into a hardcoded 1920×1080 canvas** (`clip.resized((TARGET_W, TARGET_H))`, no aspect-ratio preservation) — so Luma would correctly generate a portrait clip, and assembly would then squeeze it back into landscape. Root-caused via direct evidence: a 6000×8000 source photo correctly produced a 1080×1440 Luma clip, which then came out as 1920×1080 in the final assembled video.
3. **Decision made (explicit product discussion, not just a technical fix):** rather than pure native-per-photo output (which breaks down for a property with mixed portrait/landscape photos — confirmed real case, two photos in one job came back as 3:4 and 9:16) or always-landscape (loses real content), the app now supports **exactly two canonical output formats**, landscape and portrait, auto-selected by majority vote across a job's photos, with a manual override.
4. **Built:** `_decide_job_format_from_bytes()` (majority vote) and `_normalize_photo_to_format()` (crop to the target ratio) in `api_server.py`; `assemble_property_video()` takes an `output_format` parameter and sets its canvas accordingly; a job's `output_format` is decided once at creation and stored on the job.
5. **Crop direction, real product decision, validated against real photos:** cropping height uses a **top-biased** crop (keeps more of the ceiling/window area, crops more from the floor) rather than a centered one — real estate portrait photos are usually shot to capture ceiling height. Cropping width (landscape photo into a portrait job) uses a plain centered crop. The top-bias amount is **proportional to the actual pixels being removed** (26% of the removed amount comes from the top), not a fixed offset — an earlier version used a fixed 15%-of-original-height offset, which worked for the severe case it was tuned on but badly over-cropped the top on ordinary near-16:9 photos (confirmed: a plain 3:2 photo would have had 96% of its (small) crop taken entirely from the top).
6. **Wired into every place a scene photo gets saved**, not just the main upload path: `create_job` (original), `add_scene`, `resync_draft`, `redo_scenes_batch`'s new-image handling, and `create_job_from_url` (the URL-scraper path) — the last of these was a real, separate gap found during the architecture assessment (see below), fixed by normalizing images after `scraper.download_selected_photos()` places them, before vision analysis runs.
7. **Manual override:** an "Output format" dropdown (Auto / Landscape / Portrait) exists in the UI for the main upload flow, wired to an `output_format` field the backend already fully supports.
8. **Confirmed via real generation, not just code review:** a genuinely new job now produces real portrait output end-to-end when the source photos are portrait, and the manual override correctly forces landscape when selected.

**Separately, real Luma camera-movement quality issue (not fully solved):** portrait clips hallucinate/distort noticeably faster during camera movement than landscape clips at the same settings — root cause understood (a 9:16 frame has roughly a third the horizontal field of view of 16:9 for the same shot, so the same movement consumes proportionally more of the real photographed content before the model has to invent what's beyond the edge). Not yet fixed — see backlog item 37; the existing Luma prompt system has no numeric degree value to simply reduce (unlike Veo's, which does), so this needs new prompt language, not a parameter tweak, and deserves its own dedicated pass rather than a quick patch.

**Also fixed the same day: human shadows/silhouettes occasionally appearing in Luma output.** Confirmed via direct code inspection that `_LUMA_RULES` already said "no people" explicitly — nothing in the prompt was asking for a person. Extended the rule to also explicitly exclude "human shadows or silhouettes," matching the established pattern of naming specific observed hallucination artifacts once seen in practice (same pattern as the existing "no falling objects, no floating particles, no leaves"). This is the same class of probabilistic mitigation as the rest of `_LUMA_RULES` — reduces the odds, doesn't guarantee against it.

### Cost model — a real, severe bug found via a direct real-world discrepancy

**User report:** a 10-clip Luma video, estimated at ~€5 by the app, actually invoiced ~$20 from fal.ai.

**Root cause, confirmed via fal.ai's own published pricing:** Luma Ray 2's base rate ($0.50/5s) is for its *default* resolution (540p) — **1080p costs 4x that base rate**, and this app always requests 1080p. The cost model had no resolution multiplier at all, and used a flat per-clip rate that also ignored actual scene duration (a 9s clip was priced the same as a 5s clip). Corrected model: `10 × $2.00 = $20` — an exact match to the real invoice.

**Fixed in `cost_tracker.py`:** new `video_cost_for_clip(model_tier, duration_secs)`, duration- and resolution-aware, replacing the flat `TIER_COST_PER_CLIP` lookup in all three cost functions (`estimate_job_cost`, `calculate_actual_cost`, `calculate_rework_cost`). Veo's rates were confirmed *not* to have a resolution multiplier (same price at 720p or 1080p, per fal.ai docs) — its old flat rate was accurate for exactly 8s clips, just didn't scale for the valid 4s/6s options, so Veo estimates were mildly *over*-priced for shorter clips, not under.

**A second, independent copy of the same broken pricing logic found in `ui.html`'s `updateCostEstimate()`** — the live client-side cost preview shown during job creation/rework, completely separate from `cost_tracker.py`, with its own hardcoded flat rates. This is the same duplication pattern as the buffer-constant issue found earlier in the week. Fixed to match the backend exactly; dropdown option labels (which advertised the old wrong per-clip prices) corrected too.

**Real recurring gap found during this investigation, separately fixed (see Architecture assessment below):** `/approve`'s QC-rejection redo path was still calling the legacy `run_rework()`, which never had cost tracking wired to it at all — meaning any job with a QC-flagged scene during first-time generation was silently missing cost tracking, independent of the resolution-multiplier bug.

### Redo/rework workflow — two real, separate reliability bugs

**Bug 1 — redo button routing depended on scene age, backwards from what's needed.** Modern scenes (with a `scene_id`) triggered `redoSceneNew()`, which submits *immediately* and locks the job right away; legacy scenes opened a staging panel, letting several scenes be marked before one combined submission. This meant marking more than one scene for redo only worked on old jobs — on a modern job, marking the first scene immediately locked the job, blocking selection of a second or third. Fixed: both paths now open the same staging panel; nothing routes through the immediate single-scene path from the UI anymore (the underlying function and endpoint still exist, `add_scene` genuinely depends on the function — see below).

**Bug 2 — a stale, in-flight polling cycle could silently wipe marked-for-redo scenes.** Confirmed real case: marked 3 scenes for redo, waited a few minutes, clicked "Genera video" — it silently did a plain narration reassembly instead of a batch redo, with zero error. Root cause: `showResult()` (called when polling detects a job reaching "done") unconditionally clears every scene's rework_open flag on every call. If an earlier polling cycle (e.g. from a preceding narration action) was still in flight when new scenes got marked, its delayed resolution could fire `showResult()` after the marking, wiping it out — `clearInterval()` stops *future* ticks but not an already-in-flight async callback. Fixed with an epoch guard: `startPolling()` now stamps each polling cycle with an incrementing counter, and any tick/callback that resolves after being superseded checks and bails out instead of acting on stale results.

### Architecture assessment — a full pass for duplicate/parallel workflow paths

Prompted directly by the cumulative pattern above (buffer constant duplicated 3x, cost calculation duplicated 3x, redo-button routing bug) — a full, systematic read through every API endpoint and background-task function to find every remaining instance of "more than one way to do the same thing." Full findings delivered as a standalone document (`architecture_assessment.md`); summary and current status:

1. **`/approve`'s QC-rejection redo path was still calling the legacy `run_rework()`** (sibling-directory model), the one remaining live path into it — and this is hit by ordinary usage (any first-time generation where QC flags a scene, which is common), not an edge case. **✅ Fixed** — now calls the same batch redo mechanism (`run_redo_scenes_batch`) as the manual "Rifai" button, with proper locking and scene_id mapping.
2. **`listing_scraper.py`'s own lead/trail silence buffer, suspected of being stale** (separate implementation from `narration.py`, never touched by the WhatsApp-trim fix). **✅ Checked, no fix needed** — its values (1.0s lead, 2.0s trail) already happened to be safe, coincidentally matching or exceeding the corrected manual-workflow values. Still a case of duplicated logic that could drift in the future, just not currently broken.
3. **`create_job_from_url()` never applied the format-detection/normalization photos get on the manual upload path.** **✅ Fixed** — same `_decide_job_format_from_bytes()`/`_normalize_photo_to_format()` now applied after the scraper downloads and places images, before vision analysis runs.
4. **`run_assembly()` and `run_reassemble_only()` were near-duplicate "assemble the final video" implementations**, with `run_assembly()` (used by first-time generation and clean QC-approval — i.e. the single most common code path in the whole app) missing the legacy-clip self-heal fallback the other had. **✅ Fixed, full consolidation** (explicit decision, not the lower-risk partial option, given confirmed evidence the self-heal fallback was safe here — `run_pipeline` itself still saves its own clips under the pre-scene_id legacy naming convention, so the fallback was already firing silently on every single first-time job). `run_assembly()` deleted entirely; all three former call sites (`run_pipeline`, `/approve`, and the existing redo/rework paths) now use `run_reassemble_only()`. Confirmed via a real, complete end-to-end generation test after deployment — video generation and assembly both work correctly. Rollback point noted before the change (commit `af826498c462729d0b5b1e31c8a3661ad5145b62`) in case a problem surfaced later; not needed.
5. **Two further UI-orphaned legacy paths confirmed, not yet deleted:** the singular `POST /jobs/{id}/scenes/{scene_id}/redo` endpoint (its function `run_redo_scene` is still genuinely needed — `add_scene` depends on it internally — but the *dedicated endpoint* has no remaining caller in `ui.html`) and `POST /jobs/{id}/rework` (confirmed via direct grep — zero references anywhere in `ui.html`). Both are safe deletion candidates for a future session; not removed yet, ran out of session time.
6. **`listing_scraper.py`'s narration/scene-duration derivation is a fully separate implementation from `narration.py`'s**, sharing no code, with its own constants and rules (a 5-7 scene band that has no equivalent in the manual workflow). This is the deepest, most valuable, and most involved item — genuinely unifying these is a real project, not a quick patch, and should be scoped as its own dedicated effort.

### Maintenance/credit alert — investigated, false positive, no fix made

A maintenance alert reported "Claude API: FAILING" despite a real, confirmed $18 account balance. Investigated directly: re-running the exact same check (`credit_monitor.py`'s `get_anthropic_status()`, a real 1-token API call, since Anthropic has no balance-lookup endpoint to poll) passed cleanly immediately after. The check makes only one attempt with no retry, so a single transient network/API blip at the exact 5-minute check interval would trigger a false alert with no way to distinguish it from a real problem. Not fixed — a one-retry-before-declaring-failure change would be a reasonable, low-risk future improvement if this recurs (see backlog item 41), but this specific instance is confirmed resolved with no code change needed.

### Library reorganization — requested, discussed, not started

User wants the job-history/library UI reorganized around clients → properties → jobs, replacing the old "main job + reworks" grouping (which no longer applies now that reworks happen in-place). Real context gathered for future scoping: an `agency_id`/`agencies.json` concept already exists (built for cost reporting), but **no "property" entity exists anywhere in the data model** — properties are currently just an implicit `property_name` string on each job, with no way to link multiple jobs (e.g. original + later reworks, or a property re-shot later) to the same property record. This is a real, non-trivial data-model addition, not a UI-only change. See backlog item 39.

---

## Standing safeguards

- Stale browser cache can cause subtle bugs — hard refresh to verify JS changes.
- **Terminal paste artifacts are a real, recurring hazard** — stray bracketed-paste characters (e.g. `^[[200~...~`) can silently corrupt or no-op a pasted command. If a command's expected output doesn't appear, check for this before assuming something deeper is wrong.
- **Terminal transfers above ~2-2.5KB/line are unreliable in this specific browser terminal** (confirmed corruption + one session crash, July 16, 2026) — use complete-file-via-GitHub-upload instead of chunked terminal paste for anything beyond a small patch.
- **Never include a destructive/wildcard filesystem command in the same message as a correction retracting it** — the correction must come before any pasteable block, never after (real data loss occurred this way, July 16, 2026 — see backlog.md item 34).
- Repo is public — never commit secrets; `.env` stays gitignored.
- Never paste real credentials (passwords, tokens) into chat as reusable secrets — treat anything that appears here as compromised and rotate it.
- Before trusting a git "ahead/behind" count, check for ambiguous local branch names (`git branch -vv`, `git show-ref`) — a stray local branch can masquerade as the remote tracking ref and produce misleading divergence numbers with no real data at risk.
- **Before trusting any cost, timing, or behavioral constant, check whether it's duplicated elsewhere in the codebase** — confirmed recurring pattern (July 21, 2026): the same underlying value/logic independently reimplemented in the frontend, the backend, and/or the URL-scraper module, drifting out of sync silently until directly investigated. When fixing one instance, actively search for others rather than assuming there's only one.
- **When checking whether a function is called anywhere, `grep` for the bare name, not `name(`** — functions passed by reference (`asyncio.to_thread(some_function, ...)`) have no literal `some_function(` substring and will be silently missed.
