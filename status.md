# Property Video Studio — Status
_Last updated: July 8, 2026 (reconstructed from full project conversation, June 10 – July 7, 2026)_

Repository of record: `github.com/micbarone1-del/property-video-studio`
Deployment: Hostinger VPS, isolated at `/var/www/property-video-studio/` (fully separate from the original Gustavo Matos `newsletter` codebase, which remains untouched). Runs via `uvicorn api_server:app` inside a `screen` session / `property-video.service` systemd unit.

## Architecture

- **Backend:** `api_server.py` (FastAPI) — replaces the original email-polling interface entirely.
- **Frontend:** `ui.html` — single-file drag-and-drop UI with a login screen (access-key based).
- **Pipeline modules:**
  - `video_generation.py` (v7) — three-tier model routing: Lyra 2.0 (budget), Veo 3.1 Fast (default, "Professional"), Veo 3.1 Standard (flagship).
  - `voice_generation.py` — ElevenLabs TTS, modified to support the narration-first flow.
  - `video_assembly.py` / `video_editor.py` — MoviePy assembly, logo watermark, transitions, captions.
  - `image_enhance.py` — fal.ai upscaling + PIL auto-levels/shadow-lift/white-balance.
  - `credit_monitor.py` — fal.ai + ElevenLabs balance checks, in-UI banner + email alerts (Gmail app password).
  - `cost_tracker.py` — EUR cost estimation (pre-generation estimate, actual cost, rework incremental cost, running total).
- **Original Gustavo files** (`communication.py`, `main.py`, original `video_generation.py`, etc.) remain on the server, unused, for isolation/rollback purposes only.
- **Job model:** as of July 3–4 a redesign was agreed — one stable job directory per property (no more `_rwXXXX` sibling chains), persistent per-scene UUIDs, job locking (409 on concurrent requests), and dedicated add/delete-scene endpoints. **Status unclear**: the same day's logs still show sibling rework directories (`161dfaf7_rw5a78`, etc.) being created and manually patched around. I found no later confirmation that the sibling-chain pattern was actually replaced in deployed code. Treat as designed/prioritized, not confirmed shipped.
- **Draft-mode job creation (narration-first workflow):** `create_job` now supports `start_generation=False` (saves photos/scene config at zero cost); a new `POST /jobs/{id}/start-generation` endpoint triggers generation once narration/durations are confirmed. Backend and frontend wiring both confirmed complete as of July 7.
- **Stopped-job status:** cancelling a job now sets status to `"stopped"` with an explicit "N of M scenes completed" message, distinct from a genuine `"failed"`, so reassembly can safely resume. Confirmed complete July 7.

## Feature Status

### Done
- Web UI with login screen, replacing the email interface entirely.
- Isolated VPS deployment, original system left running/untouched in parallel.
- Image upscaling + lighting optimization.
- Credit/balance monitoring (fal.ai + ElevenLabs) with both in-UI banner and email alerts.
- Cost estimation panel (pre-generation estimate → actual → rework increment → running total, in EUR).
- Rework / selective scene regeneration capability (functional, but historically fragile — see Known Issues).
- Auto-duration estimation from narration word count; camera-movement hints per scene.
- Logo watermark burned into output video (bottom-right corner).
- Three-tier model routing (Lyra 2.0 / Veo 3.1 Fast / Veo 3.1 Standard).
- "Space characteristics" dropdown (depth-of-space + edge-of-space questions), replacing unreliable keyword-based space-type inference.
- Structured, dropdown-driven prompt assembly (no free text) with POV framing for Veo, replacing the original vision-model free-write approach that caused frequent hallucinations.
- Full original image always sent to Veo/Lyra — cropping is used only as prompt-hint language, never as an actual pixel crop (fixes hallucinated fill during "reveal" shots).
- `reveal_pullback` movement added for building facades.
- QC exterior/interior misclassification fixed (moved from keyword-block to score-based `outdoor_score`).
- "Hands appearing in frame" fixed (removed literal "First-person POV shot" phrase from the prompt template).
- Veo Standard added as a third selectable tier in the UI.
- TTS/video duration-sync fixes: corrected audio timeline-cursor ordering, corrected duration-rounding (snap up, not down), corrected cross-scene overlap caused by fade-transition timing.
- Auth key persistence fixed (moved from `sessionStorage` to `localStorage`) to stop confusing mid-job 401/403s.
- Login screen, auth middleware, and systemd auto-start (v3 security release).
- Narration-first workflow fully wired end to end (July 7): generate narration → auto-creates draft job → confirm durations → "Genera video" correctly triggers `/start-generation`.

