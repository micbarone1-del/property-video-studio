"""learning_apply.py - phases 3 and 4 of the learning loop (2026-11-25). See LEARNING_LOOP.md.
Reads ONLY <PVS_DATA_DIR>/learning_rules.json (written offline by learning_loop.py: rules that HELD on jobs not used to find them). It never imports
learning_loop. Classification comes from scene_kinds.py (shared with learning_loop).
PHASE 3 shadow (on by default, changes nothing): matching() says which held rules a scene matches; scene_risk.record stores the ids in the same
  registry line ("learn_shadow"), so firing counts and outcomes come from the existing registry. report() prints them.
PHASE 4 apply (OFF by default): PVS_LEARN_APPLY=1 AND PVS_LEARN_APPLY_UNTIL=YYYY-MM-DD (expiry, mandatory) AND no revert file. The ONLY change is
  scene["pov_movement"], to a movement that really occurred in the registry with a clearly lower bad rate; prompt text is never touched. Rules that do not
  involve move/plan_kind are shadow-only. revert_check() writes learning_apply_revert.json (apply stops) if the rates get worse.
Never raises. CLI: python3 learning_apply.py [report|check]"""
import json
import os
import sys
import time
from pathlib import Path

import scene_kinds

HERE = Path(__file__).resolve().parent
SHADOW_DEADLINE = "2026-12-14"   # LEARNING_LOOP.md phase 3: 40 firing scenes or this date, the first of the two
SHADOW_TARGET = 40
MIN_N = 10
MIN_MOVE_GAIN = 0.8              # the replacement movement must have a bad rate <= 0.8 x the current one's
REVERT_GAP = 0.05                # after applying, overall bad rate may not exceed the before-rate by more than this
_CACHE = {"mtime": None, "path": None, "rules": []}


def _data() -> Path:
    return Path(os.getenv("PVS_DATA_DIR") or HERE)


def rules_file() -> Path:
    return Path(os.getenv("PVS_LEARNING_RULES_FILE") or _data() / "learning_rules.json")


def revert_file() -> Path:
    return _data() / "learning_apply_revert.json"


def load_rules():
    """Tolerant: a missing, empty or broken file means no rules. Cached by mtime."""
    try:
        p = rules_file()
        mt = p.stat().st_mtime if p.exists() else None
        if _CACHE["path"] == str(p) and _CACHE["mtime"] == mt:
            return _CACHE["rules"]
        rules = []
        if mt is not None:
            for r in (json.loads(p.read_text(encoding="utf-8")).get("rules") or []):
                if isinstance(r, dict) and r.get("id") and isinstance(r.get("cond"), list):
                    rules.append({"id": str(r["id"]), "label": r.get("label"), "cond": [tuple(c) for c in r["cond"] if len(c) == 2]})
        _CACHE.update(path=str(p), mtime=mt, rules=rules)
        return rules
    except Exception:
        return []


def matching(scene, move, cat, tier):
    """Ids of the held rules this scene matches. tier None = unknown: rules that need the tier do not match."""
    try:
        f = scene_kinds.scene_features(scene, move, cat, tier)
        if tier is None:
            f["tier"] = None
        return [r["id"] for r in load_rules() if all(f.get(k) == v for k, v in r["cond"])]
    except Exception:
        return []


def _auto_state(now=None):
    """Automatic switch written by learning_cycle.py (learning_state.json): {"apply": {"on", "until", "rules"}}. Returns the list of proven rule ids or None."""
    try:
        a = (json.loads((_data() / "learning_state.json").read_text(encoding="utf-8")).get("apply") or {})
        if a.get("on") and (now or time.strftime("%Y-%m-%d")) <= str(a.get("until") or ""):
            return list(a.get("rules") or [])
    except Exception:
        pass
    return None


def apply_enabled(now=None) -> bool:
    """Manual switch (env + mandatory expiry) OR the automatic one (only for the rules learning_cycle proved). The revert file blocks both."""
    try:
        if revert_file().exists():
            return False
        if os.getenv("PVS_LEARN_APPLY", "").strip().lower() in ("1", "true", "yes", "on"):
            until = os.getenv("PVS_LEARN_APPLY_UNTIL", "").strip()
            if until and (now or time.strftime("%Y-%m-%d")) <= until:
                return True
        return _auto_state(now) is not None
    except Exception:
        return False


def allowed_rule_ids(now=None):
    """None = every held rule (manual switch); a list = only the rules learning_cycle proved (automatic switch)."""
    try:
        manual = os.getenv("PVS_LEARN_APPLY", "").strip().lower() in ("1", "true", "yes", "on") and os.getenv("PVS_LEARN_APPLY_UNTIL", "").strip() >= (now or time.strftime("%Y-%m-%d"))
        return None if manual else (_auto_state(now) or [])
    except Exception:
        return []


def _events():
    try:
        import scene_risk
        out = []
        p = scene_risk._file()
        if p.exists():
            for ln in p.read_text(encoding="utf-8").splitlines():
                try:
                    out.append(json.loads(ln))
                except Exception:
                    pass
        return out
    except Exception:
        return []


def _bad(e):
    return e.get("verdict") in ("flag", "reject", "failed")


