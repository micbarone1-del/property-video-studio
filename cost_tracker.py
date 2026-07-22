"""
cost_tracker.py
───────────────
Tracks and estimates costs for each video generation job.
All amounts in EUR.

Pricing (as of June 2026):
  Lyra 2.0 fast (DMD):   ~€0.045 per 81 frames, ~€0.085 per 161 frames
  LTX-2.3 fast:          ~€0.020 per 8s clip
  fal-ai/aura-sr:        ~€0.030 per image upscale
  Florence-2 Large:      ~€0.0002 per image analysis
  ElevenLabs:            €0.0003 per character (Starter), €0.00024 (Creator+)
  Infrastructure:        monthly VPS cost / estimated monthly jobs

Set in .env:
  MONTHLY_JOBS_ESTIMATE=20        (your expected jobs per month)
  VPS_MONTHLY_COST_EUR=52.45      (your Hostinger VPS cost)
  ELEVENLABS_COST_PER_CHAR=0.0003 (adjust to your plan)
"""

import os
import json
import logging
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

# ── Pricing constants ──────────────────────────────────────────────────────────
# Lyra 2.0 DMD fast mode — billed per frame
LYRA_COST_81_FRAMES  = 0.045   # ~5s clip
LYRA_COST_161_FRAMES = 0.085   # ~10s clip
LYRA_COST_241_FRAMES = 0.125   # ~15s clip

# LTX-2.3 fallback — billed per clip
LTX_COST_PER_CLIP = 0.020

# Topaz video upscaling — per second of video
TOPAZ_COST_PER_SEC     = 0.02   # 720p → 1080p tier
UPSCALE_COST_PER_IMAGE = 0.030  # fal-ai/aura-sr image upscale per image

# Florence-2 vision analysis — per call
FLORENCE_COST_PER_CALL = 0.0002

# ElevenLabs TTS — per character
ELEVENLABS_COST_PER_CHAR = float(os.getenv("ELEVENLABS_COST_PER_CHAR", "0.0003"))

# Infrastructure — updated to annual Hostinger plan: $371.88 + 22% VAT = $453.69/year
VPS_MONTHLY_EUR      = float(os.getenv("VPS_MONTHLY_COST_EUR", "34.79"))  # ~$37.81/mo at 0.92 EUR/USD
MONTHLY_JOBS_DEFAULT = int(os.getenv("MONTHLY_JOBS_ESTIMATE", "20"))  # fallback if no rolling data yet

def get_infra_cost_per_job(actual_monthly_jobs: int = None) -> float:
    """
    Infrastructure cost per video, based on ACTUAL rolling job volume when
    available (passed in from api_server.py's real job history), falling
    back to the static estimate only when no real data exists yet (e.g.
    very first jobs before any history has accumulated).
    """
    job_count = actual_monthly_jobs if actual_monthly_jobs and actual_monthly_jobs > 0 else MONTHLY_JOBS_DEFAULT
    return VPS_MONTHLY_EUR / max(job_count, 1)

# Static fallback for any code path not yet passing actual_monthly_jobs
INFRA_COST_PER_JOB = get_infra_cost_per_job()

# Frame mapping (mirrors video_generation.py)
_DURATION_TO_FRAMES = {
    6: 81, 7: 81, 8: 81,
    9: 161, 10: 161, 11: 161, 12: 161,
    13: 161, 14: 161, 15: 161,
    16: 241, 17: 241, 18: 241, 19: 241, 20: 241,
}
_FRAME_COST = {
    81:  LYRA_COST_81_FRAMES,
    161: LYRA_COST_161_FRAMES,
    241: LYRA_COST_241_FRAMES,
}


# ── Cost estimation (before generation) ───────────────────────────────────────

# Per-clip cost by model tier (8s clip) -- kept as a fallback for any
# tier not in VIDEO_COST_PER_SEC_EUR below (e.g. "standard"/Kling, which
# is dead code per status.md, not worth pricing precisely).
TIER_COST_PER_CLIP = {
    "eco":      LYRA_COST_81_FRAMES + (8 * TOPAZ_COST_PER_SEC),  # Lyra + Topaz
    "standard": 0.56,   # Kling 2.5 Turbo Pro (kept for backward compat)
    "luma":     0.46,   # Luma Ray 2 — SUPERSEDED, see VIDEO_COST_PER_SEC_EUR below
    "premium":  0.80,   # Veo 3.1 Fast — SUPERSEDED, see VIDEO_COST_PER_SEC_EUR below
}

