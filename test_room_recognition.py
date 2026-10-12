"""Tests for Claude-based room recognition in vision_analysis.analyse_input (no network, no API key needed)."""
import os, re, sys, json, tempfile, types
sys.path.insert(0, os.getcwd())
try:
    import fal_client  # noqa
except Exception:
    fc = types.ModuleType("fal_client")
    fc.subscribe = lambda *a, **k: {"results": ""}
    fc.upload_file = lambda p: "http://x/y.jpg"
    sys.modules["fal_client"] = fc
import vision_analysis as va
from PIL import Image

fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

tmp = tempfile.mkdtemp()
img = os.path.join(tmp, "p.jpg"); Image.new("RGB", (400, 300), (120, 90, 60)).save(img)

def with_claude(answer):
    va._claude_vision_text = lambda path, prompt, max_tokens=250: answer

def J(room, size="medium", depth="medium", conf=0.9):
    return json.dumps({"room": room, "size": size, "depth": depth, "confidence": conf, "description": "test"})

# 1-9 mapping of rooms
cases = [
    ("living", "large", "medium", "large", "walk_in_explore"),
    ("kitchen", "medium", "medium", "medium", "walk_in_explore"),
    ("bedroom", "medium", "medium", "bedroom", "walk_in_gentle"),
    ("bathroom", "small", "shallow", "small", "subtle_rotate"),
    ("hallway", "small", "deep", "corridor", "walk_through"),
    ("balcony", "small", "medium", "elevated", "step_out_onto"),
    ("terrace", "large", "medium", "elevated", "step_out_onto"),
    ("garden", "large", "deep", "outdoor", "reveal_pullback"),
    ("building_exterior", "large", "deep", "outdoor", "reveal_pullback"),
]
for room, size, depth, exp_space, exp_move in cases:
    with_claude(J(room, size, depth))
    r = va.analyse_input(img)
    check(f"R {room}/{size} -> {exp_space}/{exp_move}", r["v7_space_type"] == exp_space and r["suggested_movement"] == exp_move,
          (r["v7_space_type"], r["suggested_movement"]))
    check(f"R {room} tagged claude, no error", r["source"] == "claude" and r["room"] == room and r["error"] is None)

with_claude(J("living", "large", "shallow"))
check("R living large+shallow keeps the existing stand_look_around rule", va.analyse_input(img)["suggested_movement"] == "stand_look_around")

with_claude("Sure! ```json\n" + J("kitchen", "small") + "\n```")
r = va.analyse_input(img)
check("R JSON inside prose/fences is parsed", r["source"] == "claude" and r["v7_space_type"] == "small", r)

# fallbacks to Florence
va.fal_client.upload_file = lambda p: "http://x/y.jpg"
va._describe_image = lambda url: "a front garden with lawn and a building facade"
os.environ["FAL_KEY"] = "dummy"
for label, ans in [("garbage text", "I cannot help"), ("invalid JSON", "{room: living"), ("unknown room", J("spaceship")), ("call failed", None)]:
    with_claude(ans)
    r = va.analyse_input(img)
    check(f"F {label} -> Florence fallback", r["source"] == "florence" and r["error"] is None and r["v7_space_type"] == "outdoor", r)

# both unavailable
with_claude(None); os.environ.pop("FAL_KEY", None)
r = va.analyse_input(img)
check("F no Claude and no FAL_KEY -> default result with error, no exception", r["error"] and r["v7_space_type"] == "large", r)
r = va.analyse_input(os.path.join(tmp, "missing.jpg"))
check("F missing file -> error", bool(r["error"]) and "not found" in r["error"].lower())

# invalid size/depth/confidence are normalised
with_claude(json.dumps({"room": "living", "size": "huge", "depth": "??", "confidence": "high"}))
r = va.analyse_input(img)
check("N bad size/depth/confidence normalised", r["source"] == "claude" and r["v7_space_type"] == "medium" and 0 <= r["confidence"] <= 1, r)

# result vocabulary must exist in the UI (guards against frontend/backend drift)
ui = open("ui.html", encoding="utf-8").read() if os.path.exists("ui.html") else ""
if ui:
    sp = re.search(r"const SPACE_OPTS = \{(.*?)\};", ui, re.S).group(1)
    mv = re.search(r"const MOVEMENT_OPTS = \{(.*?)\};", ui, re.S).group(1)
    ui_space = set(re.findall(r"^\s*(\w+):", sp, re.M)); ui_move = set(re.findall(r"^\s*(\w+):", mv, re.M))
    check("U every v7 space value exists in ui SPACE_OPTS", set(va._SPACE_MAP.values()) <= ui_space, set(va._SPACE_MAP.values()) - ui_space)
    check("U every default movement exists in ui MOVEMENT_OPTS (stand_look_around is remapped server-side)",
          (set(va._MOVEMENT_MAP.values()) | set()) <= ui_move, set(va._MOVEMENT_MAP.values()) - ui_move)
else:
    print("SKIP ui.html not found")

# the fake-providers Claude answers the room prompt with a valid room (so fake runs exercise the same path)
import fake_providers as fp
fr = va._claude_vision_text
va._claude_vision_text = lambda path, prompt, max_tokens=250: fp._fake_claude_text(prompt, max_tokens)
r = va.analyse_input(img)
check("K fake_providers answers ROOM_PROMPT with a valid room", r["source"] == "claude" and r["room"] == "living", r)
va._claude_vision_text = fr

# prompt carries the rule that caused the known mistakes
check("P prompt: balcony only if standing on it", "standing ON" in va.ROOM_PROMPT and "through a window" in va.ROOM_PROMPT)

print(f"RESULT: {'ALL PASS' if not fails else 'FAILURES'} ({total - len(fails)}/{total})")
sys.exit(1 if fails else 0)
