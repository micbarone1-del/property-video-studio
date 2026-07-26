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

**Narration-first workflow:** fully implemented — draft-mode job creation, `/jobs/{id}/narration`, `/apply-durations`, `/reassemble-with-narration`, `/start-generation`. TTS generated and measured before video generation; durations confirmed before any video cost is incurred. **Note (July 22, 2026): the scene-count-DERIVATION logic in `listing_scraper.py` for URL-scraped jobs remains a separate implementation from `narration.py`'s scene-duration-REDISTRIBUTION logic — see "Architecture assessment" item 6 below — but the padding VALUES and MECHANISM are now unified (July 22 fix); only the scene-count-band/correction-pass logic (which manual jobs don't need at all) is still genuinely separate.**

**Job model:** single-directory-per-job, stable `scene_id`s, job locking. **As of July 22, 2026, only ONE assembly implementation exists** (`run_reassemble_only`, used by first-time generation, QC-approval, and every redo/rework path) and **only ONE redo/rework mechanism exists at all** (`POST /jobs/{id}/scenes/redo-batch`) — see "Architecture assessment" for the full consolidation history. The legacy sibling-directory model (`run_rework()`, `POST /jobs/{id}/rework`) and the singular `POST /jobs/{id}/scenes/{scene_id}/redo` endpoint have been deleted entirely (confirmed zero remaining callers before removal); `run_redo_scene()` the function was kept since `add_scene()` genuinely still depends on it.

**Test isolation:** `jobs/_test_scratch/` + `/test-scratch/` endpoint.

**Assembly:** `video_assembly.py` — MoviePy, explicit bitrate control. **Canvas is now dynamic** (landscape 1920×1080 or portrait 1080×1920), driven by each job's `output_format` — see the portrait/landscape section below.

**Watermark removal:** `watermark_removal.py` (fal.ai) — strips source-listing-site watermarks from uploaded photos.

**QC:** `vision_analysis.py` (Florence-2).

**Video library / job browsing UI:** rewritten July 22, 2026 as a collapsible **Client → Property → Job** tree (replacing the old, now-stale "main jobs and reworks" grouping built for the sibling-directory model) — see the July 22 section below and backlog item 39 for full detail.

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
5. **Two further UI-orphaned legacy paths.** **✅ Fixed, July 22, 2026** — both the singular `POST /jobs/{id}/scenes/{scene_id}/redo` endpoint and `POST /jobs/{id}/rework` (+ `run_rework()`) deleted entirely, confirmed zero remaining callers in `ui.html` before removal. `run_redo_scene()` the function was kept — `add_scene()` genuinely still depends on it.
6. **`listing_scraper.py`'s narration padding was a genuinely different MECHANISM from `narration.py`'s, not just a duplicated constant** — the scraper baked lead/trail silence directly into the audio file, while the manual workflow adds it as blank video frames at assembly time. **✅ Fixed, July 22, 2026** — this was actually causing a real, invisible double-padding bug on every scraped job (assembly's padding logic had no way to know the scraper's audio was already padded). Now the scraper's buffer constants alias the shared `narration.py` values, and it stores bare unpadded audio like manual jobs do, letting the one shared assembly function apply padding once. The scene-COUNT-derivation logic itself (the 5-7 scene band, shorten/extend correction passes) remains genuinely separate, since manual jobs don't need it at all — this narrower piece is still a real, valuable future unification, just smaller in scope than originally framed.

### Maintenance/credit alert — investigated, false positive, no fix made

