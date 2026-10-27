"""Objective sharpness of video files (2026-10-27): variance of the Laplacian of 3 frames (20%, 50%, 80% of the clip), each resized to 1280 px
wide so clips of different resolution are comparable. Higher = sharper. Only reads files; use it to compare an experiment clip with a normal one.
  python3 sharp_compare.py file1.mp4 [file2.mp4 ...]"""
import sys


def frame_sharpness(path: str):
    import cv2
    cap = cv2.VideoCapture(path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    vals = []
    for frac in (0.2, 0.5, 0.8):
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(n * frac)))
        ok, fr = cap.read()
        if not ok:
            continue
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        g = cv2.resize(g, (1280, max(1, round(g.shape[0] * 1280 / g.shape[1]))), interpolation=cv2.INTER_AREA)
        vals.append(float(cv2.Laplacian(g, cv2.CV_64F).var()))
    cap.release()
    return {"size": f"{w}x{h}", "frames": n, "sharpness": round(sum(vals) / len(vals), 1) if vals else None}


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(p.split("/")[-1][:60], frame_sharpness(p))
