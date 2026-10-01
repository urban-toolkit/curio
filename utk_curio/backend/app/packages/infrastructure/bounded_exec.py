"""Start a bounded child without running Python between fork and exec.

``subprocess``'s ``preexec_fn`` runs in the forked child before exec, and that
child is a copy of a process with other threads. A lock one of them held at the
fork stays held in the child for good, so the child never reaches exec and the
parent waits on it forever. CI showed exactly that: an invocation that never
returned, whose child was still a copy of pytest parked on a futex.

So the child execs a fresh interpreter straight away, through subprocess's own C
fork/exec path. That interpreter has one thread. It sets the rlimits, drops to a
lesser account when asked and running as root, then execs the real command, so
the command still starts bounded.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence

#: Run as ``python -I -S -c _TRAMPOLINE <spec json> <argv...>``.
_TRAMPOLINE = r"""
import json, os, resource, sys
spec = json.loads(sys.argv[1])
for key, value in spec.get("rlimits", []):
    try:
        resource.setrlimit(key, (value, value))
    except (ValueError, OSError):
        pass
drop = spec.get("drop")
if drop and os.getuid() == 0:
    try:
        os.setgroups([])
        os.setgid(drop[1])
        os.setuid(drop[0])
    except OSError:
        pass
argv = sys.argv[2:]
try:
    os.execvp(argv[0], argv)
except OSError as exc:
    sys.stderr.write("cannot start %s: %s\n" % (argv[0], exc.strerror))
    os._exit(127)
"""

_PREFIX = ("-I", "-S", "-c", _TRAMPOLINE)


def bounded_argv(argv: Sequence[str], bounds: Mapping) -> list[str]:
    """*argv*, run under *bounds* once the child has exec'd.

    *bounds* holds ``rlimits``, a list of ``[resource.RLIMIT_*, value]`` set as
    both soft and hard limit, and optionally ``drop``, ``[uid, gid]`` to become
    when the child runs as root. Limits are set first: as root they can be
    raised as well as lowered, and after the drop only lowered.
    """
    spec = {"rlimits": [[int(key), int(value)] for key, value in bounds.get("rlimits", [])]}
    drop = bounds.get("drop")
    if drop is not None:
        spec["drop"] = [int(drop[0]), int(drop[1])]
    return [sys.executable, *_PREFIX, json.dumps(spec), *argv]


def bounds_of(argv: Sequence[str]) -> dict | None:
    """The bounds a :func:`bounded_argv` command carries, or ``None``."""
    argv = list(argv)
    if tuple(argv[1:5]) != _PREFIX or len(argv) < 7:
        return None
    return json.loads(argv[5])


def command_of(argv: Sequence[str]) -> list[str]:
    """The command a :func:`bounded_argv` command runs (*argv* itself otherwise)."""
    argv = list(argv)
    return argv[6:] if bounds_of(argv) is not None else argv