A maintenance alert reported "Claude API: FAILING" despite a real, confirmed $18 account balance. Investigated directly: re-running the exact same check (`credit_monitor.py`'s `get_anthropic_status()`, a real 1-token API call, since Anthropic has no balance-lookup endpoint to poll) passed cleanly immediately after. The check makes only one attempt with no retry, so a single transient network/API blip at the exact 5-minute check interval would trigger a false alert with no way to distinguish it from a real problem. Not fixed — a one-retry-before-declaring-failure change would be a reasonable, low-risk future improvement if this recurs (see backlog item 41), but this specific instance is confirmed resolved with no code change needed.

### Library reorganization — ✅ fully built July 22, 2026

See the "July 21-22, 2026 (continued)" section below for full detail — Client → Property → Job hierarchy, new data model in `cost_model.py`, both job-creation forms, and the library UI rewrite are all done.

## July 21-22, 2026 (continued) — Architecture consolidation completed, Luma movement rewrite, and full client/property/job library reorganization

### Architecture consolidation — items 5 and 6 completed (all 6 items now done)

**Item 5 — retired remaining dead legacy redo/rework code.** `run_rework()` (the legacy sibling-directory model's background function) and the `POST /jobs/{id}/rework` endpoint that called it were deleted entirely, along with the singular `POST /jobs/{id}/scenes/{scene_id}/redo` endpoint (its underlying function `run_redo_scene()` was kept — `add_scene()` genuinely still depends on it internally, only the dedicated *endpoint* had zero remaining callers). Both confirmed via direct grep to have zero references left in `ui.html` before deletion. Verified via syntax check, AST-level name search, a real server restart, and live route-registration checks confirming the surviving endpoints (`/scenes/redo-batch`, `/scenes`, `/scenes/{scene_id}` DELETE, `/approve`) are all correctly registered and the deleted ones are correctly absent.

**Item 6 — unified narration padding between the manual and URL-scraper workflows.** This turned up a real, previously-invisible bug, not just duplicate code: the scraper baked its own lead/trail silence directly into the narration audio file (`build_final_audio_track()`), while the manual workflow adds padding as blank video frames at assembly time (`_overlay_narration_audio()`). Combined, every URL-scraped job was very likely being padded **twice** — assembly's padding logic measured the already-padded audio file's duration and added its own lead/trail on top, having no way to know the silence was already there. Fixed: `listing_scraper.py`'s `LEAD_SILENCE_SECS`/`TRAIL_SILENCE_SECS` now **alias** `narration.py`'s shared `LEAD_SECS`/`TRAIL_SECS` instead of being independent hardcoded values (was 1.0/2.0, now 1.0/1.0 — the trail buffer shrank slightly, since the shared value is now evidence-based from the WhatsApp-trim fix rather than the scraper's own less-justified original figure), and `create_job_from_url()` now stores the bare, unpadded narration audio — exactly like manual jobs — letting the one shared assembly-time function apply padding once, uniformly, for both workflows. `build_final_audio_track()` itself was kept (still used by `listing_scraper.py`'s own standalone `__main__` test script, just no longer called from the live pipeline). Verified via real import tests and direct value confirmation (`LEAD_SILENCE_SECS == narration.LEAD_SECS`, etc.) — a real scraped-job generation test would still be the ultimate confirmation, not yet run.

### Luma camera movement rewrite (backlog item 37, partial — general wobble addressed, portrait-specific issue still open)

Reported: wobbly, exaggerated manual-camera-style stepping rather than a smooth dolly-in. Root-caused by direct comparison against Veo's already-working `_VEO_MOVEMENT_TOKENS`: Luma's prompts were missing two ingredients Veo's had — explicit "3D dolly" terminology (a specific cinematography term implying smooth linear translation, vs. generic "camera movement" which a model can interpret many ways) and explicit foreground/background parallax framing — and had **no degree limits at all**, where Veo's had them throughout. All 11 `_LUMA_MOVEMENT_TOKENS` entries rewritten to add both, plus a direct negative instruction against the exact reported artifact ("no stepping or bobbing"). Same caveat as every other Luma prompt constraint in this file: a well-reasoned, evidence-based probabilistic improvement, not a guarantee — needs a real generation test to confirm. The portrait-specific camera-movement issue (narrower FOV consuming real content faster during movement) remains unaddressed — a separate, harder problem needing new prompt language, not covered by this pass.

### Claude API cost now folded into the displayed cost total (backlog item 31)

Confirmed real gap: `claude_usage` (real token cost for URL-scraped jobs — listing extraction, narration writing, photo quality ranking, vision analysis) was captured and stored on the job dict, logged to the server log, but never actually added into `cost_estimate`/`cost_actual`'s displayed total, and `ui.html` never read the field at all. Fixed: `estimate_job_cost()` and `calculate_actual_cost()` in `cost_tracker.py` now accept an optional `claude_cost_eur` parameter (0.0 default, so manual jobs — which never call Claude — are completely unaffected), folded into the total and returned as its own `claude_eur` field. `format_cost_display()` shows it as a new line when present; `ui.html`'s `showCostPanel()` already generically renders whatever lines the backend sends, so no frontend change was needed for it to show up correctly. Verified with a real computation: adding a known `claude_cost_eur` produced an exact matching increase in the total, and the display line rendered with the correct label and value.

### Old-job cleanup false-negative — investigated, original hypothesis disproven, diagnostic logging added instead of a guessed fix (backlog item 32)

The original hypothesis (`_load_jobs_from_disk()` resaves every job on every server restart, resetting the mtime the 7-day cleanup relies on) was checked directly against that function's actual code and is **false** — it's read-only, it never calls `_save_job()`. The two originally-reported stuck jobs are gone from disk now, meaning the real-world impact was a delay in cleanup, not a permanent block. Since there's no reproducible evidence left to diagnose a fix with confidence, added targeted diagnostic logging instead of guessing: the cleanup loop in `/diagnostics` now flags (via `log.warning`) any job whose `created_at` is meaningfully older than its file's mtime while that mtime is still within the 7-day safe window — the precise signature of a stale-mtime pattern — without logging anything for ordinary jobs. If this recurs, there will be real evidence to work from instead of reconstructing it after the fact.

### Full client/property/job library reorganization (backlog item 39)

Requested by the user, explicitly scoped through a short back-and-forth before building: full **Client → Property → Job** hierarchy (not just client → job), with a property able to have multiple independent jobs over time (an original video plus a later, separate reshoot — not just in-place reworks of the same job, which don't create a new job entry at all). Explicit product decisions: assign a client at job creation time, but keep it editable afterward too; and reserve space now for a future client-logo-overlay feature (backlog item 7) without building it yet.

**Data model (`cost_model.py`) — single shared source of truth, not a separate library-only concept, per the explicit architecture-discipline principle:**
- New `Property` entity (`properties.json`): `list_properties()`, `create_property(name, agency_id, notes)` (idempotent per name+agency, matching `create_agency()`'s existing pattern), `get_property()`, `update_property_agency()` (reassign a property to a different current client without retroactively touching jobs already linked to it — each job's own `agency_id` reflects who actually commissioned that specific job, which must stay historically accurate).
- `create_agency()` now reserves a `logo_path: None` field on every new agency — backlog item 7's future overlay feature, field only, not built. Existing agencies created before this change correctly don't have the key; anything reading it must use `.get("logo_path")`.
- New `property_report()` in `cost_model.py`, mirroring the existing `agency_report()` pattern exactly: per-property production-cost rollup, the concrete link between "cost" and "library" the user asked for.

**Job creation (`api_server.py`) — both paths, reusing the existing `property_name` field rather than adding a redundant one:**
- `create_job()` and `create_job_from_url()` both gained an optional `agency_id` form parameter, and both now call `cost_model.create_property()` using the property name the job *already* captures for display purposes — no second, parallel "property name" field was introduced.
- `POST /jobs/{id}/commercial` (the existing cost-modal endpoint) now also accepts an optional `property_name` to assign/reassign a job's property link after creation — satisfies "assign at creation, still editable after" with one endpoint doing both jobs, not two.
- New endpoints: `GET`/`POST /properties`, `GET /reports/properties`.
- `GET /jobs/` now includes `agency_id`/`property_id` in each job's summary — it previously omitted both entirely, which would have silently broken the library rewrite below.

**Frontend (`ui.html`):**
- Both job-creation forms (manual upload, URL-scrape) gained a "Cliente" dropdown, populated from the same `/agencies` endpoint the cost modal already uses (one shared fetch function, `populateAgencyDropdowns()`, no duplicate agency-list logic) — defaults to "— Nessun cliente —".
- `loadLibrary()` fully rewritten: replaces the old "group by stripping the `_rw` suffix" logic (built for the legacy sibling-directory rework model, stale now that reworks happen in-place with no sibling jobs created) with a collapsible **Client → Property → Job** tree, reading the newly-added `agency_id`/`property_id` fields plus `/agencies` and `/properties` for display names. Legacy jobs predating this feature (no `property_id` at all) correctly land in a "Senza proprietà" bucket under "Nessun cliente" rather than being hidden or erroring.

**Real client data corrected during testing:** verification calls against `cost_model.py` created test agencies/properties that got committed alongside the real work; cleaned up immediately after (removed the test entries, confirmed both real clients — Andrea Sciurpa Immobiliare and Sinergie Immobiliari, the latter had been missing entirely — exist correctly).

**Not yet done / real next steps for this feature:**
- All 11 of the user's existing jobs predate this feature and currently show under "Nessun cliente → Senza proprietà" — expected, not a bug, but worth a manual pass to assign real clients/properties to historical jobs if that history matters for reporting.
- Backlog item 7 (client logo overlay) can now be built on top of the reserved `logo_path` field without any further data-model change.
- A real end-to-end click-through (create a job with a client selected, confirm it appears correctly grouped in the library) has not yet been performed by the user — recommended before considering this fully closed.

### A recurring deployment snag this session, worth remembering explicitly

Twice, a `git pull` reported "Already up to date" when a just-delivered file update was expected — in both cases the real cause was that the GitHub-side upload-and-commit step hadn't actually completed yet (or the wrong/earlier file had been re-uploaded), not a technical bug. The reliable diagnostic: `git fetch origin` then compare `git rev-parse HEAD` against `git rev-parse refs/remotes/origin/main` directly, and check the actual commit's line-change count against what the real patch should contain (e.g. "43 insertions" vs. the "~108 insertions" the actual pending change should have) — this catches "the wrong version got uploaded" mistakes that "already up to date" alone doesn't explain.

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
- **GitHub can serve stale content from its own upload/serving path even after a genuine re-upload and browser hard-refresh** (July 22, 2026) — distinct from browser cache or Claude's own fetch cache. Verify against the live server directly before assuming a fresh re-upload didn't take.
- **A `git pull` reporting "Already up to date" when a new file was just uploaded usually means the GitHub-side upload/commit step didn't actually happen (or the wrong file version was uploaded)** — not a technical bug. Diagnose with `git fetch origin` then compare `git rev-parse HEAD` against `git rev-parse refs/remotes/origin/main` directly, and sanity-check the real commit's line-change count against what the pending patch should contain.

## July 22-23, 2026 (continued) — Per-scene audio buffer, investment ledger management, audio-only rework, and a real process lesson

### Real bug: per-scene voiceover audio had zero lead-in silence

**Reported by the user, confirmed real:** the first fraction of a second of speech was getting cut when a video was forwarded through a messaging app -- the same class of problem as the earlier (July 17) WhatsApp-trim fix, but a genuinely different, previously-unaddressed mechanism. That earlier fix only touched `narration.py`'s LEAD_SECS/TRAIL_SECS, used by `_overlay_narration_audio()` for the continuous-narration-track workflow. Per-scene voiceover audio (used by older-style, non-narration-first jobs) is positioned in `video_assembly.py`'s `assemble_property_video()` via a completely separate code path, which started each scene's audio at the exact instant the scene began, with no buffer at all.

**Fixed:** added `SCENE_AUDIO_LEAD_SECS`/`SCENE_AUDIO_TRAIL_SECS` (0.5s each -- deliberately smaller than narration.py's 1.0s, since a per-scene clip has a much tighter, fixed time budget of 5-10s that cannot be extended the way a full video's total length can). The image-fallback branch (no real generated video, built from a static photo) extends its own clip duration to fit the buffer; the real-video branch fits available speech into a smaller window (clip.duration - lead - trail) since that clip's duration is fixed and can never change. Whether 0.5s is sufficient for real-world cross-platform re-encoding behavior (not just the pure AAC-encoder-priming mechanism, which is much smaller) is not yet confirmed by a real test -- see the new audio-only rework feature below, built specifically to let this be tested cheaply.

**A genuinely difficult patch to land:** two earlier attempts failed before reaching the live file -- one hit a missed blank line in the anchor text (a recurring class of issue this project has hit before), the other hit base64 transfer corruption in the terminal. Both were caught by direct verification (checking the actual file content, not trusting a script's own success message) before either reached the deployed file.

### Investment ledger management (backlog item 33 follow-on)

**User request:** track the real cost of this Claude Pro subscription (€21.96/month) as part of the project's overall investment tracking, not just the URL-scraper's per-job Claude API usage (already fixed, item 31).

**Found:** an investment ledger already existed (`cost_model.py`'s `investment.json`, driving the "Investimento (fisso)" figure in the cost report), but had zero way to add a single entry -- only a full-ledger replace (`set_investment()`), apparently intended for an XLS re-upload workflow that was never actually built.

**Built:** `add_investment_entry()`/`delete_investment_entry()` in `cost_model.py` (append/remove one entry without disturbing the rest -- correctly reuses the existing "note" field name the original XLS-imported entry already used, not a second, inconsistent field). New `GET`/`POST /investment`, `DELETE /investment/{index}` endpoints. UI: a new Investment section in the cost modal (same lightweight style as the Sales section), with an add-entry form. The real Claude Pro entry (€21.96) was added to the ledger -- its note text explicitly flags that a new entry should be added each billing cycle to keep this current, since there's no automatic recurring-cost mechanism.

### Audio-only rework (new capability)

**User request, directly motivated by wanting to test the new audio buffer without paying for video regeneration:** can TTS be reworked on an existing video without redoing the (expensive) video generation too?

**Confirmed gap:** the existing redo-batch mechanism (`run_redo_scenes_batch`) always regenerates video for any marked scene -- there was no way to regenerate just the audio.

**Built:** `run_redo_audio_only()` in `api_server.py`, mirroring the relevant slice of `run_redo_scenes_batch()` but skipping every video-generation step entirely -- regenerates TTS for marked scenes using their existing voiceover text, reuses their existing video clips completely untouched, and reassembles via the same shared `run_reassemble_only()` every other path uses (no separate assembly logic). New `POST /jobs/{id}/scenes/redo-audio-only` endpoint. Cost tracking correctly reflects this as audio-only (`redo_video=False`), so it only ever incurs the cheap ElevenLabs charge, never a Luma/Veo one. UI: a new "Rigenera solo audio" button next to the main Generate button, active whenever scenes are marked for rework, calling the new endpoint via a function that mirrors `submitRework()`'s scene-collection logic exactly.

**Not yet done:** a real end-to-end test (mark a scene, click the new button, confirm audio changes and video doesn't, confirm cost tracking shows only the ElevenLabs charge) has not yet been run by the user.

### A real process lesson this session: forgetting to commit

**What happened:** the investment-ledger backend (cost_model.py, api_server.py, the real Claude Pro entry, and a backlog.md update) was applied and tested directly on the server, but never committed to git before moving on to the TTS-buffer and audio-only-rework conversation. When the user later uploaded a fresh `api_server.py` (containing the audio-only-rework feature) to GitHub and the server tried to `git pull` it, git correctly refused: "Your local changes... would be overwritten by merge."

**Fixed cleanly:** committed the pending local changes first, then `git pull --no-rebase` merged the two independent sets of changes with zero real conflict (they touched different parts of the same file), verified both sides survived the merge (both the investment endpoints and the audio-only-rework endpoint present and working), then pushed.

**Lesson, now a standing practice:** after applying any change directly on the server via terminal, commit it before starting a new, unrelated task -- even when the immediate conversation moves on to something else first. An uncommitted change sitting on the server is invisible until it collides with the next upload.
- **After applying any change directly on the server via terminal, commit it before starting a new, unrelated task** (July 23, 2026) -- an uncommitted local change is invisible until it collides with the next upload/pull, producing a real merge conflict.


## July 23-24, 2026 (continued) — Three real bugs found via real-world testing: a moviepy audio bug, a stale scene-count display, and a TTS cost-tracking gap

This entire stretch was prompted directly by the user actually using the app on a real job (07079eed) and reporting what they saw, rather than trusting either function's own logged output. All three were caught this way, not through code review.

### Major root-cause bug: moviepy's `.with_audio()` silently ignores `.with_start()` unless wrapped in `CompositeAudioClip`

**Reported:** after generating new narration and reworking a scene, the voiceover still started at time 0 with no lead-in buffer — despite both of this session's earlier buffer fixes (the continuous-narration one and the per-scene one).

**Root cause, confirmed via an isolated moviepy test:** `videoclip.with_audio(audioclip.with_start(t))` completely ignores the audio clip's `.start` offset when the clip is attached directly — a 2-second test tone shifted with `.with_start(1.0)` played from t=0 exactly as if no offset existed, going silent at t=2.0. Wrapped in `CompositeAudioClip([tone])` instead, the same clip correctly played from t=1.0. This single moviepy behavior meant:
1. `_overlay_narration_audio()` in `api_server.py` computed and *logged* the correct `lead=1.00s trail=1.00s` every single time, but the value never actually reached the rendered file — the continuous-narration buffer fixed earlier this session had been completely ineffective the entire time.
2. `video_assembly.py`'s `audio_segments` handling had the identical bug for any job with only one audio-carrying scene (`CompositeAudioClip(positioned) if len(positioned) > 1 else positioned[0]` bypassed the composite wrapper for exactly the single-clip case) — silently breaking this session's per-scene `SCENE_AUDIO_LEAD_SECS` fix for a one-scene job, the single most common case.

**Fixed:** always wrap in `CompositeAudioClip`, even for one clip, in both locations. **Verified directly on the real problem job**, at no cost (reused the existing narration.mp3 and video clip): real audio-volume measurements at 0.1s intervals confirmed silence from 0-0.9s, speech exactly from 1.0s, and silence again after 3.6s — matching the intended 1.0s lead + 2.6s narration + trail exactly.

**User-confirmed in the real world:** the buffer now survives being sent via email and forwarded through WhatsApp without the first fraction of a second being cut — the original, real-world symptom this whole investigation started from.

### Real bug: stale scene-count display after a rework

**Reported:** the job preview header showed "14 scenes" when opening the job for rework, then "2 scenes" after initiating a narration-only rework — for a job whose real scene count was 1 the entire time.

**Root cause, confirmed:** `showResult()` computed the displayed scene count from `job["scenes"]` — a per-scene video/audio/QC status-tracking array that only ever gets appended to or updated by `scene_id`, and is never trimmed down when scenes are actually removed from a job — instead of from `scenes_config` (the authoritative, current scene list). Confirmed directly on the real job: its status array carried an orphaned legacy entry with no `scene_id` at all, alongside the one real, current entry — exactly 2 entries for a 1-scene job.

**Fixed:** `scenes_config.length` is now passed through to `showResult()` and used as the primary source, falling back to the old (imperfect) logic only if genuinely unavailable. This is the same class of issue as several other bugs fixed this session — two different values both claiming to answer "how many scenes does this job have," free to drift apart over the job's lifetime. The earlier "14" was not fully traced to a specific line of code — the one place that specific header text originates from doesn't display a count at all, so it likely reflects a different, harder-to-reproduce moment; if it recurs, the exact click sequence beforehand would help pin it down.

### Real cost-tracking gap: narration regeneration never recorded its own cost

**Reported:** "still missing TTS cost estimation when I run a rework."

**Confirmed:** `/jobs/{id}/narration` (regenerating the continuous narration track) makes a real, billable ElevenLabs TTS call every time it runs, but had never recorded that cost anywhere in the job's `cost_actual` — a rework involving narration regeneration would show no TTS cost for that step at all, independent of whatever scene-redo costs were separately tracked.

**Fixed:** reuses the exact same `calculate_rework_cost()`/`format_cost_display()` pattern already used for scene reworks and the audio-only-rework feature (`redo_video=False`, `redo_audio=True`, `audio_chars=len(narration_text)`), rather than inventing a second, parallel cost calculation. Verified the underlying math in isolation (an 80-character sample correctly produced €0.024, with video/vision costs correctly at zero) without triggering a real, billable TTS call just to confirm it.

### A note on how these were found

All three bugs were only discoverable by watching the real, rendered output of a real job the user was actually working on — none were visible from code review, from the functions' own log output (which was, in the audio bug's case, actively misleading — it logged the *intended* values, not what actually happened), or from any of this session's earlier backend-level verification (curl calls, direct Python function tests). This reinforces a standing lesson from earlier tonight: a function's own success message or log line is not proof of the real, physical result — direct measurement of the actual output (audio volume levels, file duration, on-disk byte content) is what actually confirms a fix works.


## July 24-26, 2026 — Backlog item 35: premium ~1-minute video template (URL-scrape only)

**Fully scoped and built, function-level tested, not yet confirmed via a real live scrape** (deferred by explicit user choice — the isolated logic tests were judged sufficient for now).

### Scope, as explicitly decided through discussion (not assumed)

- **Manual toggle at job creation**, not automatic/price-based, not a per-client default. Applies to the **URL-scrape workflow only** — the manual upload form is untouched.
- **Extended taxonomy**, not just "more scenes of the same 6 categories": a "main" + expanded-instance structure per room type (e.g. multiple bedrooms/bathrooms/outdoor spaces shown, not just one), reusing `rank_photos_by_quality()`'s existing best-first ordering as the "main vs small" signal — no new quality mechanism was needed, since that ranking already combines pure visual quality with content representativeness ("clearly shows a visible bed for a bedroom"), exactly matching what the user separately asked for on the quality dimension.
- **Outdoor placed twice**: once right after the facade (early), once again at the closing — an explicit videography/storytelling decision, not a technical default.
- **Two new optional categories added to the extraction prompt**: `laundry` (previously lumped into `bathrooms`), `office`, `garage` — used only when premium and only when actually present in a listing.
- **Explicit three-tier fallback when a category is sparse**, in this exact priority order, confirmed and kept as specified (not changed after review): (1) expand instances in other large-room/outdoor categories that have surplus, prioritizing outdoor and large rooms, (2) add categories not in the base template (laundry/office/garage) if present, (3) last resort — reuse additional photos of the same room/space. **Real, confirmed behavior worth knowing:** tier 1 is exhausted fully before tier 2 ever runs — a photo-rich listing with plenty of core-category surplus will not necessarily include a laundry/office/garage shot even if one exists, since expanding existing large rooms/outdoor takes strict priority. This is the literal, explicitly-confirmed priority order, not an oversight.
- **If the full 3-tier cascade still can't fill the sequence:** a clear error is returned suggesting the standard ~30s format or manual upload — an explicit product decision, not a silent degradation.

### What was built

- `EXTRACTION_PROMPT` extended to recognize `laundry`/`office`/`garage` as their own categories (previously `laundry` was silently folded into `bathrooms`).
- `MIN_SCENES_PREMIUM`/`MAX_SCENES_PREMIUM` (11-13, ~55-65s) and the matching speech-range constants, computed the same way as the existing standard-format ones.
- `generate_narration_and_derive_scenes()` gained an optional `premium` parameter, switching between the standard and premium range constants rather than duplicating the whole shorten/extend/scene-count-derivation block.
- `select_photos_for_scene_count_premium()` — a new, dedicated function (kept separate from the standard one since the sequencing logic is genuinely different, not just a wider number range): splits the outdoor category into `outdoor_early`/`outdoor_late` pseudo-categories up front, then runs the four-pass selection (core categories → tier-1 expand → tier-2 new categories → tier-3 last-resort reuse).
- `build_premium_video_scenes_config()` — the premium counterpart to the existing scene-config builder, mapping the pseudo-categories back to their real category names for caption/space-type/pov-movement lookups.
- **A real architecture-discipline catch mid-build, per explicit reminder:** the categorize-and-rank-photos setup step was initially duplicated identically between the standard and premium selection functions. Extracted into a shared `_categorize_and_rank_photos()` helper before deployment, used by both. Also found and deleted a genuinely dead, zero-caller function (`select_photos()`, an older, unused selection mechanism predating `select_photos_for_scene_count()`) discovered during this same pass.
- `api_server.py`'s `create_job_from_url()`: new `premium: bool = Form(False)` parameter, branching to the premium functions above when true, an `is_premium` flag stored on the job for classification/reporting, and the gap-message fallback suggestion (standard format / manual upload) when premium's photos aren't sufficient.
- UI: new "Premium (video ~1 min)" checkbox on the URL-scrape form.

### Verification performed (zero cost, isolated function-level tests)

- `select_photos_for_scene_count_premium()`: a rich-listing scenario (plenty of every category) correctly hit the 12-scene target with outdoor appearing in both early and late positions with genuinely different photos; a sparse-bathroom-but-rich-outdoor scenario correctly expanded outdoor to fill the gap; a genuinely-too-few-photos scenario correctly reported a gap rather than silently under-delivering. Re-verified after the dedup refactor — identical results.
- `select_photos_for_scene_count()` (standard, unchanged behavior): re-verified still correct after the refactor.
- `generate_narration_and_derive_scenes()`: confirmed the premium/standard branching produces the correct scene-count range in each mode (28s speech → 5 scenes standard; 58s speech → 11 scenes premium) using a real, temporary audio file so the existing "prefer tightest fit" trimming logic could run for real, with Claude/TTS calls mocked to avoid any actual cost.

**Not yet done:** a real, live scrape of an actual listing (real extraction, real narration text, real photo categorization from a real site) has not been run — the user explicitly declined this for now, judging the isolated tests sufficient. Worth running before fully trusting this in production, given the standard-format equivalent of this feature has a much longer track record of real use.
