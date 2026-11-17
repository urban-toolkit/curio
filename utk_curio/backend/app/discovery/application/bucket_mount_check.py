"""The bucket mount service's check as the backend starts.

When ``--bucket-mounts-dir`` and ``--bucket-mount-socket`` name a mount
service, the backend runs its self-test
(``infrastructure/bucket_mounts.py``) once, on a thread of its own
(:func:`start`, which ``server.py``'s ``serve()`` calls through the discovery
service, in the home process when it serves, as it starts the monitor's
sampler of open files), with the proxy ``serve()`` started just before in
this process, which the service must reach
(``bucket_mount_sources.process_proxy``). Its outcome is /monitor's
Deployment line (:func:`status`), and a failure is also one of the monitor's
Recent errors, with what went wrong (:func:`record`). After a passed
self-test, the same thread looks at the service's mounts of sources
(``bucket_mount_sources.reconcile_at_start``).

From then on the line follows the service: each later call to it says
whether it was answered (``bucket_mount_sources.py``). A call that finds it
gone makes the line unavailable (:func:`service_lost`); the next answer makes
it on again, and runs the self-test again when the self-test itself found no
service (:func:`service_answered`).

The self-test runs in the home process alone, while in a start of several
backend processes any of them may mount a source: so its outcome is also the
start's, in a document every process reads (:data:`SELF_TEST`), and a failed
self-test lets no process mount (:func:`failed_self_test`).

Apart from the self-test's module, which imports nothing from Curio so that
CI can load it by its path: this one holds the process's state and reports
to the monitor.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from utk_curio.backend.app.common import shared_budgets
from utk_curio.backend.app.discovery.infrastructure import bucket_mounts

log = logging.getLogger(__name__)

#: The self-test's problems that say only that the service did not answer.
_CHANNEL_PROBLEMS = ("no-service", "no-answer")

#: The start's document of the self-test's outcome, kept with its budgets in
#: ``.curio/budgets`` (``shared_budgets.State``), which node code cannot
#: reach, and begun anew at each start: in a start of several backend
#: processes, what every process reads of the self-test home ran
#: (:func:`failed_self_test`).
SELF_TEST = "bucket-mount-self-test"
#: Its one field: ``{passed, problem}``. Never the outcome's detail, which
#: holds paths and rclone's answers.
_OUTCOME = "outcome"

_LOCK = threading.Lock()
_outcome: Optional[bucket_mounts.SelfTest] = None
_thread: Optional[threading.Thread] = None
#: Set when a call after the self-test found the service gone: the problem,
#: one of :data:`_CHANNEL_PROBLEMS`, and what went wrong.
_lost: Optional[tuple[str, str]] = None
#: The start's outcome another process ran, ``(passed, problem)``, once read
#: and settled: passed, or failed for a reason a mount's calls cannot clear,
#: which no later self-test of the start changes.
_settled: Optional[tuple[bool, Optional[str]]] = None


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
    words of why it is unavailable (``bucket_mounts.PROBLEMS``), else None.
    A passed self-test reads unavailable while a later call found the
    service gone."""
    if bucket_mounts.configured() is None:
        return {"state": "none", "problem": None}
    with _LOCK:
        outcome, lost = _outcome, _lost
    if outcome is None:
        return {"state": "pending", "problem": None}
    if not outcome.passed:
        return {"state": "unavailable", "problem": _words(outcome.problem)}
    if lost is not None:
        return {"state": "unavailable",
                "problem": bucket_mounts.PROBLEMS.get(lost[0], bucket_mounts.PROBLEMS["error"])}
    return {"state": "passed", "problem": None}


def failed_self_test() -> Optional[str]:
    """Why no source may mount: a self-test that failed for a reason a
    mount's own calls cannot clear (FUSE, the profile, propagation, the read
    as node code's account, the way out to Curio's proxy, the self-test's own
    error), until the backend starts again. None when it passed, has not
    ended, or found no service, which a mount's calls find again.

    In a start of several backend processes the self-test runs in home
    alone, and every other process reads its outcome from the start's
    document (:data:`SELF_TEST`), so each refuses as home does."""
    with _LOCK:
        outcome = (_outcome.passed, _outcome.problem) if _outcome is not None else _settled
    if outcome is None and shared_budgets.across_processes():
        outcome = _the_starts_outcome()
    if outcome is None:
        return None
    passed, problem = outcome
    if passed or problem in _CHANNEL_PROBLEMS:
        return None
    return f"the mount service failed its self-test: {_words(problem)}"


