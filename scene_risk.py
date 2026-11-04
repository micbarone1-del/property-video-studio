"""scene_risk.py - the ONE registry of scene risk (2026-11-04, Michele: "deve essere un file dinamico delle scene a rischio ... che continua a imparare").

SHADOW MODE: this module only RECORDS what the production clip QC already decided and SUMMARISES it. Nothing here changes a selection, a prompt, a rework or a
job state; if recording fails the job goes on (never raises). Cost: zero (no new model call). The selector / director will read `summary()` later, only
once there is enough data (MIN_N) and Michele has seen it in the autonomous-management report (the planned operator dashboard, backlog NEXT MILESTONE).

What is recorded (one JSON line per QC verdict, append-only, in <PVS_DATA_DIR>/scene_risk_events.jsonl, outside jobs/ and outside git):
  ts, job, scene, cat (room category), move (pov_movement), tier, stage ("first" = first generation QC, "rework" = QC of a regenerated clip),
  verdict (pass / flag / reject / failed = clip not generated), previous (rework only: the verdict the scene had before).
Successes are recorded too: without them no rate can be computed.
Reading it: a first-generation flag/reject is a "first_flag"; the rework QC then says pass ("resolved": the problem was random or fixed) or flag/reject
("persistent": it survived the rework - the strong signal, the one Michele asked to learn from).

  python3 scene_risk.py            prints the summary of the registry
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MIN_N = 10                    # a bucket needs this many QC'd scenes before it may be called risky
PERSISTENT_RATE = 0.25        # share of scenes still flagged after a rework that makes a bucket "risky"
_LOCK = threading.Lock()


def _file() -> Path:
    """Read at call time so a test instance (PVS_DATA_DIR) and the tests keep their own file."""
    p = os.getenv("PVS_SCENE_RISK_FILE")
    if p:
        return Path(p)
    return Path(os.getenv("PVS_DATA_DIR") or HERE) / "scene_risk_events.jsonl"


def enabled() -> bool:
    """On by default; PVS_SCENE_RISK=0 turns the recording off; never records fake-provider runs or a run started from a test_*.py script (their clips are not real)."""
    if os.getenv("PVS_FAKE_PROVIDERS", "").strip() == "1":
        return False
    v = os.getenv("PVS_SCENE_RISK")
    if v is not None:                       # an explicit setting always wins (test_scene_risk.py forces it on)
        return v.strip().lower() not in ("0", "false", "no", "off")
    # 2026-11-04: the existing test scripts (test_rework_qc.py ...) call qc_redone with FAKE clips; they must never write into the real registry
    return not os.path.basename(sys.argv[0] or "").startswith("test_")


def category_of(scene) -> str:
    s = scene or {}
    return str(s.get("category") or s.get("room") or s.get("room_type") or s.get("space_type") or "?").lower()


def record(job_id, scene_id, scene, verdict, *, stage="first", movement=None, tier=None, previous=None) -> bool:
    """Appends one event. Returns True when written. NEVER raises: the registry must not be able to break a job."""
    try:
        if not enabled() or verdict not in ("pass", "flag", "reject", "failed"):
            return False
        ev = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "job": str(job_id), "scene": str(scene_id), "cat": category_of(scene),
              "move": str(movement or (scene or {}).get("pov_movement") or "?"), "tier": tier, "stage": stage, "verdict": verdict}
        if previous:
            ev["previous"] = previous
        line = json.dumps(ev, ensure_ascii=False) + "\n"
        p = _file()
        with _LOCK:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(line)
        return True
    except Exception as e:
        try:
            import logging
            logging.getLogger(__name__).warning(f"[scene_risk] could not record: {e}")
        except Exception:
            pass
        return False


def load_events() -> list:
    p = _file()
    out = []
    try:
        for ln in p.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(ln))
            except Exception:
                continue          # one damaged line never hides the rest
    except FileNotFoundError:
        pass
    return out


def _bucket(events, keyf) -> dict:
    g = {}
    for e in events:
        k = keyf(e)
        b = g.setdefault(k, {"n": 0, "first_flag": 0, "rework_checked": 0, "persistent": 0, "resolved": 0, "failed": 0})
        if e.get("verdict") == "failed":
            b["failed"] += 1
        elif e.get("stage") == "first":
            b["n"] += 1
            b["first_flag"] += 1 if e["verdict"] in ("flag", "reject") else 0
        elif e.get("stage") == "rework":
            b["rework_checked"] += 1
            if e["verdict"] in ("flag", "reject"):
                b["persistent"] += 1
            else:
                b["resolved"] += 1
    for b in g.values():
        b["first_flag_rate"] = round(b["first_flag"] / b["n"], 2) if b["n"] else None
        b["persistent_rate"] = round(b["persistent"] / b["rework_checked"], 2) if b["rework_checked"] else None
        b["risky"] = bool(b["n"] >= MIN_N and b["rework_checked"] >= 3 and (b["persistent_rate"] or 0) >= PERSISTENT_RATE)
    return g


def summary(events=None) -> dict:
    """JSON-friendly summary for the report / dashboard. `risky` is informational only (shadow mode): no code acts on it yet."""
    ev = load_events() if events is None else events
    return {"events": len(ev), "min_n": MIN_N, "persistent_rate_threshold": PERSISTENT_RATE,
            "by_category": _bucket(ev, lambda e: e.get("cat", "?")),
            "by_movement": _bucket(ev, lambda e: e.get("move", "?")),
            "by_category_movement": _bucket(ev, lambda e: f"{e.get('cat', '?')}|{e.get('move', '?')}"),
            "first_ts": ev[0]["ts"] if ev else None, "last_ts": ev[-1]["ts"] if ev else None}


def main():
    s = summary()
    print(f"SCENE RISK REGISTRY (shadow mode): {s['events']} events, {s['first_ts']} -> {s['last_ts']}; risky = n>={MIN_N} and persistent rate >= {PERSISTENT_RATE}")
    for name in ("by_category", "by_movement", "by_category_movement"):
        print(f"{name}:")
        for k, b in sorted(s[name].items(), key=lambda kv: -(kv[1]["persistent_rate"] or 0)):
            print(f"  {k}: n {b['n']} | first flag {b['first_flag']} ({b['first_flag_rate']}) | after rework: persistent {b['persistent']}, resolved {b['resolved']} | failed {b['failed']}{' | RISKY' if b['risky'] else ''}")


if __name__ == "__main__":
    sys.exit(main())
