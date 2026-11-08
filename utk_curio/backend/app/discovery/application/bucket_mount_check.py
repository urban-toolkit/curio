"""The bucket mount service's check as the backend starts.

When ``--bucket-mounts-dir`` and ``--bucket-mount-socket`` name a mount
service, the backend runs its self-test
(``infrastructure/bucket_mounts.py``) once, on a thread of its own
(:func:`start`, which ``server.py``'s ``serve()`` calls through the discovery
service, in the process that serves, as it starts the monitor's sampler of
open files). Its outcome is /monitor's Deployment line (:func:`status`), and
a failure is also one of the monitor's Recent errors, with what went wrong
(:func:`record`).

Apart from the self-test's module, which imports nothing from Curio so that
CI can load it by its path: this one holds the process's state and reports
to the monitor.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from utk_curio.backend.app.discovery.infrastructure import bucket_mounts

log = logging.getLogger(__name__)

_LOCK = threading.Lock()
_outcome: Optional[bucket_mounts.SelfTest] = None
_thread: Optional[threading.Thread] = None


def start() -> bool:
    """Run the self-test once, on a thread of its own, when the flags name a
    service. False when they name none."""
    global _thread
    if bucket_mounts.configured() is None:
        return False
    with _LOCK:
        if _thread is None:
            _thread = threading.Thread(target=_run, name="bucket-mounts-self-test", daemon=True)
            _thread.start()
    return True


def status() -> dict:
    """/monitor's Deployment line: ``state``, which is ``none`` (no service
    named), ``pending``, ``passed`` or ``unavailable``, and ``problem``, the
    words of why it is unavailable (``bucket_mounts.PROBLEMS``), else None."""
    if bucket_mounts.configured() is None:
        return {"state": "none", "problem": None}
    with _LOCK:
        outcome = _outcome
    if outcome is None:
        return {"state": "pending", "problem": None}
    if outcome.passed:
        return {"state": "passed", "problem": None}
    return {"state": "unavailable", "problem": _words(outcome)}


def record(outcome: bucket_mounts.SelfTest) -> None:
    """Keep *outcome* for :func:`status` and log it; a failure is also one of
    the monitor's Recent errors."""
    global _outcome
    with _LOCK:
        _outcome = outcome
    if outcome.passed:
        log.info("Bucket mounts: the self-test passed: %s", outcome.detail)
        return
    words = _words(outcome)
    log.warning("Bucket mounts are unavailable: %s. %s", words, outcome.detail)
    from utk_curio.backend.app.monitor import errors as monitor_errors

    monitor_errors.record("backend", summary=f"Bucket mounts are unavailable: {words}", detail=outcome.detail)


def reset() -> None:
    """Forget the outcome and the thread. For tests only."""
    global _outcome, _thread
    with _LOCK:
        _outcome = None
        _thread = None


def _words(outcome: bucket_mounts.SelfTest) -> str:
    return bucket_mounts.PROBLEMS.get(outcome.problem or "", bucket_mounts.PROBLEMS["error"])


def _run() -> None:
    try:
        outcome = bucket_mounts.self_test_from_env()
    except Exception as exc:  # noqa: BLE001 - the self-test never raises; a bug still reports
        outcome = bucket_mounts.SelfTest(False, "error", f"the self-test raised {type(exc).__name__}: {exc}")
    if outcome is None:
        outcome = bucket_mounts.SelfTest(
            False, "error", "the flags that name the mount service were unset as its self-test started",
        )
    record(outcome)
