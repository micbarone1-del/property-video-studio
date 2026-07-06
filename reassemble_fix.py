import sys, json
sys.path.insert(0, '/var/www/property-video-studio')
import os
os.chdir('/var/www/property-video-studio')
from pathlib import Path

JOB_ID = "161dfaf7_rw9f6a"
job_dir = Path("jobs") / JOB_ID

with open(job_dir / "job_meta.json") as f:
    job = json.load(f)

scenes_config = job.get("scenes_config", [])
property_name = job.get("property_name", "Property")

clip_paths = sorted((job_dir / "clips").glob("scene_*.mp4"))
print(f"Clips found: {len(clip_paths)}")
for c in clip_paths:
    print(f"  {c.name}  ({c.stat().st_size/1024/1024:.1f} MB)")

audio_paths = []
for cp in clip_paths:
    ap = job_dir / "audio" / cp.name.replace(".mp4", ".mp3")
    audio_paths.append(str(ap) if ap.exists() else None)
    print(f"  audio for {cp.name}: {'found' if ap.exists() else 'MISSING'}")

output_path = str(job_dir / f"{property_name.replace(' ','_')}_rework.mp4")

from video_assembly import assemble_property_video
print(f"\nReassembling -> {output_path}")
ok = assemble_property_video(
    scenes_config=scenes_config,
    video_clip_paths=[str(p) for p in clip_paths],
    audio_paths=audio_paths,
    image_paths=[str(p) for p in clip_paths],
    output_path=output_path,
    property_name=property_name,
    transition_style=job.get("transition_style", "fade"),
)

if ok:
    print(f"\n✓ REASSEMBLY SUCCEEDED: {output_path}")
    job["output_path"] = output_path
    job["status"] = "done"
    with open(job_dir / "job_meta.json", "w") as f:
        json.dump(job, f)
    print("Job meta updated.")
else:
    print("\n✗ REASSEMBLY FAILED — check error above")