### In progress / partial — do not treat as fully done
- **Job/rework architecture rebuild** (single directory per property, persistent scene UUIDs, locking): agreed and prioritized, but deployment status is unconfirmed — see Architecture note above.
- **Auth middleware may currently be disabled in production.** On July 3, auth was deliberately hard-disabled directly in `api_server.py` (`if False and not _check_access(request):`) to unblock a stuck job, with explicit instructions to re-enable it afterward. No later message in the conversation confirms this was actually done. **Treat this as a live, unresolved security exposure, not a resolved one.**
- **Circular/internal transitions bug:** root-caused to fal.ai's own Veo output baking in transitions when `fast_mode=True`. This appears to be an upstream/model-side limitation, not something fully fixable from this codebase — only partially mitigated.
- **Add-scene-to-existing-job frontend bug:** adding a 9th scene to an 8-scene job was showing only 2 of the expected scenes. Backend `scenes_config` was confirmed correct; the bug was isolated to the frontend `editJob` fetch logic for the new scene's image. Diagnosis only — no confirmed fix.
- **Kling model support:** tested live and explicitly rejected by the user for this use case (small rooms produced a flat 2D zoom, no 3D effect). A Kling-specific prompt vocabulary was built as an attempted fix, but Kling was dropped from the default tier list. It remains a candidate only for a future human-character feature, which was never built.
- **The July 1–2 comprehensive bug complaint** (QC misclassifying interior/exterior, hands in frame, circular transitions, hallucinated new rooms/exits, 2D zoom, TTS desync — user's own words: "looks like you have fixed nothing") prompted a follow-up round of individual fixes (QC scoring, hands-phrase removal, Kling removal, TTS snap-up correction). **I found no later message where the user confirmed a clean, full end-to-end retest after these fixes landed together.** These should be described as "fixes attempted, not yet confirmed by a clean retest," not as resolved.

### Discussed but never implemented
- Multi-job dashboard with a concurrent queue (target: max 3 parallel jobs, based on account rate limits).
- Automatic maintenance scheduler.
- Watermark removal from input photos (distinct from the logo watermark added to output, which is done).
- Portrait/vertical video format support (blocked on model support — Lyra/Veo primarily support landscape).
- Human characters in generated video (conceptually routed to Kling 2.6 Pro for character/motion realism).
- Virtual furniture staging (noted by the user as related to the human-characters feature).

## Bugs Fixed
See "Done" list above for the full chronological set. Highlights: tuple-unpack crash in `download_asset()`, process-killing `sys.exit(1)` on scene mismatch, swapped argument order in `mass_generation()`, undefined `output_path`, caption/title mismatch in `prepare_pipeline_config()`, hardcoded `.png` extension corrupting jpegs, fragile Excel boolean parsing, hardcoded nonexistent transition file paths, TTS/video duration desync (three distinct causes, all fixed), sessionStorage-based auth logout bug, QC interior/exterior misclassification, hands-in-frame prompt bug, Veo hallucinated-fill-on-crop bug.

## Known Issues / Open Bugs
- Auth middleware may still be disabled in production (unconfirmed re-enable) — **treat as urgent**.
- Job/rework architecture rebuild status unclear — sibling `_rwXXXX` directories may still be in active use.
- Add-scene frontend bug (editJob) not confirmed fixed.
- Circular/internal transitions only partially mitigated; likely an upstream fal.ai/Veo limitation.
- No confirmed clean end-to-end retest after the July 1–2 bug-complaint fix round.
- Manual job recovery is fragile: recovering a stuck rework job required hardcoded console JS auth-bypass snippets and manual `finish_assembly.py` reassembly; no permanent fix beyond "always open the tool on a fresh page load."

## Backlog
See companion file `BACKLOG_REQUIREMENTS.md` for full detail. Priority order as last stated by the user:
1. Login screen — **done**
2. systemd auto-start — **done**
3. Multi-job dashboard + concurrent queue — **not started**
4. Auto maintenance scheduler — **not started**
5. Watermark removal from input photos — **not started**
6. Logo watermark on video — **done**
7. Portrait format option — **not started**
8. Human characters (via Kling 2.6 Pro) — **not started**
9. Virtual furniture staging — **not started**, related to #8

Additional open items surfaced after the priority list was set:
- Confirm/re-enable auth in production — **urgent**
- Confirm job/rework architecture rebuild is actually deployed
- Run a full clean end-to-end retest after the July 1–2 fix round

## Standing Safeguards / Rules
- Never modify the original Gustavo `newsletter` codebase/folder — this deployment is fully isolated.
- Always verify a GitHub upload actually took (via `grep`, `wc -l`, or `python -m py_compile` / `node --check`) **before** pulling and restarting the server — uploads have silently failed to take multiple times.
- Video must always be generated **after** narration/audio, using the audio's measured duration — never estimate video duration independently of the actual narration.
- Always send the full, uncropped original image to Veo/Lyra; use cropping only as prompt-hint language, never as an actual pixel crop.
- Avoid literal "First-person POV shot" phrasing and doorway/door/drawer-opening language in prompts — both are confirmed hallucination triggers.
