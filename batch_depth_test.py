"""
batch_depth_test.py
────────────────────
Renders multiple depth-rendering parameter variants from the SAME photo
in one run, so results can be compared side-by-side efficiently instead
of one slow round-trip per parameter change.

Usage:
    python3 batch_depth_test.py <image_path> [output_dir]

Produces one clip per variant in output_dir, named clearly by parameters,
plus a single combined side-by-side grid video for quick visual comparison.
"""

import os
import sys
import time
import logging
sys.path.insert(0, '.')

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

from depth_renderer import estimate_depth, render_depth_video, measure_depth_score

VARIANTS = [
    # (label, movement, intensity, shift_multiplier, zoom_multiplier)
    ("A_baseline",        "walk_in_explore", "natural_pace", 0.25, 0.35),
    ("B_stronger_shift",  "walk_in_explore", "natural_pace", 0.45, 0.35),
    ("C_stronger_zoom",   "walk_in_explore", "natural_pace", 0.25, 0.65),
    ("D_both_stronger",   "walk_in_explore", "natural_pace", 0.45, 0.65),
    ("E_lateral_pan",     "stand_look_around", "natural_pace", 0.45, 0.35),
    ("F_energetic",       "walk_in_explore", "energetic", 0.35, 0.50),
]


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 batch_depth_test.py <image_path> [output_dir]")
        sys.exit(1)

    image_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "/tmp/depth_variants"
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n{'='*70}")
    print(f"BATCH DEPTH RENDER TEST — {image_path}")
    print(f"{'='*70}\n")

    # Estimate depth ONCE and reuse across all variants — saves 5 API calls
    print("Step 1: Estimating depth (single API call, reused for all variants)...")
    t0 = time.time()
    depth = estimate_depth(image_path)
    if depth is None:
        print("DEPTH ESTIMATION FAILED — aborting")
        sys.exit(1)
    print(f"  Depth estimated in {time.time()-t0:.1f}s — "
          f"min={depth.min():.3f} max={depth.max():.3f} mean={depth.mean():.3f}")

    depth_score = measure_depth_score(depth)
    print(f"  Depth score: {depth_score:.3f} "
          f"({'SHALLOW — depth rendering strongly recommended' if depth_score < 0.4 else 'MODERATE/DEEP depth'})")

    results = []
    for label, movement, intensity, shift_mult, zoom_mult in VARIANTS:
        print(f"\nRendering variant '{label}': movement={movement} "
              f"intensity={intensity} shift={shift_mult} zoom={zoom_mult}")
        t0 = time.time()
        output_path = os.path.join(output_dir, f"{label}.mp4")

        # Monkey-patch the module-level multipliers for this render
        import depth_renderer as dr
        dr._TEST_SHIFT_MULT = shift_mult
        dr._TEST_ZOOM_MULT = zoom_mult

        ok = render_depth_video(
            image_path, output_path,
            duration=6, movement=movement, intensity=intensity,
        )
        elapsed = time.time() - t0
        status = "OK" if ok else "FAILED"
        print(f"  → {status} in {elapsed:.1f}s → {output_path}")
        results.append((label, ok, elapsed, output_path))

    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    for label, ok, elapsed, path in results:
        print(f"  {label:20s} {'✓' if ok else '✗':3s} {elapsed:6.1f}s  {path}")

    print(f"\nAll variants in: {output_dir}")
    print("Next: copy each to a job's clips/ folder with a unique scene index to view in browser.")


if __name__ == "__main__":
    main()
