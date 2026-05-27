"""On-disk cache for fetched Street View imagery + segmentation overlays.

Two cache namespaces:
- ``images/``  raw JPEG panoramas downloaded from Google.
- ``overlays/`` segmentation overlay PNGs produced by the inference run.

Cache root defaults to ``$CURIO_LAUNCH_CWD/.curio/streetvision/cache/`` —
matches the convention used by every other piece of Curio runtime state
(per-user package store, SQLite DB, HF model cache). Override with the
``STREETVISION_CACHE_DIR`` env var.
"""

import os
from typing import Optional


def cache_root() -> str:
    """Return the resolved cache root, honoring ``STREETVISION_CACHE_DIR``."""
    override = os.environ.get("STREETVISION_CACHE_DIR")
    if override:
        return override
    launch_cwd = os.environ.get("CURIO_LAUNCH_CWD") or os.getcwd()
    return os.path.join(launch_cwd, ".curio", "streetvision", "cache")


def images_dir() -> str:
    path = os.path.join(cache_root(), "images")
    os.makedirs(path, exist_ok=True)
    return path


def overlays_dir() -> str:
    path = os.path.join(cache_root(), "overlays")
    os.makedirs(path, exist_ok=True)
    return path


def overlay_path(image_id: str) -> Optional[str]:
    """Return the on-disk path to an overlay PNG if it exists, else None."""
    stem = os.path.splitext(image_id)[0]
    path = os.path.join(overlays_dir(), f"{stem}_overlay.png")
    return path if os.path.exists(path) else None
