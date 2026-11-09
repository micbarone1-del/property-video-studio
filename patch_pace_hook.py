"""One-off, idempotent patcher: puts the pace-fix hook in vision_analysis.analyse_output (inside the existing judge block). Handles the file as it is now on the server."""
from pathlib import Path
p = Path("vision_analysis.py"); t = p.read_text(encoding="utf-8")
NEW_CALL = "_std[\"pace\"] = _cp.apply(video_path, _std)"
OLD_CALL = "_std[\"pace\"] = _cp.apply(video_path, (_std.get(\"judge\") or {}).get(\"speed\"))"
if NEW_CALL in t:
    print("gia presente")
elif OLD_CALL in t:
    assert t.count(OLD_CALL) == 1
    p.write_text(t.replace(OLD_CALL, NEW_CALL).replace("the judge's speed word (asked in the same call) slows a clip it called fast / very_fast", "the QC's measured speed (motion_peak of the geometry measures) slows a clip proportionally"), encoding="utf-8")
    print("hook aggiornato (misura QC al posto della parola del giudice)")
else:
    a = '''                out["standard_shadow"] = _std
                _cs.record(video_path, _std)'''
    assert t.count(a) == 1, "anchor not found exactly once"
    new = '''                out["standard_shadow"] = _std
                # 2026-11-09: the QC's measured speed (motion_peak of the geometry measures) slows a clip proportionally (clip_pace; needs PVS_PACE_FIX=1 and PVS_PACE_LIMIT):
                # done HERE, once, before anyone uses the clip, so timing / assembly / rework see a normal 5 s clip. No extra Claude call.
                try:
                    import clip_pace as _cp
                    _std["pace"] = _cp.apply(video_path, _std)
                    out["pace"] = _std["pace"]
                    if _std["pace"].get("applied"):
                        log.info(f"[Vision QC] pace fix: {_std['pace']}")
                except Exception as _pe:
                    log.warning(f"[Vision QC] pace fix skipped: {_pe}")
                _cs.record(video_path, _std)'''
    p.write_text(t.replace(a, new), encoding="utf-8")
    print("patched vision_analysis.py")
