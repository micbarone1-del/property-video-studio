"""Tests of sync_preview.plan(): the checks and the 'writes only to _test_scratch' guarantee. No video is rendered."""
import json
import tempfile
from pathlib import Path

import sync_preview as sp

ok_n, fails = 0, []


def check(name, cond, extra=""):
    global ok_n
    if cond:
        ok_n += 1
        print(f"PASS {name}")
    else:
        fails.append(name)
        print(f"FAIL {name} {extra}")


def expect(exc, fn):
    try:
        fn()
    except exc:
        return True
    except Exception:
        return False
    return False


tmp = Path(tempfile.mkdtemp())
(tmp / "aaaa1111").mkdir()
(tmp / "bbbb2222" / "clips").mkdir(parents=True)
(tmp / "aaaa1111" / "narration.mp3").write_bytes(b"x")
(tmp / "aaaa1111" / "job_meta.json").write_text(json.dumps({"timeline": {"mode": "anchored", "targets": [5.2, 5.0, 5.0, 5.0, 5.0, 5.0]},
                                                              "transition_style": "fade", "output_format": "landscape"}))
for i in range(6):
    (tmp / "bbbb2222" / "clips" / f"scene_{i:03d}.mp4").write_bytes(b"y")

p = sp.plan("aaaa1111", "bbbb2222", tmp)
check("T1 plan: 6 targets, 6 clips, narration of the timeline job", len(p["targets"]) == 6 and len(p["clips"]) == 6 and p["narration"].name == "narration.mp3")
check("T2 the output is inside _test_scratch (never inside a job folder)", p["out"].parent == tmp / "_test_scratch")
check("T3 plan has no side effect (no scratch folder created, nothing written)", not (tmp / "_test_scratch").exists())
(tmp / "bbbb2222" / "clips" / "scene_005.mp4").unlink()
check("T4 a missing clip is reported", expect(FileNotFoundError, lambda: sp.plan("aaaa1111", "bbbb2222", tmp)))
check("T5 a job without anchored timeline is refused", expect(ValueError, lambda: (
    (tmp / "bbbb2222" / "job_meta.json").write_text(json.dumps({"narration_mode": "per_scene"})), sp.plan("bbbb2222", "aaaa1111", tmp))))
check("T6 path tricks and scratch names are refused as job ids", all(expect(ValueError, lambda j=j: sp.plan(j, "bbbb2222", tmp)) for j in ("../x", "_test_scratch", ".hidden", "")))
check("T7 unknown job -> FileNotFoundError", expect(FileNotFoundError, lambda: sp.plan("zzzz9999", "bbbb2222", tmp)))
cmd = sp.light_copy_cmd("a.mp4", "b.mp4")
check("T9 the light copy: 480 p, fast start, writes only the new file", "scale=-2:480" in cmd and "+faststart" in cmd and cmd[-1] == "b.mp4" and cmd[cmd.index("-i") + 1] == "a.mp4")
src = Path(sp.__file__).read_text()
check("T8 the tool never deletes (no remove/rmtree/unlink) and uses the real assembly functions",
      not any(w in src for w in ("rmtree", ".unlink(", "os.remove", "shutil.move")) and "assemble_property_video" in src and "_overlay_narration_audio" in src)
print(f"\n{ok_n}/{ok_n + len(fails)} PASS")
raise SystemExit(1 if fails else 0)