# Real per-second fal.ai rates (2026-07-20 fix, verified against fal.ai's
# own published pricing -- not yet cross-checked against a real invoice
# line-by-line, treat as a well-evidenced estimate pending that check).
# Audio is always off in our calls (ElevenLabs handles narration
# separately), and we always request 1080p resolution.
#   Luma Ray 2: 1080p costs 4x the BASE (540p) rate of $0.50/5s -- our old
#     flat €0.46/clip never applied this multiplier at all. Confirmed this
#     exactly explains a real reported case: a 10-clip video estimated at
#     ~€5 actually invoiced at ~$20 from fal.ai (10 x $2.00 = $20).
#   Veo 3.1 Fast / Standard: NO resolution multiplier (confirmed same
#     price at 720p or 1080p) -- old flat rates were already correct for
#     an exact 8s clip, just didn't scale down for the valid 4s/6s options.
USD_TO_EUR = 0.92  # matches the rate already used for VPS_MONTHLY_EUR

VIDEO_COST_PER_SEC_EUR = {
    "luma":        (0.50 / 5) * 4 * USD_TO_EUR,   # ~0.368 EUR/s at 1080p
    "premium":     0.10 * USD_TO_EUR,              # ~0.092 EUR/s, Veo 3.1 Fast, no audio
    "premium_veo": 0.20 * USD_TO_EUR,              # ~0.184 EUR/s, Veo 3.1 Standard, no audio
}


def video_cost_for_clip(model_tier: str, duration_secs) -> float:
    """
    Real per-clip video cost, scaled by actual clip duration -- replaces
    the flat TIER_COST_PER_CLIP lookup for tiers fal.ai genuinely bills
    per-second (Luma, Veo). Falls back to the flat rate for any tier not
    in VIDEO_COST_PER_SEC_EUR.
    """
    if model_tier in VIDEO_COST_PER_SEC_EUR:
        return duration_secs * VIDEO_COST_PER_SEC_EUR[model_tier]
    return TIER_COST_PER_CLIP.get(model_tier, TIER_COST_PER_CLIP["premium"])


def estimate_job_cost(
    scenes:              list,
    do_upscale:          bool = True,
    do_video_upscale:    bool = True,
    do_vision_qc:        bool = True,
    model_tier:          str  = "premium",
    actual_monthly_jobs: int  = None,
    claude_cost_eur:     float = 0.0,
) -> dict:
    """Estimates the total cost of a job before generation starts.
    actual_monthly_jobs: real rolling count of jobs completed in the last
    30 days, passed from api_server.py — used to calculate the true
    per-video infrastructure share rather than a static guess.
    claude_cost_eur: real Claude API cost for URL-scraped jobs (listing
    extraction, narration writing, photo quality ranking, vision
    analysis) -- 2026-07-21 fix (architecture assessment item 31): this
    was captured (scraper.get_claude_cost()) and stored on the job dict,
    but never actually folded into the displayed cost estimate/actual --
    0.0 for manual jobs, which never call Claude at all.
    """
    n = len(scenes)

    # Video generation cost — tier-aware, duration-aware for Luma/Veo
    # (2026-07-20 fix: was a flat per-clip rate, ignoring both actual
    # per-scene duration and Luma's real resolution-based cost multiplier)
    video_cost = sum(video_cost_for_clip(model_tier, int(s.get("duration", 8))) for s in scenes)

    # Topaz upscale only applies to eco tier
    video_upscale_cost = 0.0
    if model_tier == "eco" and do_video_upscale:
        for scene in scenes:
            duration = int(scene.get("duration", 8))
            video_upscale_cost += duration * TOPAZ_COST_PER_SEC

    upscale_cost = (UPSCALE_COST_PER_IMAGE * n) if do_upscale else 0.0
    total_chars  = sum(len(s.get("voiceover", "")) for s in scenes)
    tts_cost     = total_chars * ELEVENLABS_COST_PER_CHAR
    vision_calls = (n * 2) if do_vision_qc else 0
    vision_cost  = vision_calls * FLORENCE_COST_PER_CALL
    infra_cost   = get_infra_cost_per_job(actual_monthly_jobs)
    total = video_cost + upscale_cost + video_upscale_cost + tts_cost + vision_cost + infra_cost + claude_cost_eur

    return {
        "type":               "estimate",
        "scenes":             n,
        "model_tier":         model_tier,
        "video_eur":          round(video_cost,          4),
        "upscale_eur":        round(upscale_cost,        4),
        "video_upscale_eur":  round(video_upscale_cost,  4),
        "tts_eur":            round(tts_cost,            4),
        "tts_chars":          total_chars,
        "vision_eur":         round(vision_cost,         4),
        "vision_calls":       vision_calls,
        "infra_eur":          round(infra_cost,          4),
        "claude_eur":         round(claude_cost_eur,      4),
        "total_eur":          round(total,               3),
        "calculated_at":      datetime.utcnow().isoformat(),
    }