def _the_starts_outcome() -> Optional[tuple[bool, Optional[str]]]:
    """The outcome of the self-test home ran, from the start's document, as
    ``(passed, problem)``; None while there is none, or when the document
    cannot be read (logged at debug: the start's list of the hosts let
    through cannot be written then either, which fails each mount for its
    reason). Kept in this process once settled."""
    global _settled
    try:
        with shared_budgets.State(SELF_TEST).held() as state:
            kept = state.get(_OUTCOME)
    except OSError as exc:
        log.debug("Bucket mounts: the self-test's outcome could not be read: %s", exc)
        return None
    if not (isinstance(kept, dict) and isinstance(kept.get("passed"), bool)
            and (kept.get("problem") is None or isinstance(kept.get("problem"), str))):
        return None
    outcome = (kept["passed"], kept["problem"])
    if outcome[0] or outcome[1] not in _CHANNEL_PROBLEMS:
        with _LOCK:
            _settled = outcome
    return outcome


def service_lost(problem: str, detail: str) -> None:
    """A call found the service gone (*problem*, ``no-service`` or
    ``no-answer``): the line says unavailable until a call is answered. The
    first call of such a run is one of the monitor's Recent errors."""
    global _lost
    with _LOCK:
        first = _lost is None
        _lost = (problem, detail)
    if not first:
        return
    words = bucket_mounts.PROBLEMS.get(problem, bucket_mounts.PROBLEMS["error"])
    log.warning("Bucket mounts are unavailable: %s. %s", words, detail)
    from utk_curio.backend.app.monitor import errors as monitor_errors

    monitor_errors.record("backend", summary=f"Bucket mounts are unavailable: {words}", detail=detail)


def service_answered() -> None:
    """A call got the service's answer: a loss is over, and a self-test that
    found no service runs again, on a thread of its own."""
    global _lost, _outcome, _thread
    with _LOCK:
        was_lost, _lost = _lost is not None, None
        again = (
            _outcome is not None and not _outcome.passed and _outcome.problem in _CHANNEL_PROBLEMS
            and (_thread is None or not _thread.is_alive())
        )
        if again:
            _outcome = None
            _thread = threading.Thread(target=_run, name="bucket-mounts-self-test", daemon=True)
            _thread.start()
    if was_lost:
        log.info("Bucket mounts: the mount service answers again")
    if again:
        log.info("Bucket mounts: the mount service answers, so its self-test runs again")


def record(outcome: bucket_mounts.SelfTest) -> None:
    """Keep *outcome* for :func:`status` and log it; a failure is also one of
    the monitor's Recent errors. In a start of several backend processes it
    is the start's too (:func:`_share`)."""
    global _outcome, _lost
    with _LOCK:
        _outcome = outcome
        if outcome.passed or outcome.problem not in _CHANNEL_PROBLEMS:
            # The service answered the self-test.
            _lost = None
    _share(outcome)
    if outcome.passed:
        log.info("Bucket mounts: the self-test passed: %s", outcome.detail)
        return
    words = _words(outcome.problem)
    log.warning("Bucket mounts are unavailable: %s. %s", words, outcome.detail)
    from utk_curio.backend.app.monitor import errors as monitor_errors

    monitor_errors.record("backend", summary=f"Bucket mounts are unavailable: {words}", detail=outcome.detail)


def _share(outcome: bucket_mounts.SelfTest) -> None:
    """In a start of several backend processes, *outcome* in the start's
    document, which every process reads (:func:`failed_self_test`): whether it
    passed, and its problem. A document that cannot be written is logged:
    then the start's list of the hosts let through cannot be written either,
    which fails each mount for its reason."""
    if not shared_budgets.across_processes():
        return
    try:
        with shared_budgets.State(SELF_TEST).held() as state:
            state[_OUTCOME] = {"passed": outcome.passed, "problem": outcome.problem}
    except OSError as exc:
        log.warning("Bucket mounts: the self-test's outcome could not be kept for the start's other processes: %s",
                    exc)


def reset() -> None:
    """Forget the outcome, the thread, a lost service and the start's outcome
    read. For tests only."""
    global _outcome, _thread, _lost, _settled
    with _LOCK:
        _outcome = None
        _thread = None
        _lost = None
        _settled = None


def _words(problem: Optional[str]) -> str:
    return bucket_mounts.PROBLEMS.get(problem or "", bucket_mounts.PROBLEMS["error"])


def _run() -> None:
    from utk_curio.backend.app.discovery.application import bucket_mount_sources

    try:
        outcome = bucket_mounts.self_test_from_env(proxy=bucket_mount_sources.process_proxy())
    except Exception as exc:  # noqa: BLE001 - the self-test never raises; a bug still reports
        outcome = bucket_mounts.SelfTest(False, "error", f"the self-test raised {type(exc).__name__}: {exc}")
    if outcome is None:
        outcome = bucket_mounts.SelfTest(
            False, "error", "the flags that name the mount service were unset as its self-test started",
        )
    record(outcome)
    if outcome.passed:
        # The service's mounts of sources: admitted again, or unmounted.
        bucket_mount_sources.reconcile_at_start()
