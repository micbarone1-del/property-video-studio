"""camera_plan.py (2026-10-26): the ONE table of camera movements. Zero cost, no network.
Guards: every copy reads the same table (identity, not equality), the UI mirror equals it, every movement named is known to the Luma
prompt tokens and to the UI list, and the exact differences from the pre-consolidation behaviour are listed (nothing changed by accident)."""
import sys, os, re, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for name in ("fal_client", "moviepy", "anthropic"):          # not installed in the sandbox; the server has them
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
sys.modules["anthropic"].Anthropic = getattr(sys.modules["anthropic"], "Anthropic", lambda *a, **k: "REAL")
import camera_plan as cp
import video_generation as vg
import vision_analysis as va
import listing_scraper as ls
res = []
def check(n, ok, info=""):
    res.append(bool(ok)); print(("PASS " if ok else "FAIL ") + n + ("" if ok else f" -- {info}"))

# ---- one table, read by every user ----------------------------------------------------------------------------------------------
check("T1 video_generation.SPACE_DEFAULT_MOVEMENT IS camera_plan's table (same object, not a copy)", vg.SPACE_DEFAULT_MOVEMENT is cp.SPACE_DEFAULT_MOVEMENT)
check("T2 vision_analysis._MOVEMENT_MAP IS camera_plan's table", va._MOVEMENT_MAP is cp.SPACE_DEFAULT_MOVEMENT)
check("T3 the scraper's category table IS camera_plan.CATEGORY_MOVEMENT", ls._CATEGORY_TO_POV_MOVEMENT is cp.CATEGORY_MOVEMENT)
ui = open("ui.html", encoding="utf-8").read()
m = re.search(r"const SPACE_DEFAULT_MOVEMENT_MAP = \{(.*?)\};", ui, re.S)
ui_map = dict(re.findall(r"(\w+):\s*'(\w+)'", m.group(1))) if m else {}
check("T4 ui.html's mirror equals camera_plan.SPACE_DEFAULT_MOVEMENT exactly", ui_map == cp.SPACE_DEFAULT_MOVEMENT, (ui_map, cp.SPACE_DEFAULT_MOVEMENT))
sp = set(re.findall(r"^\s*(\w+):", re.search(r"const SPACE_OPTS = \{(.*?)\};", ui, re.S).group(1), re.M))
check("T5 every space type of the table is a UI space option", set(cp.SPACE_DEFAULT_MOVEMENT) == sp, (set(cp.SPACE_DEFAULT_MOVEMENT) ^ sp))

# ---- every movement named exists where it is used -------------------------------------------------------------------------------
names = set(cp.SPACE_DEFAULT_MOVEMENT.values()) | set(cp.ROOM_MOVEMENT.values()) | set(cp.CATEGORY_MOVEMENT.values()) | {cp.DEFAULT_MOVEMENT}
ui_move = set(re.findall(r"^\s*(\w+):", re.search(r"const MOVEMENT_OPTS = \{(.*?)\};", ui, re.S).group(1), re.M))
check("T6 every movement of the table is in the UI MOVEMENT_OPTS (a missing one would show the first option: the July 10 bug)",
      (names - {"stand_look_around"}) <= ui_move, names - ui_move)
check("T7 every movement of the table has a Luma prompt token (a missing one silently becomes walk_in_explore)",
      names <= set(vg._LUMA_MOVEMENT_TOKENS), names - set(vg._LUMA_MOVEMENT_TOKENS))
check("T8 every space type of the table is a known space for the other prompt tables",
      all(s in vg._VEO_SPACE_TOKENS for s in cp.SPACE_DEFAULT_MOVEMENT if s in ("large", "medium", "bedroom", "small", "corridor", "outdoor", "elevated")), "")
check("T9 the UI labels the facade/outward options and no longer recommends the reverse dolly (reveal_pullback)",
      "approach_facade:" in ui and "outward_view:" in ui and "sconsigliato" in ui and "⭐ Avvicinamento con profondità" not in ui)

# ---- the intended differences from the pre-consolidation behaviour (nothing else changed) --------------------------------------
OLD_SPACE = {"large": "walk_in_explore", "medium": "walk_in_gentle", "bedroom": "walk_in_gentle", "small": "subtle_rotate",
             "corridor": "walk_through", "outdoor": "reveal_pullback", "elevated": "step_out_onto"}      # video_generation + ui.html
OLD_VISION = {"large": "walk_in_explore", "medium": "walk_in_explore", "bedroom": "walk_in_gentle", "small": "subtle_rotate",
              "corridor": "walk_through", "outdoor": "reveal_pullback", "elevated": "step_out_onto"}     # vision_analysis (the one URL drafts used)
OLD_CATEGORY = {"exterior": "reveal_pullback", "outdoor": "walk_toward", "living": "walk_in_explore", "kitchen": "walk_in_gentle",
                "bedrooms": "stand_look_around", "bathrooms": "subtle_rotate"}
