"""Small filesystem helpers (importable without the web framework, so they can be unit-tested)."""
import os
import shutil
from pathlib import Path


def replace_dir_atomic(new_dir, target) -> None:
    """Replaces `target` with `new_dir` without ever leaving the job without its files.

    The previous content is kept as `<target>.prev` (one generation) so a bad swap can be undone by hand.
    If the final rename fails the previous content is put back and the error is re-raised.
    Added 2026-10-12 after /jobs/{id}/draft/resync wiped a job's photos when a later validation failed.
    """
    new_dir, target = Path(new_dir), Path(target)
    prev = target.with_name(target.name + ".prev")
    if prev.exists():
        shutil.rmtree(str(prev))
    had_old = target.exists()
    if had_old:
        os.rename(str(target), str(prev))
    try:
        os.rename(str(new_dir), str(target))
    except Exception:
        if had_old:
            os.rename(str(prev), str(target))
        raise
