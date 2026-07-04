import sys
sys.path.insert(0, '.')
from depth_renderer import estimate_depth, _build_camera_offsets, _reproject_frame, _fill_holes, _apply_motion_blur
import cv2, os

image_path = 'jobs/161dfaf7/images/scene_006.jpg'
image = cv2.imread(image_path)
image = cv2.resize(image, (1920, 1080), interpolation=cv2.INTER_LANCZOS4)

print("Estimating depth (one fal.ai call)...")
depth = estimate_depth(image_path)
if depth is None:
    print("DEPTH FAILED")
    sys.exit(1)
depth = cv2.resize(depth, (1920, 1080))
print("Depth OK, mean:", depth.mean())

offsets = _build_camera_offsets('subtle_rotate', 'natural_pace', 24)
print("Offset range dx:", min(o[0] for o in offsets), "to", max(o[0] for o in offsets))

os.makedirs('/tmp/manual_frames', exist_ok=True)
prev_dx, prev_dy = 0.0, 0.0
for i, (dx, dy, dz) in enumerate(offsets):
    warped, holes = _reproject_frame(image, depth, dx, dy, dz)
    filled = _fill_holes(warped, holes)
    frame_dx = dx - prev_dx
    frame_dy = dy - prev_dy
    blurred = _apply_motion_blur(filled, frame_dx, frame_dy, strength=0.8)
    prev_dx, prev_dy = dx, dy
    cv2.imwrite(f'/tmp/manual_frames/frame_{i:04d}.jpg', blurred, [cv2.IMWRITE_JPEG_QUALITY, 95])

print('Wrote', len(offsets), 'frames to /tmp/manual_frames/')
f0 = cv2.imread('/tmp/manual_frames/frame_0000.jpg')
f20 = cv2.imread('/tmp/manual_frames/frame_0020.jpg')
diff = cv2.absdiff(f0, f20)
print('Diff between saved frame 0 and frame 20 (from disk):', diff.max(), diff.mean())
