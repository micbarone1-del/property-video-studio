"""Narration vs scene durations (2026-10-15): scenes must cover the speech itself (lead/trail blank frames are
added AROUND the scenes at assembly), extra seconds go to the LAST scene, and the assembly overflow only counts
speech running past the end of the video. Run: python3 test_narration_durations.py"""
import re, sys
import narration as nr

fails = 0
def check(name, cond, detail=""):
    global fails
    print(("PASS" if cond else "FAIL"), name, detail)
    if not cond: fails += 1

L = [5] * 12
d = nr.calculate_scene_durations(57.8, 12, L, [5, 9])
check("N1 57.8 s fits 12x5 (no extension, not too short)", not d["needs_extension"] and not d["too_short"] and d["new_scene_durations"] == L, str(d["new_scene_durations"]))
d = nr.calculate_scene_durations(59.9, 12, L, [5, 9])
check("N2 59.9 s still fits 60 s (old rule wanted 61.9 -> extension)", not d["needs_extension"] and sum(d["new_scene_durations"]) == 60)
d = nr.calculate_scene_durations(61.6, 12, L, [5, 9])
check("N3 61.6 s needs extension, bump lands on the LAST scene", d["needs_extension"] and d["new_scene_durations"] == [5] * 11 + [9], str(d["new_scene_durations"]))
check("N4 total covers the speech", sum(d["new_scene_durations"]) >= 61.6 and d["target_total_secs"] == 64)
d = nr.calculate_scene_durations(53.0, 12, L, [5, 9])
check("N5 53 s in 60 s = 7 s of silence -> too_short", d["too_short"] and not d["needs_extension"])
d = nr.calculate_scene_durations(56.5, 12, L, [5, 9])
check("N6 56.5 s in 60 s = 3.5 s of silence -> compatible", not d["too_short"] and "compatibili" in d["message"], d["message"])
d = nr.calculate_scene_durations(27.5, 6, [5] * 6, [5, 9])
check("N7 standard 6x5 with 27.5 s fits (old rule: 29.5 ok too)", not d["needs_extension"] and d["new_scene_durations"] == [5] * 6)
d = nr.calculate_scene_durations(30.5, 6, [5] * 6, [5, 9])
check("N8 30.5 s over 30 s extends the last scene only", d["new_scene_durations"] == [5] * 5 + [9], str(d["new_scene_durations"]))

src = open("api_server.py").read()
check("O1 overflow counts only speech past the video end", "overflow = max(0.0, narration.duration - video.duration)" in src and "needed   = LEAD_SECS + narration.duration + TRAIL_SECS" not in src)
ui = open("ui.html").read()
check("U1 UI check uses the same rule (no +2.0 / +2.0 term)", "const targetTotal = narrationSecs;" in ui and "(currentTotal - narrationSecs) > 4.0" in ui and "narrationSecs + 2.0" not in ui)
check("U2 no leftover padding term in narration.py maths", "NARRATION_PADDING_SECS" not in re.sub(r"^NARRATION_PADDING_SECS.*$", "", open("narration.py").read(), flags=re.M).split("def calculate_scene_durations")[1])

# overflow arithmetic of the assembly (pure maths, same expression as api_server)
def final_len(V, N, lead=1.0, trail=1.0):
    overflow = max(0.0, N - V)
    return lead + V + trail + overflow, lead + N, (lead + V + trail + overflow) - (lead + N)
f, end, tail = final_len(60, 57.8)
check("A1 N=57.8, V=60: final 62 s, speech ends 58.8, 3.2 s of tail", abs(f - 62) < 1e-9 and abs(tail - 3.2) < 1e-9)
f, end, tail = final_len(60, 61.6)
check("A2 N=61.6, V=60: speech keeps a full 1 s trail after it (old maths left 3 s)", abs(tail - 1.0) < 1e-9, f"tail={tail:.1f}")
print("ALL PASS" if not fails else f"{fails} FAIL")
sys.exit(1 if fails else 0)
