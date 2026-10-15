"""Luma prompt rules (2026-10-15): mirrors may only reflect the empty room. Source-level check (video_generation imports
fal_client, which the sandbox may not have). Run: python3 test_prompt_rules.py"""
import re, sys
src = open("video_generation.py").read()
m = re.search(r"_LUMA_RULES = \((.*?)\n\)", src, re.S)
rules = " ".join(re.findall(r'"([^"]*)"', m.group(1))) if m else ""
fails = 0
def check(n, c):
    global fails
    print("PASS" if c else "FAIL", n)
    fails += 0 if c else 1
check("R1 rules constant found", bool(rules))
check("R2 mirror reflections: no person/figure/face/camera operator", all(w in rules for w in ("must reflect only the empty room", "no person", "no human figure", "no face", "no camera operator")))
check("R3 old mirror rule and no-people rule still there", "no mirrors or reflective surfaces that were not already present" in rules and "no people, no human shadows or silhouettes" in rules)
check("R4 only one definition of the Luma rules (no parallel copy)", len(re.findall(r"no human shadows", src)) == 1)
check("R5 constant still used by the Luma prompt", 'f"{motion}, {pace}, {_LUMA_RULES}"' in src)
print("ALL PASS" if not fails else f"{fails} FAIL")
sys.exit(1 if fails else 0)