def _ev_features(e):
    return scene_kinds.scene_features({"anchor": e.get("anchor"), "depth": e.get("depth")}, e.get("move"), e.get("cat"), e.get("tier"))


def pick_alt_move(current, events, ctx=None):
    """A movement seen in the registry (so a valid one) with n >= MIN_N and a bad rate <= MIN_MOVE_GAIN x the current movement's, compared ONLY among scenes that
    share the environment conditions of the rule (ctx: its condition without move / plan_kind, e.g. depth=deep): the movement is not judged across different
    kinds of space. Events recorded before phase 2 have no depth/anchor, so a rule that needs them finds nothing and nothing changes. None if there is no clear winner."""
    try:
        want = [(k, v) for k, v in (ctx or []) if k not in ("move", "plan_kind")]
        first = []
        for e in events:
            if e.get("stage") != "first" or e.get("move") in (None, "?"):
                continue
            if want:
                f = _ev_features(e)
                if not all(f.get(k) == v for k, v in want):
                    continue
            first.append(e)
        by = {}
        for e in first:
            k = by.setdefault(e["move"], [0, 0]); k[1] += 1; k[0] += 1 if _bad(e) else 0
        cur = by.get(current)
        if not cur or cur[1] < MIN_N or not cur[0]:
            return None
        cur_rate = cur[0] / cur[1]
        best = None
        for m, (k, n) in by.items():
            if m == current or n < MIN_N:
                continue
            r = k / n
            if r <= MIN_MOVE_GAIN * cur_rate and (best is None or r < best[1]):
                best = (m, r)
        return best[0] if best else None
    except Exception:
        return None


def on_plan(scene, cat=None, tier=None) -> bool:
    """Planning hook. Returns True only if pov_movement was changed (phase 4). Touches nothing else but learn_* keys. Never raises."""
    try:
        if not isinstance(scene, dict) or not apply_enabled():
            return False
        move = scene.get("pov_movement")
        ids = matching(scene, move, cat or scene.get("category") or scene.get("space_type"), tier)
        allowed = allowed_rule_ids()
        movers = [r for r in load_rules() if r["id"] in ids and (allowed is None or r["id"] in allowed) and any(k in ("move", "plan_kind") for k, _ in r["cond"])]
        if not movers:
            return False
        events = _events()
        for r in movers:
            alt = pick_alt_move(move, events, ctx=r["cond"])
            if alt:
                scene["learn_prev_move"] = move
                scene["pov_movement"] = alt
                scene["learn_applied"] = [r["id"]]
                return True
        return False
    except Exception:
        return False


def revert_check(events=None, write=True):
    """After applying: compare the OVERALL first-pass bad rate after the first applied scene with the one before it (the whole rate, not only the subgroup),
    and the applied scenes with the rest after. Worse overall by REVERT_GAP, or applied scenes not better than the rest -> revert file."""
    ev = events if events is not None else _events()
    first = [e for e in ev if e.get("stage") == "first"]
    applied = [e for e in first if e.get("learn_applied")]
    if len(applied) < MIN_N:
        return {"status": "not enough applied scenes", "applied": len(applied)}
    t0 = min(e["ts"] for e in applied)
    before = [e for e in first if e["ts"] < t0]
    after = [e for e in first if e["ts"] >= t0]
    rest = [e for e in after if not e.get("learn_applied")]
    rate = lambda xs: (sum(1 for e in xs if _bad(e)) / len(xs)) if xs else None
    rb, ra, rap, rr = rate(before), rate(after), rate(applied), rate(rest)
    worse = (rb is not None and ra is not None and ra > rb + REVERT_GAP) or (rr is not None and rap is not None and rap >= rr)
    res = {"status": "REVERT" if worse else "ok", "applied": len(applied), "before": rb, "after": ra, "applied_rate": rap, "rest_rate": rr}
    if worse and write:
        try:
            revert_file().write_text(json.dumps({**res, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}), encoding="utf-8")
        except Exception:
            pass
    return res


def report(events=None):
    ev = events if events is not None else _events()
    first = [e for e in ev if e.get("stage") == "first"]
    fired = [e for e in first if e.get("learn_shadow")]
    rest = [e for e in first if not e.get("learn_shadow")]
    rate = lambda xs: (round(sum(1 for e in xs if _bad(e)) / len(xs), 3) if xs else None)
    per = {}
    for e in fired:
        for i in e["learn_shadow"]:
            k = per.setdefault(i, [0, 0]); k[1] += 1; k[0] += 1 if _bad(e) else 0
    today = time.strftime("%Y-%m-%d")
    return {"rules_loaded": len(load_rules()), "scenes_firing": len(fired), "target": SHADOW_TARGET, "deadline": SHADOW_DEADLINE,
            "phase3_due": len(fired) >= SHADOW_TARGET or today >= SHADOW_DEADLINE, "bad_rate_firing": rate(fired), "bad_rate_rest": rate(rest),
            "per_rule": {i: {"scenes": n, "bad": k} for i, (k, n) in per.items()}, "apply_enabled": apply_enabled(),
            "reverted": revert_file().exists()}


if __name__ == "__main__":
    print(json.dumps(revert_check(write=False) if (sys.argv[1:] or [""])[0] == "check" else report(), indent=1, ensure_ascii=False))
