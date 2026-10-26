"""The ONE rework engine (2026-10-22, backlog 75 + architecture discipline).

Before this module the same rework logic lived in three functions in
api_server.py (run_redo_scene, run_redo_scenes_batch, run_redo_audio_only):
audio -> clip length -> source image -> enhance -> video -> scene status ->
cost. The copies drifted: the scene-status step looked a scene up by scene_id,
but first-generation status entries only carry "index", so EVERY rework
appended a second entry for the same scene and the library kept showing the
stale first one (job 83ca6568: 6 scenes, 7 entries, scene 5 still "reject");
and a rework clip length used a different rule (4-8 s, rounded up) from the
first generation (6-20 s, rounded to nearest) so a scene whose original clip
was 12 s came back 8 s.

Everything here is plain Python with the outside world injected (TTS, video,
image enhancement, audio measurement, saving), so it is tested offline with
fakes (test_scene_rework.py). api_server.py supplies the real functions and
keeps what only the server can do: the job lock, the rework policy
(count/begin/end/gate), notifications and the final reassembly.
"""
import shutil
from pathlib import Path

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# First-generation clip length rule (api_server job pipeline, Stage 2):
# clip = spoken audio + 2 s buffer, snapped to an even number of seconds,
# minimum 6, maximum 20. ONE definition: first generation and every rework use it.
CLIP_BUFFER_SECS = 2.0
CLIP_MIN_SECS = 6
CLIP_MAX_SECS = 20


def clip_seconds_for_audio(audio_secs, fallback):
    """Clip length for a scene whose own voiceover lasts audio_secs.
    No usable measurement -> fallback (the scene's configured duration)."""
    try:
        audio_secs = float(audio_secs)
    except (TypeError, ValueError):
        return fallback
    if audio_secs <= 0:
        return fallback
    buffered = audio_secs + CLIP_BUFFER_SECS
    return max(CLIP_MIN_SECS, min(CLIP_MAX_SECS, int(round(buffered / 2) * 2)))


def find_source_image(job_dir, scene_id, scene_idx, log=None):
    """Original photo of a scene: {scene_id}.ext first, then the legacy
    scene_NNN.ext of jobs created before scene ids (copied to the new name so
    the fallback is needed only once). None if there is no photo."""
    img_dir = Path(job_dir) / "images"
    for ext in IMAGE_EXTS:
        cand = img_dir / f"{scene_id}{ext}"
        if cand.exists():
            return cand
    for ext in IMAGE_EXTS:
        legacy = img_dir / f"scene_{scene_idx:03d}{ext}"
        if legacy.exists():
            new_name = img_dir / f"{scene_id}{ext}"
            shutil.copy2(str(legacy), str(new_name))
            if log:
                log.info(f"Migrated legacy image {legacy.name} -> {new_name.name}")
            return new_name
    return None


def update_scene_status(statuses, scene_id, scene_idx, scene, **fields):
    """Updates the status entry of ONE scene in place and returns it.

    Match order: same scene_id; else the entry with the same "index" (every
    first-generation entry has an index and no scene_id: this is the case the
    old code missed); else append a new entry (scene added later). The entry
    always ends up with its scene_id so the next lookup is exact."""
    entry = next((s for s in statuses if s.get("scene_id") == scene_id), None)
    if entry is None:
        entry = next((s for s in statuses
                      if not s.get("scene_id") and s.get("index") == scene_idx), None)
    if entry is None:
        entry = {"scene_id": scene_id, "index": scene_idx,
                 "caption": scene.get("caption", ""), "video": "ok",
                 "audio": "skipped", "qc_verdict": "pass"}
        statuses.append(entry)
    entry["scene_id"] = scene_id
    entry.update(fields)
    # Jobs reworked by the old code carry a stale first entry plus an appended
    # twin for the same scene: keep ONE (at the earliest position, which is
    # where the library looks first).
    twins = [s for s in statuses if s is not entry and s.get("index") == scene_idx]
    if twins:
        first_pos = min(i for i, s in enumerate(statuses) if s is entry or s in twins)
        statuses[:] = [s for s in statuses if s is not entry and s not in twins]
        statuses.insert(min(first_pos, len(statuses)), entry)
    return entry


def record_rework_cost(job, redone, model_tier, redo_video, job_dir=None):
    """Prices one rework round and folds it into job["cost_actual"].
    redone = list of {"duration", "had_voiceover", "voiceover_chars"}.
    Returns the rework record (or None if nothing was redone)."""
    if not redone:
        return None
    from cost_tracker import calculate_rework_cost, format_cost_display
    import clip_provenance
    # 2026-10-26: price the new clips by the model that really made them (sidecar next to <scene_id>.mp4)
    used_models = [clip_provenance.used_model_of(Path(job_dir) / "clips" / f"{r.get('scene_id')}.mp4")
                   if (job_dir and r.get("scene_id")) else None for r in redone] if redo_video else []
    rework_cost = calculate_rework_cost(
        scenes_redone=[{"duration": r.get("duration", 0)} for r in redone] if redo_video else [],
        models_used=[model_tier] * len(redone) if redo_video else [],
        redo_video=redo_video,
        redo_audio=any(r.get("had_voiceover") for r in redone),
        audio_chars=sum(r.get("voiceover_chars", 0) for r in redone),
        model_tier=model_tier,
        used_models=used_models,
    )
    job.setdefault("reworks", []).append(rework_cost)
    original_raw = job.get("cost_actual_raw")
    if original_raw:
        job["cost_actual"] = format_cost_display(original_raw, previous_reworks=job["reworks"])
    else:
        # Job predates cost_actual_raw: use its existing total as the baseline.
        legacy_total = (job.get("cost_actual") or {}).get("grand_total_eur", 0)
        pseudo_raw = {"type": "actual", "total_eur": legacy_total, "model_tier": model_tier}
        job["cost_actual"] = format_cost_display(pseudo_raw, previous_reworks=job["reworks"])
    return rework_cost


