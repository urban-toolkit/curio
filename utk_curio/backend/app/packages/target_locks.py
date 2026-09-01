"""Per-(user, target) package locks — ONE serialization home (memo dev/92 B-1).

Promotion has always serialized per coordinate through this lock; dev/92
adds the second consumer: :mod:`backend_runtime`'s invocation READ phase
(manifest → pin verify → entry/tree reads into memory) takes the same lock,
so an invocation can never observe a mid-promote package state — the
installer's replace is ``rmtree`` **then** ``move`` (not atomic), and before
dev/92 a racing invocation could catch the dir absent (404) or new files
against the old pin (409 "reinstall" *during* the reinstall).

The lock ITSELF comes from :mod:`common.file_locks` (dev/93's shared
implementation — never a second keyed-lock dance); this module only owns
the namespace and the two-consumer contract. Thread-scope on purpose, like
promotion's original lock: cross-process promote races stay correct via the
base-digest check, and invocations fail loudly (never mixed) in that rare
case.

Hold discipline: promotes hold the lock for their whole install+pin
sequence (seconds); invocations hold it only while copying ≤64 files/8 MiB
into memory (microseconds) — sandbox workers always run OUTSIDE it.
"""

from __future__ import annotations

import threading

from utk_curio.backend.app.common.file_locks import keyed_thread_lock

_NAMESPACE = "package-target"


def target_lock(user_key: str, target: str) -> threading.Lock:
    """The process-wide lock for one (user, package-dir) coordinate."""
    return keyed_thread_lock(_NAMESPACE, f"{user_key}/{target}")
