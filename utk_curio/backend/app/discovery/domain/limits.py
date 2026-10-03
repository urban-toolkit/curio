"""The Discovery Catalog's download ceiling.

Set with ``curio.py --discovery-max-download-mb``, which the launcher passes to
the backend as ``CURIO_DISCOVERY_MAX_DOWNLOAD_MB``. A portal download, a Direct
URL file and a file added from a bucket are each refused past it; a manifest
may lower it for its own source, never raise it.
"""

from __future__ import annotations

import os

ENV_MAX_DOWNLOAD_MB = "CURIO_DISCOVERY_MAX_DOWNLOAD_MB"

#: The ceiling when the flag is not given: 1 GiB.
DEFAULT_MAX_DOWNLOAD_MB = 1024


def max_download_bytes() -> int:
    """The ceiling, in bytes. A value that is not a positive whole number of
    megabytes is the default."""
    raw = os.environ.get(ENV_MAX_DOWNLOAD_MB, "").strip()
    try:
        megabytes = int(raw) if raw else DEFAULT_MAX_DOWNLOAD_MB
    except ValueError:
        megabytes = DEFAULT_MAX_DOWNLOAD_MB
    if megabytes <= 0:
        megabytes = DEFAULT_MAX_DOWNLOAD_MB
    return megabytes * 1024 * 1024


__all__ = ["ENV_MAX_DOWNLOAD_MB", "DEFAULT_MAX_DOWNLOAD_MB", "max_download_bytes"]
