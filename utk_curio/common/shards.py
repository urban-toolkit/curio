"""Which backend process owns a dataflow (tmp/sharded-backend prototype).

With ``curio.py start --backend-processes N`` the launcher starts N backends,
process 0 (home) first, each with ``CURIO_SHARD`` (its number), ``CURIO_SHARDS``
(N), ``CURIO_SHARD_PORTS`` (every process's internal port, by number) and one
shared ``CURIO_BOOT_ID``, then nginx in front of them. nginx's map from a
dataflow id to a process is written from :func:`shard_of`, which the backend's
owner guard uses too, so the router and the guard agree by construction.
Without those variables every process is home and owns every dataflow. A
process reads them once, when this module is first imported.
"""

from __future__ import annotations

import os
import re

#: The route key's first two hex digits, which pick the process.
_LEAD = re.compile(r"^([0-9a-fA-F]{2})")


def shard_of(dataflow_id, shards: int) -> int:
    """The process that owns *dataflow_id* among *shards*: its id's first two
    hex digits modulo *shards*. Anything else is home's (0)."""
    if shards <= 1:
        return 0
    match = _LEAD.match(str(dataflow_id or ""))
    return int(match.group(1), 16) % shards if match else 0


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


_THIS = _int_env("CURIO_SHARD", 0)
_COUNT = max(1, _int_env("CURIO_SHARDS", 1))


def this_shard() -> int:
    """This process's number; 0, home, when the launcher named none."""
    return _THIS


def shard_count() -> int:
    """How many backend processes share the dataflows."""
    return _COUNT


def sharded() -> bool:
    """Whether more than one backend process shares the dataflows."""
    return _COUNT > 1


def is_home() -> bool:
    """Whether this process does the startup work, the timers and the
    monitor: the only one with one process, process 0 with several."""
    return _THIS == 0


def owner_of(dataflow_id) -> int:
    """The process that owns *dataflow_id* in this start."""
    return shard_of(dataflow_id, _COUNT)


def shard_ports() -> list[int]:
    """Every process's internal port, by number (``CURIO_SHARD_PORTS``)."""
    ports = []
    for part in (os.environ.get("CURIO_SHARD_PORTS") or "").split(","):
        part = part.strip()
        if part.isdigit():
            ports.append(int(part))
    return ports