# ── Actual cost tracking (after generation) ───────────────────────────────────

def calculate_actual_cost(
    scenes_generated: list,
    models_used:      list,
    audios_generated: list,
    do_upscale:       bool = True,
    do_vision_qc:     bool = True,
    model_tier:       str  = "premium",
    claude_cost_eur:  float = 0.0,
) -> dict:
    """Calculates the actual cost after generation completes.
    claude_cost_eur: see estimate_job_cost() docstring -- same real,
    previously-uncounted Claude API cost, for scraped jobs (2026-07-21 fix).
    """
    n = len(scenes_generated)

    # Video — tier-aware pricing
    video_cost  = 0.0
    veo_clips   = 0
    lyra_clips  = 0
    ltx_clips   = 0

    for i, scene in enumerate(scenes_generated):
        model    = models_used[i] if i < len(models_used) else model_tier
        duration = int(scene.get("duration", 10))

        if "ltx" in str(model):
            video_cost += LTX_COST_PER_CLIP
            ltx_clips  += 1
        elif "lyra" in str(model) or model_tier == "eco":
            frames      = _DURATION_TO_FRAMES.get(duration, 81)
            video_cost += _FRAME_COST.get(frames, LYRA_COST_81_FRAMES)
            # Add Topaz upscale cost for eco tier
            video_cost += duration * TOPAZ_COST_PER_SEC
            lyra_clips += 1
        else:
            # Veo or Luma — real per-second billing (2026-07-20 fix)
            video_cost += video_cost_for_clip(model_tier, duration)
            veo_clips  += 1

    upscale_cost = (UPSCALE_COST_PER_IMAGE * n) if do_upscale else 0.0
    total_chars  = sum(a.get("chars", 0) for a in audios_generated)
    tts_cost     = total_chars * ELEVENLABS_COST_PER_CHAR
    vision_calls = (n * 2) if do_vision_qc else 0
    vision_cost  = vision_calls * FLORENCE_COST_PER_CALL
    infra_cost   = INFRA_COST_PER_JOB
    total = video_cost + upscale_cost + tts_cost + vision_cost + infra_cost + claude_cost_eur

    return {
        "type":          "actual",
        "scenes":        n,
        "model_tier":    model_tier,
        "veo_clips":     veo_clips,
        "lyra_clips":    lyra_clips,
        "ltx_clips":     ltx_clips,
        "video_eur":     round(video_cost,   4),
        "upscale_eur":   round(upscale_cost, 4),
        "tts_eur":       round(tts_cost,     4),
        "tts_chars":     total_chars,
        "vision_eur":    round(vision_cost,  4),
        "vision_calls":  vision_calls,
        "infra_eur":     round(infra_cost,   4),
        "claude_eur":    round(claude_cost_eur, 4),
        "total_eur":     round(total,        3),
        "calculated_at": datetime.utcnow().isoformat(),
    }


# ── Rework incremental cost ────────────────────────────────────────────────────

