from utk_curio.sandbox.app import app
import atexit
import os
import signal
import sys

@app.route('/health', methods=['GET'])
def health():
    return 'OK', 200


def _kill_descendants() -> None:
    """Kill every process we (or Werkzeug's reloader) spawned before we exit.

    With ``use_reloader=True`` Werkzeug runs as a supervisor + worker pair.
    The supervisor watches for file changes and re-execs the worker; if the
    supervisor exits cleanly (atexit / catchable signal) we also need to take
    the worker down. Otherwise the worker keeps holding the DuckDB lock
    and subsequent ``curio start`` invocations fail with "file in use"
    until the orphan is killed manually.

    Also runs on the worker — there it's a no-op since the worker has no
    children of its own, but it costs nothing.
    """
    try:
        import psutil
    except ImportError:
        return
    try:
        me = psutil.Process()
    except psutil.NoSuchProcess:
        return
    children = me.children(recursive=True)
    if not children:
        return
    for child in children:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(children, timeout=2)


def _self_destruct_when_parent_dies() -> None:
    """Spawn a daemon thread that polls the parent PID and self-exits if it goes away.

    Catches the cases where ``_kill_descendants`` can't run in the supervisor:

    - **Windows ``TerminateProcess``** (what ``Popen.terminate()`` calls): no
      signal is delivered to the supervisor, so its atexit/signal handlers
      never fire — but the worker outlives it. Polling ``os.getppid()`` here
      catches that.
    - **POSIX ``SIGKILL``**: same story (uncatchable signal).
    - **OOM kill, host crash, ``kill -9``**: same story.

    Only runs on the worker process (where ``WERKZEUG_RUN_MAIN == 'true'``)
    so the supervisor doesn't kill itself when its own grandparent (the
    parent shell) exits.
    """
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        return  # we're the supervisor, not the worker

    try:
        import psutil
    except ImportError:
        return

    parent_pid = os.getppid()
    if parent_pid in (0, 1):
        return  # already orphaned; nothing useful to monitor

    import threading
    import time

    def _watch():
        while True:
            time.sleep(1)
            try:
                psutil.Process(parent_pid)
            except psutil.NoSuchProcess:
                # Supervisor died for *any* reason. Bail before we leak the
                # DuckDB lock to the next ``curio start``.
                os._exit(0)

    t = threading.Thread(target=_watch, daemon=True, name='parent-watchdog')
    t.start()


def _on_signal(signum, _frame):
    _kill_descendants()
    # Re-raise via the default handler so the OS records the right exit code.
    try:
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)
    except Exception:
        sys.exit(0)


# atexit fires on a normal interpreter exit (sys.exit, end of main, KeyboardInterrupt).
atexit.register(_kill_descendants)

# Worker-side: poll the supervisor and bail if it dies. Covers SIGKILL,
# Windows TerminateProcess, OOM, and other paths where atexit can't run.
_self_destruct_when_parent_dies()

# Signal handlers cover SIGTERM (Docker stop, systemd stop, ``kill <pid>``)
# and the Windows equivalents. Werkzeug's reloader installs its own SIGINT
# handler in the supervisor; ours registers at import time so it runs even
# if the reloader's setup hasn't yet replaced it.
for _sig_name in ('SIGINT', 'SIGTERM', 'SIGBREAK', 'SIGHUP'):
    _sig = getattr(signal, _sig_name, None)
    if _sig is None:
        continue
    try:
        signal.signal(_sig, _on_signal)
    except (ValueError, OSError):
        # ValueError: signal only valid in main thread.
        # OSError: signal not registerable on this platform (e.g. SIGHUP on Windows).
        pass


if __name__ == '__main__':
    app.run(
        host=os.getenv('FLASK_SANDBOX_HOST', '127.0.0.1'),
        port=int(os.getenv('FLASK_SANDBOX_PORT', 2000)),
        threaded=True,
        debug=False,
        use_reloader=os.getenv('FLASK_USE_RELOADER', '1') != '0',
        exclude_patterns=['*.duckdb', '*.duckdb.wal', '*.duckdb-shm', '*.duckdb-wal'],
    )

