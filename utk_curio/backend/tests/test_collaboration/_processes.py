"""This test process as one of several backend processes, and the dataflows
each of them owns (``collaboration/owner_guard.py``).

The launcher starts each backend with its number and how many there are
(``common/backend_processes.py``); a test sets the same variables.
"""

from __future__ import annotations

import uuid

#: How many backend processes the tests' start runs.
PROCESSES = 2


def as_process(monkeypatch, number: int, processes: int = PROCESSES) -> None:
    """This process, as the launcher starts the backend numbered *number* of
    *processes*."""
    monkeypatch.setenv("CURIO_BACKEND_PROCESS", str(number))
    monkeypatch.setenv("CURIO_BACKEND_PROCESSES", str(processes))


def as_the_one_process(monkeypatch) -> None:
    """This process, as a start of one backend, every install's today."""
    monkeypatch.delenv("CURIO_BACKEND_PROCESS", raising=False)
    monkeypatch.delenv("CURIO_BACKEND_PROCESSES", raising=False)


def owner_of(dataflow_id: str, processes: int = PROCESSES) -> int:
    """The process the dataflow *dataflow_id* belongs to, by its id."""
    from utk_curio.common.backend_processes import shard_of

    return shard_of(dataflow_id, processes)


def owned_by(number: int, processes: int = PROCESSES) -> str:
    """A new dataflow id that belongs to the process numbered *number*."""
    while True:
        candidate = str(uuid.uuid4())
        if owner_of(candidate, processes) == number:
            return candidate


def assert_names_the_owner(text: str, dataflow_id: str, owner: int, here: int,
                           processes: int = PROCESSES) -> None:
    """*text*, a refusal, names the dataflow, the process that owns it and
    this one."""
    assert dataflow_id in text, f"the refusal does not name dataflow {dataflow_id}: {text!r}"
    assert f"belongs to backend process {owner}" in text, f"the refusal does not name its owner: {text!r}"
    assert f"process {here} of {processes}" in text, f"the refusal does not name this process: {text!r}"
