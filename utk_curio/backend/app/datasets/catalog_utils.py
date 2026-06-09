"""Small helpers for catalog IDs and timestamps."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone


def iso_from_timestamp(ts: float | None = None) -> str:
    dt = datetime.fromtimestamp(ts, timezone.utc) if ts is not None else datetime.now(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def stable_id(prefix: str, raw: str) -> str:
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]
    return f"{prefix}-{digest}"


def catalog_id_from_title(title: str) -> str:
    """Generate a local catalog dataset id from a human title.

    Returns a string like ``local.data.<slug>`` that satisfies the
    ``<datasetId>@<major>`` directory-name regex when combined with ``@1``.

    Each dot-segment in a valid dataset ID must start with a letter ``[a-z]``.
    A numeric-leading slug (e.g. from a timestamp-based filename) is prefixed
    with ``d`` so the generated ID always passes the storage regex.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "dataset"
    if slug and not slug[0].isalpha():
        slug = f"d{slug}"
    return f"local.data.{slug}"
