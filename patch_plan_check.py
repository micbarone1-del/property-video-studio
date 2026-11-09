"""One-off, idempotent: the judge (same call, no extra cost) also says how the clip compares with the director's plan; recorded in the shadow events. No verdict changes."""
import re
def sub(p, a, b, tag):
    s = open(p, encoding="utf-8").read()
    if b in s:
        print("already:", tag); return
    assert s.count(a) == 1, tag
    open(p, "w", encoding="utf-8").write(s.replace(a, b)); print("patched:", tag)
C = "clip_standard.py"
sub(C, "def evaluate(clip_path, usage_out=None, ask=None, model=None) -> dict:", '''def plan_lines(plan, n):
    """2026-11-09 (Michele): the judge compares what the camera really did with the director's PLAN (past the target / other direction = faster than planned). Same call, shadow only."""
    if not plan:
        return ""
    return ("\\nThe camera was PLANNED to do this: move=%s, travel=%s, target=%s. Also add to the JSON a key \\"plan_check\\": "
            "{\\"reached_target_at_frame\\": <1-%d, or null if never>, \\"past_target\\": true|false, \\"direction_matches_plan\\": true|false, "
            "\\"more_than_planned\\": \\"no|a_little|a_lot\\"} comparing what the camera really did with that plan."
            % (plan.get("move"), plan.get("travel"), str(plan.get("target"))[:80], n))


def evaluate(clip_path, usage_out=None, ask=None, model=None, plan=None) -> dict:''', "evaluate signature")
sub(C, "prompt = JUDGE_PROMPT.format(n=len(frames_tmp)) + geo_line", 'prompt = JUDGE_PROMPT.format(n=len(frames_tmp)) + geo_line + plan_lines(plan, len(frames_tmp))\n        res["plan"] = ({k: plan.get(k) for k in ("move", "travel", "target")} if plan else None)', "prompt")
sub(C, '"pace": res.get("pace")}', '"pace": res.get("pace"), "plan": res.get("plan"), "plan_check": j.get("plan_check")}', "record")
V = "vision_analysis.py"
sub(V, "_std = _cs.evaluate(video_path, usage_out=usage)", '''try:
                    import movement_director as _md
                    _plan = _md.last_plan(video_path)
                except Exception:
                    _plan = None
                _std = _cs.evaluate(video_path, usage_out=usage, plan=_plan)''', "hook")
T = "test_clip_standard.py"
sub(T, '\nprint("FAILS:", fails)', '''
calls.clear(); cs.evaluate(pan, ask=ask_pass, plan={"move": "forward", "travel": "short", "target": "the door"})
check("S26 plan given: the same judge call also asks how the camera compares with the plan (no extra call)", "PLANNED" in calls[0][1] and "plan_check" in calls[0][1] and len(calls) == 1)
calls.clear(); cs.evaluate(pan, ask=ask_pass)
check("S27 no plan: prompt unchanged", "PLANNED" not in calls[0][1])
rp = cs.evaluate(pan, ask=lambda im, p, u: '{"verdict": "pass", "plan_check": {"past_target": true}}', plan={"move": "static", "travel": "short", "target": "x"})
check("S28 plan_check passes through and is recorded; verdict untouched", rp["judge"]["plan_check"]["past_target"] is True and rp["plan"]["move"] == "static" and '"plan_check": j.get("plan_check")' in open(cs.__file__).read())
print("FAILS:", fails)''', "tests")
