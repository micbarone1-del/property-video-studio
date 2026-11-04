"""exp_risk_features.py - WHAT IN THE PHOTO makes a scene risky (2026-11-04, Michele: "analizza le foto con Claude vision per categorizzare le scene a rischio").
EXPERIMENT TOOL, NOT PRODUCTION. risk_table.py showed that room and plan type do NOT predict which scenes get flagged; this describes the source photo of every
scene we produced clips for with ONE fixed checklist (Claude vision, one call per photo, one image each) and compares, feature by feature, the share of flagged clips
of the scenes that have the feature with the scenes that do not.

  python3 exp_risk_features.py run [--cap 0.6] [--go]    asks Claude for the checklist of every scene photo (prints the cost estimate first; needs --go); saves risk_features.json
  python3 exp_risk_features.py report                    FREE: joins the features with the flagged share per scene (risk_table) and prints the comparison
  PVS_VOLUME_SCRATCH = where the runs are, PVS_JOBS_DIR = where the jobs are
Honest limits: about 20 scenes, so a difference between groups is a LEAD to check on new scenes, not a proof; a feature seen in fewer than 3 scenes on either side is marked weak.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
SCRATCH = Path(os.environ.get("PVS_VOLUME_SCRATCH") or (HERE / "jobs" / "_test_scratch"))
OUT = SCRATCH / "facade"
FEATURES_FILE = OUT / "risk_features.json"
IN_USD_PER_M, OUT_USD_PER_M = 3.0, 15.0
EST_USD_PER_PHOTO = 0.012
MIN_SIDE = 3                    # fewer scenes than this on either side = weak evidence

FLAGS = ("view_out_window", "sky_visible", "mirror_or_glass", "people_or_pets", "street_or_vehicles", "water_plants_curtains",
         "far_background", "long_depth", "tight_space", "low_light", "busy_clutter", "strong_wide_angle", "empty_room", "complex_architecture")

PROMPT = """This is the source photo of one scene of a real-estate video. An AI video model will turn it into a 5 second clip with the camera gliding slowly forward, and it tends to INVENT things that are not in the photo (new rooms, buildings, people) or to drift (rotate, go backward).
Describe the photo with this fixed checklist. Answer with JSON only, true/false for every flag, no extra keys except the three text fields:
{{"view_out_window": a window, glass door or balcony opening that shows the OUTSIDE takes a clear part of the frame,
 "sky_visible": sky is visible,
 "mirror_or_glass": a mirror, glass shower or other reflective surface shows reflections,
 "people_or_pets": a person or an animal is visible (also in a reflection),
 "street_or_vehicles": a street, road, car or other vehicle is visible,
 "water_plants_curtains": things that can sway or flow: water, trees, plants, curtains, flags,
 "far_background": an open scene with a distant background (skyline, street, landscape, far building),
 "long_depth": a deep room or corridor whose far end is far from the camera,
 "tight_space": the camera is very close to walls or furniture, little free floor in front,
 "low_light": dark or low light,
 "busy_clutter": many small objects or a very busy scene,
 "strong_wide_angle": visible perspective stretching or distortion typical of a wide-angle lens,
 "empty_room": an empty room without furniture,
 "complex_architecture": many balconies, arches, repeated windows or several building parts (typical of a facade),
 "dominant_subject": "what dominates the frame, 5 words max",
 "camera_height": "eye" or "high" or "low",
 "model_might_invent": "one short sentence: what a video model might invent beyond the edges of the frame"}}"""


def spend_usd(usage: dict) -> float:
    return round((usage.get("in", 0) * IN_USD_PER_M + usage.get("out", 0) * OUT_USD_PER_M) / 1e6, 3)


def clean(r: dict) -> dict:
    """Keeps the checklist only: every flag as a real bool (missing = False), the text fields as short strings."""
    out = {k: (r.get(k) is True or str(r.get(k)).lower() == "true") for k in FLAGS}
    out["dominant_subject"] = str(r.get("dominant_subject") or "")[:60]
    out["camera_height"] = str(r.get("camera_height") or "")[:10]
    out["model_might_invent"] = str(r.get("model_might_invent") or "")[:160]
    return out


def scene_cases() -> list:
    """Unique 'job:scene' of every scene we made clips for (from the saved run keys)."""
    seen = []
    for kf in sorted(OUT.glob("key_*.json")):
        try:
            for k in json.loads(kf.read_text()):
                if k.get("ok") and k.get("case") and k["case"] not in seen:
                    seen.append(k["case"])
        except Exception:
            continue
    return seen


def compare(rows: dict, features: dict) -> list:
    """rows: {case: flagged share 0..1}; features: {case: cleaned dict}. -> [(flag, n_with, rate_with, n_without, rate_without, weak)] sorted by the gap."""
    out = []
    cases = [c for c in rows if c in features]
    for f in FLAGS:
        w = [rows[c] for c in cases if features[c].get(f)]
        wo = [rows[c] for c in cases if not features[c].get(f)]
        if not w or not wo:
            out.append((f, len(w), None, len(wo), None, True))
            continue
        out.append((f, len(w), round(sum(w) / len(w), 2), len(wo), round(sum(wo) / len(wo), 2), len(w) < MIN_SIDE or len(wo) < MIN_SIDE))
    return sorted(out, key=lambda t: -((t[2] - t[4]) if t[2] is not None else -9))


def run(cap, go):
    from dotenv import load_dotenv
    load_dotenv(HERE / ".env")
    import exp_volume as ev
    import exp_director as dr
    cases = scene_cases()
    est = round(len(cases) * EST_USD_PER_PHOTO, 2)
    print(f"{len(cases)} scene photos, estimated cost about {est} USD (cap {cap} USD).")
    if not go:
        print("Nothing done: add --go to run it.")
        return 0
    feats, usage = {}, {}
    try:
        feats = json.loads(FEATURES_FILE.read_text())
    except Exception:
        pass
    for c in cases:
        if c in feats:
            continue
        if spend_usd(usage) > cap:
            print(f"cap {cap} USD reached: stopped"); break
        job, _, i = c.partition(":")
        try:
            img, _kw, _sc = ev.scene_args(job, int(i))
            feats[c] = clean(dr.ask_claude(PROMPT, [str(img)], usage))
            print(c, "ok", flush=True)
        except Exception as e:
            print(c, "ERROR", str(e)[:120], flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    FEATURES_FILE.write_text(json.dumps(feats, ensure_ascii=False, indent=1))
    print(f"saved {len(feats)} scenes in {FEATURES_FILE}; spent about {spend_usd(usage)} USD")
    ev.add_spend(spend_usd(usage), "exp_risk_features run")
    return 0


def report():
    import risk_table as rt
    feats = json.loads(FEATURES_FILE.read_text())
    rows = rt.collect()
    sc = rt.aggregate(rows)
    rate = {c: s["flagged"] / s["n"] for c, s in sc.items()}
    print(f"RISK FEATURES: {len(feats)} scenes described, {len(rate)} scenes with clips (flagged share = Michele's label if any, else the detector)")
    print("feature | scenes WITH (flagged share) | scenes WITHOUT (flagged share) | note")
    for f, nw, rw, nwo, rwo, weak in compare(rate, feats):
        print(f"  {f} | {nw} ({rw if rw is not None else '-'}) | {nwo} ({rwo if rwo is not None else '-'}) | {'WEAK (fewer than %d scenes on one side)' % MIN_SIDE if weak else ''}")
    print("scenes, riskiest first:")
    for c, r in sorted(rate.items(), key=lambda kv: -kv[1]):
        f = feats.get(c)
        yes = ",".join(k for k in FLAGS if f and f.get(k)) if f else "(no photo description)"
        print(f"  {c} {round(r * 100)}% | {f.get('dominant_subject') if f else ''} | {yes} | may invent: {f.get('model_might_invent') if f else ''}")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["run"]:
        sys.exit(run(float(a[a.index("--cap") + 1]) if "--cap" in a else 0.6, "--go" in a))
    if a[:1] == ["report"]:
        sys.exit(report())
    print(__doc__)
