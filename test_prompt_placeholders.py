"""Guard: no narration prompt may reach Claude with an unfilled {PLACEHOLDER} or a leftover doubled brace.
Regression 2026-11-20: since fed544e (12 Nov) the blocks prompt sent the literal text {NUMBERS_RULE} / {VERB_RULE}
because part of the string was concatenated as a plain (non f-string) literal."""
import re, sys
import scene_script as ss
ok = 0; bad = 0
def check(name, cond, info=""):
    global ok, bad
    if cond: ok += 1; print("PASS", name)
    else: bad += 1; print("FAIL", name, info)
labels = ["x"] * 6
prompts = {
    "build_prompt": ss.build_prompt("d", "a", "Gallo", labels),
    "build_anchored_prompt": ss.build_anchored_prompt("d", "a", "Gallo", labels),
    "build_blocks_prompt": ss.build_blocks_prompt("d", "a", "Gallo", labels, list(range(6))),
    "build_tighten_prompt": ss.build_tighten_prompt(["Una frase."], [(0, 5)], "d", "Gallo"),
}
for n, p in prompts.items():
    left = sorted(set(re.findall(r"\{[A-Za-z_][A-Za-z_0-9]*\}", p)))
    check(f"PH-{n}: no unfilled placeholder", not left, str(left))
    check(f"PH-{n}: no doubled braces left", "{{" not in p and "}}" not in p)
for n in ("build_prompt", "build_anchored_prompt", "build_blocks_prompt"):
    check(f"PH-{n}: carries the numbers and verb rules", ss.NUMBERS_RULE in prompts[n] and ss.VERB_RULE in prompts[n])
print(f"RESULT: {ok} passed, {bad} failed"); sys.exit(1 if bad else 0)
