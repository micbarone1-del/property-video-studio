# Property Video Studio — Status

_Last verified: July 8, 2026 — full audit of all 25 repository files, read directly (not summarized from memory or prior chats). Server and GitHub `main` confirmed in sync as of this audit (see Infrastructure Note)._

## Architecture — live production pipeline

**Backend:** FastAPI (`api_server.py`, current version — a prior audit this session mistakenly read a stale cached snapshot of this file; that error has been corrected here).

**Auth:** Conditional — gated by `X-Access-Key` header against a `UI_ACCESS_KEY` environment variable if one is set; open access if the env var is unset. (Not independently confirmed whether `.env` on the server actually sets this, since `.env` is gitignored and wasn't read.)

**Video generation (`video_generation.py`) — four tiers, all fully implemented and live:**
- **`eco`** — Lyra 2.0 zoom (`fal-ai/lyra-2/zoom`) + Topaz upscale 720p→1080p. ~€0.045–0.125/clip by frame count. Lyra is parametric (camera controlled via API params, not prompt) — uses a frozen-scene prompt style, distinct from Veo/Luma's motion-description prompts.
- **`luma`** — Luma Ray 2 (`fal-ai/luma-dream-machine/ray-2/image-to-video`). **Current default**, selected in `ui.html`. ~€0.46/clip. Confirmed via real testing: genuine 3D parallax, no warping, including on the bathroom photo that previously broke both depth rendering and Veo. Automatic fallback to Veo 3.1 Fast on failure.
- **`premium`** — Veo 3.1 Fast, native 1080p. ~€0.80/clip.
- **`premium_veo`** — Veo 3.1 Standard (`fast_mode=False`). ~€1.60/clip. Explicitly built and labeled to avoid the circular/internal transition problem ("no circular wipe" in both UI and code comments). Falls back to Veo Fast on failure.
- Model tier is selected in the UI dropdown and passed through the job config to `generate_video_single` — fully wired end to end.
- **Kling: fully removed from all functional code.** Two harmless dead comments remain (`video_generation.py`, `cost_tracker.py`) referencing Kling for historical prompt-design rationale only.

**Narration-first workflow:** fully implemented — draft-mode job creation, `/jobs/{id}/narration` (TTS-only step), `/apply-durations`, `/reassemble-with-narration`, `/start-generation`. TTS is generated and measured before video generation, durations confirmed in UI, video generated to match. Valid duration snap values account for both Veo (4/6/8s) and Luma (5/9s) — see `narration.py`.

**Job model:** single-directory-per-job, locked/stable `scene_id`s, 0-indexed scene numbering throughout UI and server. Job locking prevents assembly race conditions. New rework endpoints (`redo_scene`, `add_scene`, `delete_scene`) use strict scene-index bounds — the fix for the earlier test-clip contamination incident is present and confirmed. The old sibling-directory `/jobs/{id}/rework` endpoint still exists but is explicitly marked legacy in code, kept only for in-flight old jobs — no new work should build on it.

**Test isolation:** `jobs/_test_scratch/` + `/test-scratch/` endpoint, confirmed implemented as documented.

**Assembly:** `video_assembly.py` — `assemble_property_video()`, MoviePy-based, explicit bitrate control, transition styles (fade/fade_white/slide_left/slide_right/cut).

**Watermark removal:** `watermark_removal.py` (fal.ai object-removal) — strips source-listing-site watermarks from uploaded photos. Distinct from the planned client-logo overlay feature (backlog), which would add the agency's own logo rather than remove anything.

**QC:** `vision_analysis.py` (Florence-2-based).

**Cost tracking:** `cost_tracker.py` — per-tier billing (frame-based for Lyra, per-second for Veo/Luma), rolling 30-day job count for infrastructure cost-per-video.

**Credits:** `credit_monitor.py`, exposed via `/credits` endpoint.

**Streaming:** Range-request streaming implemented on both `/clip/` (preview) and `/download` endpoints.

**Retention:** auto-cleanup of jobs older than 7 days, confirmed in code.

## Present in repo but NOT part of the live pipeline (legacy / standalone)

Flagging these explicitly so they aren't mistaken for active code in future sessions:

- **`main.py`, `communication.py`, and the CLI paths in `video_assembly.py`/`video_editor.py`** — a self-contained legacy automation (Excel-via-email intake, Google Drive upload, email delivery, using `StorySequencer`/`VideoCompositor`). Confirmed disconnected from the live API: `communication.py`'s Google API dependencies aren't even listed in `requirements.txt`. Note: `video_editor.py`'s legacy path has its own logo-overlay support (`show_logo`/`logo_path`) — relevant context for scoping the client-logo backlog item, but not directly reusable since it's a different code path from the live `assemble_property_video()`.
- **`depth_renderer.py`** — a genuinely sophisticated, complete implementation (percentile normalization anchored to frame center, edge-gradient damping at depth discontinuities, bilateral filtering, motion blur, disocclusion inpainting). Includes a `measure_depth_score()` function intended for auto-routing flat/shallow scenes to depth-rendering vs. deep scenes to Veo — **this routing logic exists but is not called anywhere in `api_server.py`**, so it's not active in production. Kept for reference; Luma Ray 2 has pragmatically solved the problem this was built for.
- **`batch_depth_test.py`** — parameter-comparison test harness for `depth_renderer.py`. Standalone, not imported elsewhere.
- **`test_luma.py`** — standalone script that validated Luma Ray 2 against the bathroom photo before it was merged into `video_generation.py`. No longer needed for that purpose but harmless to keep.
- **`reassemble_fix.py`** — a one-off manual repair script hardcoded to a specific past job ID (`161dfaf7_rw9f6a`). Not a reusable tool; an artifact of a prior incident fix. Candidate for deletion.

## Resolved / corrected this session (July 8, 2026)

- **"Kling routing unverified"** — closed, confirmed no functional Kling code exists.
- **"Luma Ray 2 needs integration"** — closed, already fully implemented and already the default.
- **"Veo circular/internal transition"** — upgraded from "on hold" to resolved in code (`premium_veo` tier exists specifically to fix this); recommend one real test clip for visual confirmation before considering it fully closed.
- **Earlier in this same session, an incorrect audit was reported** claiming `video_generation.py` only used a bare `fal-ai/ltx-2.3` endpoint with no tier system — this was based on a stale/cached fetch and was wrong. Corrected via direct terminal `grep` and full file reads.

## Open items

- **Rework edge cases (watch item, no known repro):** full end-to-end test passed; possible fixes may still be needed for specific use cases. Flag with a concrete repro when one surfaces.
- **Video library & job browsing UI:** reported as implemented (user, July 8, 2026) — not yet independently code-verified. Needs confirmation of scope and whether it changes the 7-day retention window.
- **`.env` contents** (auth key presence, API keys) not verified — file is correctly gitignored and wasn't read.

## Infrastructure note — GitHub/server sync gap (found & fixed July 8, 2026)

GitHub `main` was 3 commits behind the live server at the start of this session (2 `status.md` commits + 1 `backlog.md` commit existed on GitHub but hadn't been pulled to the server). Reconciled via clean fast-forward merge (commit `08905c6`) — no data lost, no conflicts. **Standing precaution:** verify sync in both directions at the start of any code-work session (`git status` on server; `git fetch && git log HEAD..origin/main --oneline`) before treating either side as authoritative.

## Standing safeguards (unchanged)

- Stale browser cache can cause subtle bugs — hard refresh to verify JS changes.
- Terminal paste artifacts are a real hazard — stray characters from pasting can silently corrupt commands.
- Repo is public — never commit secrets; `.env` stays gitignored.
