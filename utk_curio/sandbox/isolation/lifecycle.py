"""Starting, watching, and stopping the execution zygote.

NOT VERIFIED. Needs Linux; never executed.

The zygote is a child process of the sandbox, started lazily on the first
isolated execution rather than at import time. Lazy matters for two reasons:

- With isolation off (``CURIO_ISOLATION=off``, and the default for a local launch) nothing extra is ever spawned, so the
  in-process path carries none of this cost or risk.
- ``sandbox/app/api.py`` runs ``_worker_init()`` at import, and starting a
  second heavyweight process there would double sandbox startup for every
  launch, isolated or not.

It is started with ``subprocess``, not ``fork``, on purpose: see the note at
the top of ``zygote.py``. A fork of the Flask process would inherit its threads
and its DuckDB handle, which is exactly what this is meant to avoid.
"""

import os
import subprocess
import sys
import threading

_lock = threading.Lock()
_process = None
_socket_path = None

# The zygote imports geopandas/pandas/shapely/duckdb before it can serve, which
# is the cost being amortised. Generous, because a cold import on a loaded
# machine is slow and failing here fails the user's first node.
_READY_TIMEOUT_SECONDS = 180


#: What one glibc malloc arena reserves: HEAP_MAX_SIZE, twice the 32 MiB
#: ceiling of the mmap threshold on a 64-bit build.
MALLOC_ARENA_MB = 64

#: The share of a child's budget its malloc arenas may reserve between them.
MALLOC_ARENA_SHARE = 4


class ZygoteStartupError(RuntimeError):
    """The zygote could not be started or never became ready."""


def malloc_arena_cap(memory_mb):
    """How many malloc arenas a child with *memory_mb* of budget may hold."""
    return max(2, int(memory_mb) // MALLOC_ARENA_SHARE // MALLOC_ARENA_MB)


def zygote_environment(limits, environ=None):
    """The zygote's environment: this process's, with its malloc arenas capped.

    glibc gives every thread that mallocs an arena of its own, up to eight per
    core, and each one reserves ``MALLOC_ARENA_MB`` of address space up front.
    A child's RLIMIT_AS counts the reservation, not what is used, and a node's
    libraries start threads by the core: onnxruntime one per physical core. At
    64 threads, as on a 64-core host, its session could not even be created
    inside the default budget. With the cap, threads beyond it share the
    arenas there are; how many threads a library starts is unchanged.

    Set here, before the zygote's first allocation, because glibc settles its
    arena limit once per process and a forked child inherits what the zygote
    settled: a ``mallopt`` in the child comes too late. A lower
    ``MALLOC_ARENA_MAX`` already in the environment stands.
    """
    env = dict(os.environ if environ is None else environ)
    memory_mb = (limits or {}).get("memory_mb")
    if memory_mb:
        cap = malloc_arena_cap(memory_mb)
        try:
            current = int(env.get("MALLOC_ARENA_MAX", ""))
        except ValueError:
            current = 0
        env["MALLOC_ARENA_MAX"] = str(min(current, cap) if current > 0 else cap)
    return env


def ensure_running(config, *, exec_user=None, require_seccomp=True):
    """Start the zygote if it is not already up. Returns the socket path.

    Idempotent and safe to call from several request threads at once: the lock
    means only the first caller spawns, and a process that has since died is
    replaced rather than reused.
    """
    global _process, _socket_path

    with _lock:
        if _process is not None and _process.poll() is None:
            return _socket_path

        if _process is not None:
            # Died since last time. Say so; the next launch is a fresh start,
            # not a silent retry.
            print(
                f"[isolation] the execution zygote exited with "
                f"{_process.returncode}; restarting it",
                file=sys.stderr, flush=True,
            )

        socket_path = config.socket_path
        os.makedirs(os.path.dirname(socket_path), exist_ok=True)

        command = [
            sys.executable, "-u", "-m", "utk_curio.sandbox.isolation.zygote",
            "--socket", socket_path,
        ]
        if exec_user:
            command += ["--exec-user", exec_user]
        if require_seccomp:
            command.append("--require-seccomp")

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=None,          # inherit, so its errors reach the log
                text=True,
                env=zygote_environment(config.limits),
                # Its own process group, so a signal aimed at the sandbox's
                # group does not race the zygote's own children.
                start_new_session=True,
            )
        except OSError as exc:
            raise ZygoteStartupError(f"could not spawn the execution zygote: {exc}")

        _wait_for_ready(process, socket_path)

        _process = process
        _socket_path = socket_path
        return socket_path


def _wait_for_ready(process, socket_path):
    """Block until the zygote prints ZYGOTE_READY, or fail loudly.

    Reading a line is better than polling for the socket file: the socket
    exists before the imports finish, so a connect could succeed against a
    zygote that cannot yet serve.
    """
    import selectors

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    remaining = _READY_TIMEOUT_SECONDS

    while remaining > 0:
        if process.poll() is not None:
            raise ZygoteStartupError(
                f"the execution zygote exited with {process.returncode} before "
                "becoming ready; check the sandbox log for its traceback"
            )
        events = selector.select(timeout=min(5.0, remaining))
        remaining -= 5.0
        if not events:
            continue
        line = process.stdout.readline()
        if not line:
            continue
        if line.strip() == "ZYGOTE_READY":
            _drain_in_background(process)
            return
        # Anything else it printed is diagnostic; pass it through.
        print(f"[zygote] {line.rstrip()}", file=sys.stderr, flush=True)

    _terminate(process)
    raise ZygoteStartupError(
        f"the execution zygote did not become ready within "
        f"{_READY_TIMEOUT_SECONDS}s"
    )


def _drain_in_background(process):
    """Keep reading the zygote's stdout so its pipe never fills.

    A full pipe would block the zygote inside a print and wedge every
    execution, which is a miserable failure to diagnose.
    """

    def _drain():
        try:
            for line in process.stdout:
                print(f"[zygote] {line.rstrip()}", file=sys.stderr, flush=True)
        except Exception:
            pass

    thread = threading.Thread(target=_drain, name="zygote-stdout", daemon=True)
    thread.start()


def _terminate(process):
    try:
        process.terminate()
        process.wait(timeout=5)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def shutdown():
    """Stop the zygote. Registered with atexit by the sandbox."""
    global _process
    with _lock:
        if _process is None:
            return
        _terminate(_process)
        _process = None


def is_running():
    return _process is not None and _process.poll() is None
