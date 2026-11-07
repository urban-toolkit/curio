"""This process's limit on open files, raised for Curio's servers, and how
many it holds.

A container's processes start at Docker's soft limit of 1024 open files, far
under their hard limit, and a terminal's on macOS at 256. A backend holds a
socket per open dataflow, its database pool and its streams, so the launcher
raises the soft limit toward ``WANTED`` before it starts the servers, which
inherit it. Isolated node runs set their own (``sandbox/isolation/child.py``).

:func:`in_use` is what the monitor samples every hour: the backend reads its
own, and the sandbox's ``/monitor`` reply carries the sandbox's
(``backend/app/monitor/open_files.py``).
"""

import os

#: The soft limit the launcher asks for, within the hard limit.
WANTED = 65536

#: What macOS may accept when it refuses more: a soft limit above its
#: ``kern.maxfilesperproc``, or above ``OPEN_MAX`` (10240) on older releases,
#: is refused.
_FALLBACKS = (24576, 10240)


def raise_limit(wanted=WANTED):
    """Raise the soft open-files limit toward *wanted*, never past the hard
    limit and never down. Returns the soft limit it leaves, or None where the
    platform has no such limit (Windows)."""
    try:
        import resource
    except ImportError:
        return None
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft == resource.RLIM_INFINITY:
        return soft
    target = wanted if hard == resource.RLIM_INFINITY else min(wanted, hard)
    for candidate in (target, *(value for value in _FALLBACKS if value < target)):
        if candidate <= soft:
            break
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (candidate, hard))
            break
        except (ValueError, OSError):
            continue
    return resource.getrlimit(resource.RLIMIT_NOFILE)[0]


def in_use():
    """This process's open files and its soft limit on them, as
    ``(count, limit)``: its files, sockets and pipes, each descriptor once.

    The count is None where the platform cannot list a process's descriptors
    (Windows), and the limit None where it has none (Windows) or it is
    unlimited. Never raises."""
    return _count(), _soft_limit()


def _count():
    try:
        import psutil

        return int(psutil.Process().num_fds())
    except Exception:  # noqa: BLE001 - no psutil, or a platform it cannot count on
        pass
    try:
        # Linux without psutil. The listing's own descriptor is among them, as
        # it is in psutil's count.
        return len(os.listdir("/proc/self/fd"))
    except OSError:
        return None


def _soft_limit():
    try:
        import resource

        soft = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    except Exception:  # noqa: BLE001 - no such limit here (Windows)
        return None
    if soft == resource.RLIM_INFINITY or soft < 0:
        return None
    return int(soft)
