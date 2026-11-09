"""One-off, idempotent patcher: adds the pace-fix hook to vision_analysis.analyse_output (inside the existing judge block)."""
from pathlib import Path
p = Path("vision_analysis.py"); t = p.read_text(encoding="utf-8")
if "_cp.apply(" in t:
    print("gia presente")
else:
    a = '''                out["standard_shadow"] = _std
                _cs.record(video_path, _std)'''
    assert t.count(a) == 1, "anchor not found exactly once"
    new = '''                out["standard_shadow"] = _std
                # 2026-11-09: the judge's speed word (asked in the same call) slows a clip it called fast / very_fast (clip_pace, PVS_PACE_FIX=1, default OFF):
                # done HERE, once, before anyone uses the clip, so timing / assembly / rework see a normal 5 s clip. No extra Claude call.
                try:
                    import clip_pace as _cp
                    _std["pace"] = _cp.apply(video_path, (_std.get("judge") or {}).get("speed"))
                    out["pace"] = _std["pace"]
                    if _std["pace"].get("applied"):
                        log.info(f"[Vision QC] pace fix: {_std['pace']}")
                except Exception as _pe:
                    log.warning(f"[Vision QC] pace fix skipped: {_pe}")
                _cs.record(video_path, _std)'''
    p.write_text(t.replace(a, new), encoding="utf-8")
    print("patched vision_analysis.py")
