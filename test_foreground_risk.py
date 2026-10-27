import json
import os
import sys
os.environ["PVS_ANCHOR"] = "1"
import camera_plan as cp
import vision_analysis as va
q = chr(34)
res = []


def check(name, ok):
    res.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name)


def classify(answer):
    old = va._claude_vision_text
    va._claude_vision_text = lambda *a, **k: json.dumps(answer)
    try:
        return va._classify_room_claude("x.jpg")
    finally:
        va._claude_vision_text = old


base = {"room": "living", "size": "medium", "depth": "medium", "confidence": 0.9, "description": "sofa and palm"}
r1 = classify(dict(base, anchor="none", anchor_side="center", anchor_height="middle", foreground_risk=True))
check("F1 no safe anchor + bulky object near the camera -> straight push-in toward the centre", r1 and r1["anchor"] == cp.CENTRE_ANCHOR and r1["anchor_side"] == "center")
r2 = classify(dict(base, anchor="the far window", anchor_side="center", anchor_height="upper", foreground_risk=True))
check("F2 a safe anchor is kept even when the risk flag is set", r2 and r2["anchor"] == "the far window")
r3 = classify(dict(base, anchor="none", anchor_side="center", anchor_height="middle", foreground_risk=False))
check("F3 no risk and no anchor -> today is unchanged (no anchor)", r3 and r3["anchor"] == "")
r4 = classify(dict(base, anchor="none", anchor_side="center", anchor_height="middle"))
check("F4 an answer without the new key behaves as before", r4 and r4["anchor"] == "")
check("F5 the centre phrase is accepted by the anchor filter", cp.clean_anchor(cp.CENTRE_ANCHOR) == cp.CENTRE_ANCHOR)
check("F6 intent_kwargs hands the scene to the generator", cp.intent_kwargs({"anchor": cp.CENTRE_ANCHOR, "anchor_side": "center"}).get("anchor") == cp.CENTRE_ANCHOR)
check("F7 the centre anchor gives exactly the tested motion text", cp.anchor_motion_for("walk_in_explore", cp.CENTRE_ANCHOR, "center", "medium") == cp.CENTRE_MOTION)
check("F8 a normal anchor still gives the normal text", cp.anchor_motion_for("walk_in_explore", "the far window", "center", "medium") == cp.ANCHOR_MOTION.format(anchor="the far window"))
check("F9 the new question is in the room prompt", "foreground_risk" in va.ROOM_PROMPT_ANCHOR and "four more keys" in va.ROOM_PROMPT_ANCHOR)
src = open("exp_luma.py").read()
check("F10 the test tool reads the text from camera_plan (no private copy)", "TARGET_MOTION = camera_plan.CENTRE_MOTION" in src and "treat nearby furniture" not in src)
print(str(sum(res)) + "/" + str(len(res)))
sys.exit(0 if all(res) else 1)
