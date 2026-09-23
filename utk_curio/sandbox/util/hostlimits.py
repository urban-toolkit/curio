"""What this process may actually spend: memory and PIDs, as the kernel sees it.

Both semaphores that bound concurrent node execution -- ``_default_parallelism``
for isolated Python children and ``_default_js_parallelism`` for Node
subprocesses -- are sized against a memory ceiling. They used to assume one
(a flat cap of 8 and 16) rather than look, which is wrong in both directions: it
promises 32GB of node memory on a 32GB VM, and it holds a 377GB host to the same
8 children.

Curio ships in a container, so the order here matters. ``SC_PHYS_PAGES`` reports
the *host's* memory from inside a container with ``mem_limit`` set, which is the
one answer that must never be used when a cgroup limit exists: it would size the
pool to memory this process cannot touch. cgroup first, sysconf only as the
fallback for a bare-metal run.

Deliberately not ``psutil.virtual_memory()``, which this repo already depends
on: it reads /proc/meminfo, which inside a container is still the host's, so it
answers a different question than the one being asked here. psutil is right for
the monitor page, which reports what the machine has; this is about what this
process may spend.

Every reader returns ``None`` rather than a guess when it cannot tell, and the
callers keep their previous constant in that case.
"""

import os

# cgroup v1 writes a sentinel near 2**63 for "no limit"; the exact value varies
# with the page size, so anything absurd is read as unlimited rather than as a
# ceiling of eight million terabytes.
_UNLIMITED_ABOVE_BYTES = 1 << 62

_CGROUP_V2_MEMORY = "/sys/fs/cgroup/memory.max"
_CGROUP_V1_MEMORY = "/sys/fs/cgroup/memory/limit_in_bytes"
_CGROUP_V2_PIDS = "/sys/fs/cgroup/pids.max"
_CGROUP_V1_PIDS = "/sys/fs/cgroup/pids/pids.max"


def _read_limit(path):
    """One cgroup limit file as an int, or None for absent/unlimited/garbage."""
    try:
        with open(path, encoding="utf-8") as handle:
            raw = handle.read().strip()
    except OSError:
        return None
    if raw == "max":  # cgroup v2's explicit "no limit"
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value <= 0 or value >= _UNLIMITED_ABOVE_BYTES:
        return None
    return value


def visible_memory_mb():
    """Memory this process may use, in MB, or None if it cannot be determined."""
    for path in (_CGROUP_V2_MEMORY, _CGROUP_V1_MEMORY):
        limit = _read_limit(path)
        if limit is not None:
            return limit // (1024 * 1024)
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):
        return None  # not Linux, or a platform without these names
    if pages <= 0 or page_size <= 0:
        return None
    return (pages * page_size) // (1024 * 1024)


def visible_pids_max():
    """The container's PID ceiling, or None when there is no cgroup limit.

    Unlike memory there is no host-level fallback worth having: the point of
    this number is the ``pids_limit`` a compose file sets, and a host with no
    limit is one where RLIMIT_NPROC is the only ceiling anyway.
    """
    for path in (_CGROUP_V2_PIDS, _CGROUP_V1_PIDS):
        limit = _read_limit(path)
        if limit is not None:
            return limit
    return None
