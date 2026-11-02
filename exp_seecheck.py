"""
exp_seecheck.py -- EXPERIMENT TOOL, NOT PRODUCTION (2026-11-02). Does Claude really SEE the objects it reports?
For each image it asks Claude for the main objects with a bounding box, draws the boxes with numbered labels on a copy of the image
(jobs/_test_scratch/seecheck_<label>.jpg) and prints the list, so a person can check every claim against the picture in seconds.
A reported object with no visible thing inside its box = an invented object in the evaluator itself (false positive risk).
  python3 exp_seecheck.py LABEL=path_or_name.jpg [LABEL=...]     (a bare name is looked up in jobs/_test_scratch)
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import exp_endframe as ef
import exp_director as dr

PROMPT = """List the main objects and fixtures you can see in this photo of a room, at most 25 items, each with its count and a bounding box.
Be literal: include only what you can actually point at. If you are not sure that something is there, leave it out.
Answer with JSON only: {"items": [{"name": "short name", "count": 1, "box": [x0, y0, x1, y1], "confidence": "high|medium|low"}]}
box values are fractions of the image width and height between 0 and 1 (x0,y0 top-left; x1,y1 bottom-right)."""


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    ef.OUT_DIR.mkdir(parents=True, exist_ok=True)
    usage = {}
    for item in sys.argv[1:]:
        label, _, p = item.partition("=")
        path = Path(p) if "/" in p else ef.OUT_DIR / p
        if not path.is_file():
            print(f"{label}: file not found ({path})")
            continue
        res = dr.ask_claude(PROMPT, [path], usage)
        im = Image.open(path).convert("RGB")
        d = ImageDraw.Draw(im)
        W, H = im.size
        print(f"== {label} ({path.name})")
        for i, it in enumerate(res.get("items", []), 1):
            try:
                x0, y0, x1, y1 = [float(v) for v in it["box"]]
                d.rectangle([x0 * W, y0 * H, x1 * W, y1 * H], outline=(255, 0, 0), width=max(2, W // 400))
                d.text((x0 * W + 4, y0 * H + 2), str(i), fill=(255, 255, 0))
            except Exception:
                pass
            print(f"   {i:2d}. {it.get('name')} x{it.get('count')} [{it.get('confidence')}] box {it.get('box')}")
        out = ef.OUT_DIR / f"seecheck_{label}.jpg"
        im.save(out, quality=90)
        print("   marked image:", ef.PUBLIC + out.name)
    print(f"Claude tokens in/out {usage.get('in')}/{usage.get('out')} (~USD {round((usage.get('in', 0) * 2 + usage.get('out', 0) * 10) / 1e6, 3)})")


if __name__ == "__main__":
    main()
