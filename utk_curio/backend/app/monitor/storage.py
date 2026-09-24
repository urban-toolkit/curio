"""Disk usage across the state tree, as aggregates, from a cached walk.

Public route, so the same rule as ``stats.py`` applies: counts and
distributions, never a per-user row. The per-store sizes this module computes
are reduced to a histogram before they leave ``snapshot()``, and the directory
names they came from (which are user ids) never leave this module's locals.

DELIBERATELY NOT SHIPPING A SORTED SIZE VECTOR. A list like
``[640MB, 120MB, 11MB]`` is a per-user row with the label filed off: anyone who
can obtain any other ordering of the same users can line the two up. Buckets
give the chart everything it needs and carry no per-store identity. If a future
change "just needs the raw sizes for a better chart", it does not.

THE CACHE. A walk over a large state tree is the one expensive thing on this
page, and the page polls. The result is held for ``TTL_SECONDS`` and recomputed
under the lock, so a burst of pollers produces exactly one walk and the rest
wait for it rather than starting their own. With the frontend polling this
route every 60s, the walk runs at most once a minute no matter how many
browsers are open.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path

TTL_SECONDS = 60

# A public endpoint must not be turned into a denial of service by a
# pathological tree. Hitting this sets ``truncated`` rather than failing, so
# the page still reports what it managed to measure.
MAX_ENTRIES = 200_000

# Upper bounds for the store-size histogram, in bytes; the final None is the
# overflow bin. Fixed so the axis is stable between polls.
SIZE_BUCKETS = (1_048_576, 10_485_760, 104_857_600, 1_073_741_824,
                10_737_418_240, None)

# The only four area names that can appear in the payload.
AREAS = ("users", "data", "exec-overlays", "exec-scratch")

_LOCK = threading.Lock()
_cache: dict = {"value": None, "at": 0.0}


def snapshot() -> dict:
    """The cached walk, recomputing it when stale."""
    now = time.monotonic()
    with _LOCK:
        cached = _cache.get("value")
        age = now - _cache.get("at", 0.0)
        if cached is not None and age < TTL_SECONDS:
            return _with_age(cached, age)

        value = _walk_everything()
        _cache["value"] = value
        _cache["at"] = time.monotonic()
        return _with_age(value, 0.0)


def reset() -> None:
    """Drop the cache. For tests only."""
    with _LOCK:
        _cache["value"] = None
        _cache["at"] = 0.0


def _with_age(value: dict, age: float) -> dict:
    out = dict(value)
    out["ageSeconds"] = int(age)
    out["ttlSeconds"] = TTL_SECONDS
    return out


def _roots() -> dict:
    """Where each area lives, resolved the way the rest of the tree resolves it.

    Never hardcodes ``.curio``: ``CURIO_STATE_DIR`` relocates the whole tree and
    ``CURIO_SHARED_DATA`` relocates the data root independently of it, so
    ``curio_root() / "data"`` would measure the wrong directory on any instance
    that moved one and not the other.
    """
    from utk_curio.backend.app.common import user_storage
    from utk_curio.sandbox.isolation import supervisor

    root = user_storage.curio_root()
    shared_data = os.environ.get("CURIO_SHARED_DATA") or str(root / "data")
    return {
        "users": root / "users",
        "data": Path(shared_data),
        "exec-overlays": root / "exec-overlays",
        "exec-scratch": Path(supervisor.scratch_root(shared_data)),
    }


def _walk_everything() -> dict:
    started = time.perf_counter()
    budget = [MAX_ENTRIES]
    truncated = False
    breakdown = []

    roots = _roots()
    for area in AREAS:
        total, files, hit_cap = _measure(roots[area], budget)
        truncated = truncated or hit_cap
        breakdown.append({"area": area, "bytes": total, "files": files})

    store_sizes, stores_capped = _user_store_sizes(roots["users"], budget)
    truncated = truncated or stores_capped

    return {
        "computedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "walkMs": int((time.perf_counter() - started) * 1000),
        "truncated": truncated,
        "userStores": _summarise_stores(store_sizes),
        "breakdown": breakdown,
        "disk": _disk(roots["users"]),
    }


def _measure(path: Path, budget: list) -> tuple:
    """(bytes, files, hit_cap) for one tree. An unreadable dir is skipped."""
    total = 0
    files = 0
    hit_cap = False
    stack = [str(path)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if budget[0] <= 0:
                        return total, files, True
                    budget[0] -= 1
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            # follow_symlinks=False so a link into a shared
                            # tree is not counted as a copy of it.
                            total += entry.stat(follow_symlinks=False).st_size
                            files += 1
                    except OSError:
                        continue
        except (OSError, ValueError):
            # A missing area is normal (no exec-overlays without isolation) and
            # an unreadable one must not fail the response.
            continue
    return total, files, hit_cap


def _user_store_sizes(users_root: Path, budget: list) -> tuple:
    """One size per store directory. The NAMES stay in this function."""
    sizes = []
    truncated = False
    try:
        with os.scandir(str(users_root)) as entries:
            for entry in entries:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                total, _files, hit_cap = _measure(Path(entry.path), budget)
                truncated = truncated or hit_cap
                sizes.append(total)
    except (OSError, ValueError):
        return [], truncated
    return sizes, truncated


def _summarise_stores(sizes: list) -> dict:
    ordered = sorted(sizes)
    buckets = []
    for index, bound in enumerate(SIZE_BUCKETS):
        lower = SIZE_BUCKETS[index - 1] if index else 0
        if bound is None:
            count = sum(1 for size in ordered if size > SIZE_BUCKETS[-2])
        else:
            count = sum(1 for size in ordered if lower < size <= bound)
        buckets.append({"leBytes": bound, "count": count})
    return {
        "count": len(ordered),
        "totalBytes": sum(ordered),
        "largestBytes": ordered[-1] if ordered else 0,
        "medianBytes": ordered[len(ordered) // 2] if ordered else 0,
        "buckets": buckets,
    }


def _disk(path: Path) -> dict:
    try:
        usage = shutil.disk_usage(str(path if path.exists() else path.parent))
        return {"totalBytes": int(usage.total), "freeBytes": int(usage.free)}
    except Exception:  # noqa: BLE001
        return {"totalBytes": None, "freeBytes": None}
