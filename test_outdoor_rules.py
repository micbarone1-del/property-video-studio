"""P3 + P4 (2026-10-28), from job cc33f8af: the closing scene was an aerial photo of the Colosseum that moved like a drone toward a 'facade'.
P3: an outside space that is not recognised gets the minimal move; the facade approach only for the first facade of the video.
P4: aerial / drone views and landmarks not seen from the property are neither exterior nor outdoor (classifier prompts).
No network, no key. Run: python3 test_outdoor_rules.py"""
import os, sys, types
sys.path.insert(0, os.getcwd())
for _m in ("fal_client", "anthropic"):
    try: __import__(_m)
    except ImportError: sys.modules[_m] = types.ModuleType(_m)
import camera_plan as cp
fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

# ---- P3 movement
check("O1 outdoor, room not recognised (None) -> minimal", cp.movement_for("outdoor", "deep", None) == "subtle_rotate")
check("O2 outdoor, a room outside the table -> minimal", cp.movement_for("outdoor", "deep", "other_interior") == "subtle_rotate")
check("O3 the real facade still gets the approach", cp.movement_for("outdoor", "deep", "building_exterior") == "approach_facade")
check("O4 garden / pool / other_exterior / terrace / balcony keep the outward look",
      all(cp.movement_for("outdoor" if r in ("garden", "pool", "other_exterior") else "elevated", "deep", r) == "outward_view"
          for r in ("garden", "pool", "other_exterior", "terrace", "balcony")))
check("O5 interiors are untouched", cp.movement_for("large", "medium", "living") == "walk_in_explore" and cp.movement_for("bedroom", None, "bedroom") == "walk_in_gentle")
scenes = [{"pov_movement": "approach_facade"}, {"pov_movement": "walk_in_explore"}, {"pov_movement": "approach_facade"}, {"pov_movement": "outward_view"}]
ch = cp.keep_first_facade_approach(scenes)
check("O6 the first facade approach stays, a later one becomes minimal", ch == [2] and scenes[0]["pov_movement"] == "approach_facade" and scenes[2]["pov_movement"] == "subtle_rotate")
check("O7 nothing else is touched", scenes[1]["pov_movement"] == "walk_in_explore" and scenes[3]["pov_movement"] == "outward_view")
check("O8 no facade at all / empty list: no change, no error", cp.keep_first_facade_approach([{"pov_movement": "walk_in_explore"}]) == [] and cp.keep_first_facade_approach([]) == [] and cp.keep_first_facade_approach(None) == [])
check("O9 the rule is applied in the ONE shared function of both URL and partner paths", "camera_plan.keep_first_facade_approach(scenes_config)" in open("api_server.py").read())

# ---- P4 prompts
import listing_scraper as ls
import vision_analysis as va
p = ls._VISION_CLASSIFY_PROMPT
check("O10 classifier: aerial / drone / satellite are NOT exterior or outdoor -> other", "AERIAL" in p and "DRONE" in p and "answer other" in p.split("AERIAL")[1])
check("O11 classifier: landmark or monument from outside the property is excluded", "landmark or monument" in p)
check("O12 classifier: the view from the home's OWN window / balcony is still allowed", "view FROM A WINDOW of this home" in p and "this home's own balcony, terrace or window" in p)
check("O13 classifier still ends with the one-word answer line", p.rstrip().endswith("exterior, living, kitchen, bedrooms, bathrooms, outdoor or other."))
check("O14 room prompt: an aerial photo is other_exterior, not building_exterior", "aerial or drone photo" in va.ROOM_PROMPT and "other_exterior" in va.ROOM_PROMPT.split("aerial or drone photo")[1][:120])
print(f"\nRESULT: {'ALL PASS' if not fails else 'FAILURES'} ({total - len(fails)}/{total})")
sys.exit(1 if fails else 0)