def calculate_rework_cost(
    scenes_redone:  list,
    models_used:    list,
    redo_video:     bool = True,
    redo_audio:     bool = False,
    audio_chars:    int  = 0,
    model_tier:     str  = "premium",
) -> dict:
    """
    Calculates the incremental cost of a rework run.
    Only charges for what was actually regenerated.

    Tier-aware pricing mirrors calculate_actual_cost() exactly, so a redo
    on a Luma/Veo/eco-tier job is priced the same as a fresh clip in that
    tier would be -- not a flat Lyra frame-rate fallback (2026-07-13 fix;
    previously this always used Lyra frame pricing regardless of tier).
    """
    n = len(scenes_redone)

    video_cost = 0.0
    if redo_video:
        for i, scene in enumerate(scenes_redone):
            model    = models_used[i] if i < len(models_used) else model_tier
            duration = int(scene.get("duration", 8))
            if "ltx" in str(model):
                video_cost += LTX_COST_PER_CLIP
            elif "lyra" in str(model) or model_tier == "eco":
                frames      = _DURATION_TO_FRAMES.get(duration, 81)
                video_cost += _FRAME_COST.get(frames, LYRA_COST_81_FRAMES)
                video_cost += duration * TOPAZ_COST_PER_SEC
            else:
                video_cost += video_cost_for_clip(model_tier, duration)

    tts_cost    = (audio_chars * ELEVENLABS_COST_PER_CHAR) if redo_audio else 0.0
    vision_cost = n * FLORENCE_COST_PER_CALL   # output QC only

    total = video_cost + tts_cost + vision_cost

    return {
        "type":          "rework",
        "scenes":        n,
        "model_tier":    model_tier,
        "video_eur":     round(video_cost,  4),
        "tts_eur":       round(tts_cost,    4),
        "vision_eur":    round(vision_cost, 4),
        "infra_eur":     0.0,
        "total_eur":     round(total,       3),
        "calculated_at": datetime.utcnow().isoformat(),
    }


# ── Format for UI display ──────────────────────────────────────────────────────

def format_cost_display(cost: dict, previous_reworks: list = None) -> dict:
    """
    Formats cost data for display in the UI.
    Includes running total if reworks have been done.

    Returns a display-ready dict with formatted strings.
    """
    rework_total = sum(r.get("total_eur", 0) for r in (previous_reworks or []))
    grand_total  = cost.get("total_eur", 0) + rework_total

    lines = []
    if cost.get("video_eur", 0) > 0:
        tier = cost.get("model_tier", "premium")
        tier_labels = {
            "eco":      "Lyra 2.0 + Topaz",
            "standard": "Kling 2.5 Turbo",
            "luma":     "Luma Ray 2",
            "premium":  "Veo 3.1 Fast",
        }
        model_label = tier_labels.get(tier, "Veo 3.1 Fast")
        if cost.get("ltx_clips", 0) > 0:
            model_label += f" + LTX fallback ({cost['ltx_clips']} clips)"
        lines.append({
            "label": f"Video generation — {cost.get('scenes',0)} clips ({model_label})",
            "value": f"€{cost['video_eur']:.3f}"
        })
    if cost.get("upscale_eur", 0) > 0:
        lines.append({
            "label": f"AI upscaling — {cost.get('scenes',0)} images",
            "value": f"€{cost['upscale_eur']:.3f}"
        })
    if cost.get("tts_eur", 0) > 0:
        lines.append({
            "label": f"Voiceover — {cost.get('tts_chars',0):,} characters",
            "value": f"€{cost['tts_eur']:.4f}"
        })
    if cost.get("vision_eur", 0) > 0:
        lines.append({
            "label": f"Vision QC — {cost.get('vision_calls',0)} checks",
            "value": f"€{cost['vision_eur']:.4f}"
        })
    if cost.get("infra_eur", 0) > 0:
        lines.append({
            "label": "Infrastructure share",
            "value": f"€{cost['infra_eur']:.2f}"
        })
    if cost.get("claude_eur", 0) > 0:
        lines.append({
            "label": "Claude API (scraping, narrazione, analisi foto)",
            "value": f"€{cost['claude_eur']:.4f}"
        })
    if rework_total > 0:
        lines.append({
            "label": f"Rework costs ({len(previous_reworks)} rework(s))",
            "value": f"€{rework_total:.3f}"
        })

    return {
        "type":        cost.get("type", "estimate"),
        "lines":       lines,
        "total":       f"€{grand_total:.2f}",
        "grand_total_eur": round(grand_total, 3),
        "is_estimate": cost.get("type") == "estimate",
    }


# ── CLI test ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)

    test_scenes = [
        {"duration": 8,  "voiceover": "Benvenuti in questo splendido appartamento."},
        {"duration": 10, "voiceover": "Il soggiorno è luminoso e spazioso con grandi finestre."},
        {"duration": 6,  "voiceover": ""},
        {"duration": 8,  "voiceover": "La cucina moderna è completamente attrezzata."},
        {"duration": 8,  "voiceover": "Il bagno principale è elegante e funzionale."},
    ]

    print("=== COST ESTIMATE ===")
    estimate = estimate_job_cost(test_scenes, do_upscale=True, do_vision_qc=True)
    display  = format_cost_display(estimate)
    for line in display["lines"]:
        print(f"  {line['label']:<50} {line['value']}")
    print(f"  {'Total':<50} {display['total']}")