diff_space = {k: (OLD_SPACE[k], cp.SPACE_DEFAULT_MOVEMENT[k]) for k in OLD_SPACE if OLD_SPACE[k] != cp.SPACE_DEFAULT_MOVEMENT[k]}
check("D1 space table: ONLY outdoor, elevated and medium changed (medium: the manual UI and server said walk_in_gentle, the photo analysis said walk_in_explore; "
      "the analysis' value, the one every URL job actually got, is kept)",
      diff_space == {"outdoor": ("reveal_pullback", "approach_facade"), "elevated": ("step_out_onto", "outward_view"), "medium": ("walk_in_gentle", "walk_in_explore")}, diff_space)
check("D2 versus the photo-analysis table: only outdoor and elevated changed",
      {k for k in OLD_VISION if OLD_VISION[k] != cp.SPACE_DEFAULT_MOVEMENT[k]} == {"outdoor", "elevated"})
diff_cat = {k: (OLD_CATEGORY[k], cp.CATEGORY_MOVEMENT[k]) for k in OLD_CATEGORY if OLD_CATEGORY[k] != cp.CATEGORY_MOVEMENT[k]}
check("D3 scraper categories: ONLY exterior and outdoor changed", diff_cat == {"exterior": ("reveal_pullback", "approach_facade"), "outdoor": ("walk_toward", "outward_view")}, diff_cat)
check("D4 the two outside categories are derived from the room table (facade / garden), not copied",
      cp.CATEGORY_MOVEMENT["exterior"] == cp.ROOM_MOVEMENT["building_exterior"] and cp.CATEGORY_MOVEMENT["outdoor"] == cp.ROOM_MOVEMENT["garden"])

# ---- movement_for ---------------------------------------------------------------------------------------------------------------
check("M1 rooms: facade approaches, garden/pool/other/balcony/terrace look outward",
      cp.movement_for("outdoor", "deep", "building_exterior") == "approach_facade"
      and all(cp.movement_for("outdoor", "deep", r) == "outward_view" for r in ("garden", "pool", "other_exterior"))
      and all(cp.movement_for("elevated", "medium", r) == "outward_view" for r in ("balcony", "terrace")))
check("M2 interior rooms follow the space type; the shallow large room keeps its old special case",
      cp.movement_for("large", "medium", "living") == "walk_in_explore" and cp.movement_for("large", "shallow", "living") == "stand_look_around"
      and cp.movement_for("bedroom", "medium", "bedroom") == "walk_in_gentle" and cp.movement_for("small", "shallow", "bathroom") == "subtle_rotate")
check("M3 unknown room (the Florence fallback) -> the space default; unknown space -> walk_in_explore",
      cp.movement_for("outdoor", "deep", None) == "approach_facade" and cp.movement_for("nonsense") == "walk_in_explore")
check("M4 the photo analysis result carries the room-based movement (no second table)",
      va._build_input_result("ground_exterior", "deep", 0.9, "x", "claude", room="garden")["suggested_movement"] == "outward_view"
      and va._build_input_result("ground_exterior", "deep", 0.9, "x", "claude", room="building_exterior")["suggested_movement"] == "approach_facade"
      and va._build_input_result("elevated", "medium", 0.9, "x", "claude", room="terrace")["suggested_movement"] == "outward_view")

# ---- no leftover literal copies ------------------------------------------------------------------------------------------------
src = {f: open(f, encoding="utf-8").read() for f in ("video_generation.py", "vision_analysis.py", "listing_scraper.py", "api_server.py")}
check("N1 no source file but camera_plan.py writes a space -> movement table any more",
      not re.search(r'"outdoor":\s*"(reveal_pullback|approach_facade|outward_view|walk_toward)"', "".join(src.values()))
      and not re.search(r'"elevated":\s*"(step_out_onto|outward_view)"', "".join(src.values())))
check("N2 the made-up fallback 'gentle_arc' is gone from the scraper's scene builders", 'get(category, "gentle_arc")' not in src["listing_scraper.py"] and 'get(real_category, "gentle_arc")' not in src["listing_scraper.py"])
sel = {"selected": {c: [{"local_path": c}] for c in ls.PRIORITY_ORDER}}
scenes = {s["category"]: s["pov_movement"] for s in ls.build_standard_video_scenes_config(sel, {}, 5)}
check("N3 the standard scene builder gives the facade the approach and the garden/terrace the outward look, the rest as before",
      scenes == {"exterior": "approach_facade", "living": "walk_in_explore", "kitchen": "walk_in_gentle", "bedrooms": "stand_look_around",
                 "bathrooms": "subtle_rotate", "outdoor": "outward_view"}, scenes)
print(f"\n{sum(res)}/{len(res)} PASS"); sys.exit(0 if all(res) else 1)
