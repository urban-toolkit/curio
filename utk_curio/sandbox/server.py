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
    # Reuse the backend's exclude list and default **stat** reloader so
    # Watchdog's pathlib-based ignores cannot miss deep ``.curio/`` paths
    # (same ``ERR_EMPTY_RESPONSE`` mid-install failure as the backend).
    # The leaf module, not backend.server: importing that builds the backend
    # app and hits its database (see utk_curio/backend/reloader.py).
    from utk_curio.backend.reloader import (
        DEFAULT_RELOADER_TYPE,
        RELOADER_EXCLUDE_PATTERNS,
    )

    # Fail closed: a multi-user instance must not come up with the code
    # execution routes unguarded. Checked here rather than at import time so
    # the unit suites can still build the app with app.test_client().
    from utk_curio.sandbox.app.auth import require_startup_token
    require_startup_token()

    # Same idea for execution isolation: resolve it now so a hosted instance
    # that asked for --isolation=fork and cannot have it dies here, with a
    # readable message, instead of quietly serving every node in-process. A
    # local launch degrades and warns instead (see isolation/mode.py).
    from utk_curio.sandbox.isolation import mode as _isolation_mode
    _resolved_isolation, _isolation_reason = _isolation_mode.resolve_from_environment()
    _isolation_mode.warn_once(_isolation_reason)
    print(
        f"[sandbox] node execution isolation: {_resolved_isolation}",
        file=sys.stderr, flush=True,
    )

    if _resolved_isolation == _isolation_mode.FORK:
        # Confining syscalls does not stop open(). A world-readable artifact
        # store or user database is readable by node code with no escape at
        # all, so tighten the permissions and then verify. Done at boot rather
        # than per request: a misconfiguration must fail the start, because
        # raising from a request handler would surface as a 500 and /exec
        # promises to report failures as stderr at 200.
        from utk_curio.sandbox.isolation import hardening as _hardening
        from utk_curio.sandbox.isolation import runner as _runner
        from utk_curio.sandbox.util.parsers import _shared_data_dir

        _config = _runner.IsolationConfig.from_environment()
        _findings, _fatal = _hardening.apply_and_report(
            os.environ.get('CURIO_LAUNCH_CWD', os.getcwd()),
            str(_shared_data_dir()),
            uid=_config.exec_uid,
            gid=None,
            hosted=_isolation_mode.mode_from_environment()[1],
        )
        for _finding in _findings:
            print(f"[isolation] {_finding}", file=sys.stderr, flush=True)
        if _fatal:
            raise SystemExit(
                "[isolation] refusing to start: this instance has user auth "
                "enabled and asked for isolated execution, but the paths listed "
                "above are still reachable by the execution user. Configure "
                "--exec-user with an unprivileged account, or pass "
                "--isolation=off to accept the risk explicitly."
            )

    app.run(
        host=os.getenv('FLASK_SANDBOX_HOST', '127.0.0.1'),
        port=int(os.getenv('FLASK_SANDBOX_PORT', 2000)),
        threaded=True,
        debug=False,
        use_reloader=os.getenv('FLASK_USE_RELOADER', '1') != '0',
        exclude_patterns=RELOADER_EXCLUDE_PATTERNS,
        reloader_type=DEFAULT_RELOADER_TYPE,
    )

