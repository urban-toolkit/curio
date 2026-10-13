"""A run's place in the sandbox, and the reply that keeps its connection busy
until the run has one (#889).

The sandbox runs only so many nodes at once: one Python node without isolation
(``app/worker.py`` ``_exec_lock``), ``CURIO_EXEC_PARALLELISM`` isolated
children (``isolation/runner.py`` ``IsolationConfig.slot()``) and
``CURIO_JS_PARALLELISM`` Node processes (``worker._js_slot()``). A run that
finds its place taken waits for it in the sandbox. The backend reads a reply
with a read timeout on every gap between its bytes, the wait for the first one
included, so a reply that said nothing until the run ended counted the wait
against the node's timeout (#863, #889).

So ``/exec`` and ``/execJs`` answer at once and run the node on a thread of its
own (:func:`reply_when_run`). While the run waits for its place, the reply
sends a space every :data:`KEEPALIVE_SECONDS`. When the run takes its place
(:func:`took_place`, called where each queue lets a run through), it sends one
more, then nothing until the run ends, when the JSON follows. A JSON reader
skips the spaces, and the read timeout counts the run alone.

Only the standard library at import: the isolation runner imports this, and
must not build the sandbox's Flask app.
"""

import sys
import threading
import time
import traceback

#: How often a waiting run's reply sends a space. Well within the shortest read
#: timeout the backend gives a run (300 s, Solve's validation runs).
KEEPALIVE_SECONDS = 5

_this_run = threading.local()


def took_place():
    """Say that the run on this thread has its place in the sandbox.

    Called where each queue lets a run through. Only a run's first call
    counts: a run that queues again later (a Compare Scenarios node's Node
    slot after its Python run, the retry after a Node crash) is already
    running. Outside a reply, as in a direct call to the executors, it does
    nothing.
    """
    placed = getattr(_this_run, "placed", None)
    if placed is not None and not placed.is_set():
        _this_run.placed_at = time.perf_counter()
        placed.set()


def reply_when_run(run, serialize, *, route, node_type):
    """Start *run* on a thread of its own and return its reply, as bytes.

    *run* returns the route's result; *serialize* turns a result into the JSON
    bytes the route has always sent. The reply is a space at once, a space
    every :data:`KEEPALIVE_SECONDS` while the run waits for its place, one more
    when it takes it, then the JSON when the run ends.

    The run holds the shared DuckDB connection until it ends, as
    ``holds_duckdb`` does for a view (``util/db.connection_in_use``): the route
    returns before the run ends. An error the run raises comes back in the
    body, since the status went out with the first space. A reply nobody reads
    any more (the backend gave up on it) does not stop the run.
    """
    placed = threading.Event()
    ended = threading.Event()
    reply = {}
    started = time.perf_counter()

    def work():
        from utk_curio.sandbox.util.db import connection_in_use

        _this_run.placed = placed
        _this_run.placed_at = None
        try:
            try:
                with connection_in_use():
                    reply["body"] = serialize(run())
            except BaseException as exc:  # noqa: BLE001 - the status has gone out
                print(f"[sandbox {route}] failed  node={node_type}\n{traceback.format_exc()}",
                      file=sys.__stderr__, flush=True)
                reply["body"] = serialize(_failed(exc))
            finished = time.perf_counter()
            waited = (_this_run.placed_at or finished) - started
            print(f"[sandbox {route}] finished  total={finished - started:.3f}s"
                  f"  waited={waited:.3f}s  node={node_type}", file=sys.__stderr__, flush=True)
        finally:
            placed.set()
            ended.set()

    threading.Thread(target=work, name=f"run {route}", daemon=True).start()
    return _reply(placed, ended, reply)


def _reply(placed, ended, reply):
    yield b" "  # at once: the status and headers go out with it
    while not placed.wait(KEEPALIVE_SECONDS):
        yield b" "
    if not ended.is_set():
        yield b" "  # the run starts now: the read timeout counts from here
    ended.wait()
    if reply.get("body"):
        yield reply["body"]


def _failed(exc):
    """The reply to a run the sandbox itself failed. ``error`` names the
    failure for the backend; the node's usual fields say the same to any
    other reader."""
    name = type(exc).__name__
    return {
        "error": name,
        "message": str(exc),
        "stdout": [],
        "stderr": f"Sandbox error: {name}: {exc}",
        "output": {"path": "", "dataType": "str"},
    }