class RedoError(Exception):
    """Raised only in strict mode (a scene being ADDED must not be skipped)."""


async def redo_scenes(job, job_dir, scene_ids, deps, *, video=True, strict=False, label="Rework"):
    """Regenerates the given scenes in place. Does NOT lock, count against the
    rework budget, reassemble or notify: the caller does (api_server).

    video=True : voiceover (if the scene has one) -> clip length -> photo ->
                 enhance -> new clip. video=False: voiceover only, the existing
                 clip is untouched (no Luma/Veo cost).
    strict=True: a missing scene / photo / failed clip raises RedoError (adding
                 a scene); otherwise the scene is skipped and reported.

    deps (all injected): generate_speech(text, out_path, voice_id=None)->bool,
    audio_seconds(path)->float|None, enhance(src, dst), generate_video(img,
    seconds, out, **kw)->bool, to_thread(fn, *a, **kw) awaitable, save(),
    progress(percent, message), log.
    Returns {"redone": [...], "failed": [scene_id], "skipped": [scene_id]}."""
    job_dir = Path(job_dir)
    scenes_config = job.get("scenes_config", [])
    statuses = job.setdefault("scenes", [])
    tier = job.get("model_tier", "premium")
    n = max(len(scene_ids), 1)
    out = {"redone": [], "failed": [], "skipped": []}
    log = deps.log

    for idx, scene_id in enumerate(scene_ids):
        scene_idx = next((i for i, s in enumerate(scenes_config) if s.get("scene_id") == scene_id), None)
        if scene_idx is None:
            if strict:
                raise RedoError(f"Scene {scene_id} not found")
            log.warning(f"[rework] scene {scene_id} not found, skipping")
            out["skipped"].append(scene_id)
            continue
        scene = scenes_config[scene_idx]
        voiceover = (scene.get("voiceover") or "").strip()
        seconds = int(scene.get("duration", 10))

        # ── voiceover ────────────────────────────────────────────────────
        if voiceover:
            audio_dir = job_dir / "audio"
            audio_dir.mkdir(exist_ok=True)
            audio_out = str(audio_dir / f"{scene_id}.mp3")
            deps.progress(int(5 + (idx / n) * 80), f"{label}: rigenero voiceover ({idx+1}/{n})…")
            ok_audio = await deps.to_thread(deps.generate_speech, voiceover, audio_out,
                                            voice_id=job.get("voice_id") or None)
            if not ok_audio or not Path(audio_out).exists():
                if video:
                    log.warning(f"[rework] TTS failed for {scene_id}; keeping the previous audio file if any")
                else:
                    log.error(f"[rework] audio-only: TTS failed for {scene_id}")
                    out["skipped"].append(scene_id)
                    continue
            elif video:
                seconds = clip_seconds_for_audio(deps.audio_seconds(audio_out), seconds)
        elif not video:
            log.warning(f"[rework] audio-only: scene {scene_id} has no voiceover text, skipping")
            out["skipped"].append(scene_id)
            continue

        if not video:
            update_scene_status(statuses, scene_id, scene_idx, scene, audio="ok")
            out["redone"].append({"scene_id": scene_id, "duration": 0,
                                  "had_voiceover": True, "voiceover_chars": len(voiceover)})
            continue

        # ── photo ────────────────────────────────────────────────────────
        source_img = find_source_image(job_dir, scene_id, scene_idx, log)
        if not source_img:
            if strict:
                raise RedoError(f"No source image found for scene {scene_id}")
            log.error(f"[rework] no source image for scene {scene_id}, skipping")
            out["failed"].append(scene_id)
            continue
        enhanced_dir = job_dir / "enhanced"
        enhanced_dir.mkdir(exist_ok=True)
        enhanced_img = enhanced_dir / f"{scene_id}_enhanced.jpg"
        if not enhanced_img.exists():
            deps.progress(int(10 + (idx / n) * 80), f"{label}: miglioro immagine ({idx+1}/{n})…")
            await deps.to_thread(deps.enhance, str(source_img), str(enhanced_img))
        img_for_generation = str(enhanced_img) if enhanced_img.exists() else str(source_img)

        # ── clip ─────────────────────────────────────────────────────────
        clips_dir = job_dir / "clips"
        clips_dir.mkdir(exist_ok=True)
        clip_out = str(clips_dir / f"{scene_id}.mp4")
        deps.progress(int(15 + (idx / n) * 80), f"{label}: rigenero clip {idx+1}/{n} ({seconds}s)…")
        ok_video = await deps.to_thread(
            deps.generate_video, img_for_generation, seconds, clip_out,
            space_type=scene.get("space_type", "large"),
            pov_movement=scene.get("pov_movement", "walk_in_explore"),
            lighting=job.get("lighting", "bright_natural"),
            intensity=job.get("intensity", "natural_pace"),
            model_tier=tier,
            output_format=job.get("output_format", "landscape"),
            do_video_upscale=job.get("do_video_upscale", True),
        )
        if not ok_video:
            if strict:
                raise RedoError("Video generation failed")
            log.error(f"[rework] video generation failed for scene {scene_id}")
            out["failed"].append(scene_id)
            continue

        update_scene_status(statuses, scene_id, scene_idx, scene, video="ok",
                            audio="ok" if voiceover else "skipped",
                            duration_used=seconds, qc_verdict="pass")
        out["redone"].append({"scene_id": scene_id, "duration": seconds,
                              "had_voiceover": bool(voiceover),
                              "voiceover_chars": len(voiceover)})

    job["scenes"] = statuses
    deps.save()
    return out
