"""Split a test suite into balanced parts, one per CI runner.

Both the e2e suite (``test_frontend/runner_split.py``, ``CURIO_E2E_PART``) and
the backend unit suite (``conftest.py``, ``CURIO_UNIT_PART``) are cut into
``k/n`` parts that run on separate ubuntu-latest jobs. A group -- whatever must
stay together on one runner, a test file at the least -- goes to exactly one
part, longest first onto the least-loaded part, priced by a recorded durations
file. A group missing from that file is priced at a default, so a stale file
only costs balance, never a test.
"""

from __future__ import annotations

import json
from pathlib import Path

#: A group whose duration is unknown (new since the file was recorded).
DEFAULT_GROUP_SECONDS = 30.0


def parse_part(value: str, name: str = "part") -> tuple[int, int]:
    """``"k/n"`` -> (k-1, n): 1-based on the outside, 0-based inside."""
    try:
        k, n = (int(piece) for piece in value.split("/", 1))
    except ValueError:
        raise ValueError(f"{name} must be k/n, got {value!r}") from None
    if not 1 <= k <= n:
        raise ValueError(f"{name} {value!r}: k must be between 1 and n")
    return k - 1, n


def load_durations(path: Path) -> dict:
    """Seconds per group, or nothing when the file is missing or unreadable."""
    try:
        return {str(k): float(v) for k, v in json.loads(Path(path).read_text()).items()}
    except (OSError, ValueError):
        return {}


def assign(groups, parts: int, durations: dict,
           default: float = DEFAULT_GROUP_SECONDS) -> dict:
    """Longest-first onto the least-loaded part. Deterministic for a given input."""
    load = [0.0] * parts
    placed = {}
    ordered = sorted(set(groups), key=lambda g: (-durations.get(g, default), g))
    for group in ordered:
        target = min(range(parts), key=lambda i: (load[i], i))
        placed[group] = target
        load[target] += durations.get(group, default)
    return placed


def keep_part(items, value: str, group_of, durations: dict, name: str = "part"):
    """Split ``items`` into (this part's items, the rest) for ``value`` = ``k/n``."""
    index, count = parse_part(value, name)
    placed = assign([group_of(item) for item in items], count, durations)
    kept = [item for item in items if placed[group_of(item)] == index]
    dropped = [item for item in items if placed[group_of(item)] != index]
    return kept, dropped
