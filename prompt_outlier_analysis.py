"""prompt_outlier_analysis.py - what do the prompts of the rushing clips have in common? (2026-11-04) READ-ONLY, no API, no spend.

Input: the key files of the A/B rounds (code -> exact prompt sent to Luma) and Michele's blind speed labels (clip_speed_labels.json).
Michele's hypothesis: Luma tries to REACH the target within the 5 s, so the more the prompt points at a far destination, the faster the clip.
This lists every distinct prompt with its outcome counts, how many times and in which words the prompt points at a destination, and the fast-rate per bucket.
Same prompt, different outcomes (reps) = random variation of Luma; a prompt feature that moves the fast-rate = a cause we can remove.
"""
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOBS_DIR = Path(os.environ.get("PVS_JOBS_DIR") or (HERE / "jobs"))
D = JOBS_DIR / "_test_scratch" / "prompt_ab"
DEST = re.compile(r"\b(toward|towards|pushes|push-in|push|across|reach|reaches|beyond|entrance|gate|gates|door|building|house|houses|far|distant|path|ahead)\b", re.I)
TARGET_RE = re.compile(r"push-in toward (.+?)(?:, advancing|, the camera keeps)", re.I | re.S)
END_RE = re.compile(r"The shot ends on a view of the (?:room|scene) showing.*$", re.S)


def features(prompt: str) -> dict:
    t = TARGET_RE.search(prompt)
    e = END_RE.search(prompt)
    movement_part = prompt[: prompt.find("this is a frozen photograph")] if "this is a frozen photograph" in prompt else prompt
    end_part = e.group(0) if e else ""
    return {"target": (t.group(1).strip() if t else "?"), "end_view": end_part,
            "dest_move": len(DEST.findall(movement_part)), "dest_end": len(DEST.findall(end_part)), "words": len(prompt.split())}


def main():
    labels = json.loads((HERE / "clip_speed_labels.json").read_text())
    groups = defaultdict(lambda: {"n": 0, "fast": 0, "slightly_fast": 0, "ok": 0, "slow": 0, "prompt": ""})
    for run, codes in labels.items():
        if run.startswith("_"):
            continue
        kf = D / f"key_{run}.json"
        if not kf.exists():
            continue
        for r in json.loads(kf.read_text()):
            lab = codes.get(r["code"])
            if not lab:
                continue
            g = groups[(run, r["case"], r["variant"], r["prompt"])]
            g["n"] += 1
            g[lab] += 1
            g["prompt"] = r["prompt"]
    rows = []
    for (run, case, var, _), g in groups.items():
        f = features(g["prompt"])
        rows.append({"case": case, "var": var, **g, **f})
    rows.sort(key=lambda r: (r["case"], r["var"]))
    print(f"{len(rows)} distinct prompts\n")
    print("case        var n  fast slight ok slow | dest_move dest_end words | target")
    for r in rows:
        print(f"{r['case']:<11} {r['var']:<3} {r['n']:<2} {r['fast']:<4} {r['slightly_fast']:<6} {r['ok']:<2} {r['slow']:<4} | {r['dest_move']:<9} {r['dest_end']:<8} {r['words']:<5} | {r['target'][:60]}")
    print("\nend-view sentence of each prompt that had at least one fast clip, and of the same case's best prompt:")
    shown = set()
    for r in rows:
        if r["fast"] and (r["case"], r["var"]) not in shown:
            shown.add((r["case"], r["var"]))
            print(f"- {r['case']} {r['var']} (fast {r['fast']}/{r['n']}): {r['end_view'][:330]}")
    print("\nfast-rate by how often the END-VIEW description points at a destination (A, B, G, N, F only; C and D are not forward moves):")
    buckets = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        if r["var"] in ("C", "D"):
            continue
        b = "0-2" if r["dest_end"] <= 2 else ("3-4" if r["dest_end"] <= 4 else "5+")
        buckets[b][0] += r["n"]; buckets[b][1] += r["fast"]; buckets[b][2] += r["slightly_fast"]
    for b in ("0-2", "3-4", "5+"):
        if b in buckets:
            n, fa, sl = buckets[b]
            print(f"  destination words in end view {b:<4} clips={n:<3} fast={fa} ({100*fa/n:.0f}%)  slightly_fast={sl}")
    print("\nfast-rate by target distance class (near = N or F; far = A, B, G):")
    cls = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        if r["var"] in ("C", "D"):
            continue
        c = "near" if r["var"] in ("N", "F") else "far"
        cls[c][0] += r["n"]; cls[c][1] += r["fast"]; cls[c][2] += r["slightly_fast"]
    for c in ("far", "near"):
        n, fa, sl = cls[c]
        print(f"  {c:<5} clips={n:<3} fast={fa} ({100*fa/max(n,1):.0f}%)  slightly_fast={sl}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
