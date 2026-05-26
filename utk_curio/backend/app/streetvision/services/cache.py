"""On-disk cache for fetched Street View imagery + segmentation overlays.

Two cache namespaces:
- ``images/``  raw JPEG panoramas downloaded from Google.
- ``overlays/`` segmentation overlay PNGs produced by the inference run.

Cache root defaults to ``<instance>/streetvision_cache/`` (where ``instance``
is Flask's app instance path — the same place Curio writes its other
ephemeral state). Override with the ``STREETVISION_CACHE_DIR`` env var.
"""

import os
from typing import Optional


def cache_root() -> str:
    """Return the resolved cache root, honoring ``STREETVISION_CACHE_DIR``."""
    override = os.environ.get("STREETVISION_CACHE_DIR")
    if override:
        return override
    # Match Curio's instance-folder convention. Falling back to ./cache keeps
    # us working in scratch test runs that don't set up Flask's instance path.
    instance = os.environ.get("CURIO_INSTANCE_PATH") or os.path.join(
        os.getcwd(), "instance"
    )
    return os.path.join(instance, "streetvision_cache")


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
