"""Which backend process this is, the start's boot id, and the process a
dataflow belongs to.

``curio.py start`` may run several backend processes, and runs one today. It
starts each with three environment variables, which only the launcher sets
(:func:`environment`):

- ``CURIO_BACKEND_PROCESS``: this process's number, from 0;
- ``CURIO_BACKEND_PROCESSES``: how many backend processes the start runs;
- ``CURIO_BOOT_ID``: the start's boot id, one for every backend it starts.

A backend started without them, by hand or by a test, is process 0 of 1 and
makes its own boot id.

Process 0 is the home process. It alone does the startup work: the shared
guest, the hosted guests' copies dropped, the agents and the examples put
back, the monitor's histories started anew, the guest cleanup and the kept
outputs' sweep, the open-files sampler, and the bucket mount service's proxy
and check (``backend/server.py`` and ``create_app``). A launcher that starts
several backends starts home first and the others once it serves, so that
work is done before they serve.

The boot id names a start. A run left queued or running under another one was
cut off by a restart, and a backend's start or any run read marks it
interrupted (``runs/service.py``); the backends of one start share theirs, so
none marks another's live runs. A backend Werkzeug's reloader started makes
its own, since the reloader starts it again after each code change with the
same environment, and each of those is a restart the launcher never sees. A
start of several backends runs them without the reloader, under which each
would make its own.

The functions read ``os.environ`` when called, or the mapping they are given.
"""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Mapping

#: This process's number among the start's backends, from 0.
PROCESS_VARIABLE = "CURIO_BACKEND_PROCESS"
#: How many backend processes the start runs.
PROCESSES_VARIABLE = "CURIO_BACKEND_PROCESSES"
#: The start's boot id.
BOOT_ID_VARIABLE = "CURIO_BOOT_ID"

#: The home process's number.
HOME = 0

#: A dataflow id's first two hex digits, which name its process.
_LEAD = re.compile(r"[0-9a-fA-F]{2}")


def _environ(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def _whole_number(environ: Mapping[str, str], name: str, default: int) -> int:
    text = (environ.get(name) or "").strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        raise ValueError(f"{name} is {text!r}, not a whole number; only the launcher sets it") from None


def process_count(environ: Mapping[str, str] | None = None) -> int:
    """How many backend processes this start runs: 1 when the launcher named none."""
    environ = _environ(environ)
    count = _whole_number(environ, PROCESSES_VARIABLE, 1)
    if count < 1:
        raise ValueError(f"{PROCESSES_VARIABLE} is {count}; a start runs at least one backend")
    return count


def this_process(environ: Mapping[str, str] | None = None) -> int:
    """This process's number, from 0: :data:`HOME` when the launcher named none."""
    environ = _environ(environ)
    count = process_count(environ)
    number = _whole_number(environ, PROCESS_VARIABLE, HOME)
    if not 0 <= number < count:
        raise ValueError(f"{PROCESS_VARIABLE} is {number}, not one of the {count} backend process(es)")
    return number


def is_home(environ: Mapping[str, str] | None = None) -> bool:
    """Whether this is the home process, which does the startup work."""
    return this_process(environ) == HOME


def boot_id(environ: Mapping[str, str] | None = None) -> str:
    """This process's boot id: the one the launcher gave every backend of its
    start, or one made now when it gave none or Werkzeug's reloader started
    this process. Each call without one makes another: ``runs/jobs.BOOT_ID``
    asks once, at import, and holds this process's."""
    environ = _environ(environ)
    given = (environ.get(BOOT_ID_VARIABLE) or "").strip()
    if given and environ.get("WERKZEUG_RUN_MAIN") != "true":
        return given
    return str(uuid.uuid4())


def environment(*, process: int, processes: int, boot_id: str) -> dict[str, str]:
    """The variables the launcher adds to a backend's environment: it is
    *process* of *processes*, of the start whose boot id is *boot_id*."""
    given = {
        PROCESS_VARIABLE: str(process),
        PROCESSES_VARIABLE: str(processes),
        BOOT_ID_VARIABLE: str(boot_id or "").strip(),
    }
    this_process(given)
    if not given[BOOT_ID_VARIABLE]:
        raise ValueError("a start's backends need its boot id")
    return given


def shard_of(dataflow_id, processes: int) -> int:
    """The process the dataflow *dataflow_id* belongs to among *processes*:
    its id's first two hex digits, read as a number, modulo *processes*. An id
    that does not start with two hex digits, and every id when there is one
    process, belongs to the home process. What sends a dataflow's requests to
    a process and what checks that a process owns a dataflow both ask this."""
    if processes <= 1:
        return HOME
    lead = _LEAD.match(str(dataflow_id or ""))
    return int(lead.group(0), 16) % processes if lead else HOME
