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

#: The Arrow memory pool a memory-capped zygote's children allocate from:
#: glibc's malloc, in the arenas capped above.
ARROW_POOL_UNDER_A_CAP = "system"


class ZygoteStartupError(RuntimeError):
    """The zygote could not be started or never became ready."""


def malloc_arena_cap(memory_mb):
    """How many malloc arenas a child with *memory_mb* of budget may hold."""
    return max(2, int(memory_mb) // MALLOC_ARENA_SHARE // MALLOC_ARENA_MB)


def zygote_environment(limits, environ=None):
    """The zygote's environment: this process's, with its allocators fitted to the cap.

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

    Arrow's allocator is the other reservation (#376). pyarrow's default pool,
    mimalloc, reserves an arena of address space on a child's first Arrow
    allocation: 1 GiB when that fits under the cap, else 128 MiB. RLIMIT_AS
    counts the whole arena, so at the default budget a quarter of it is gone
    before the node's own data. And when the space left is just over an
    arena's size, the arena fits but the 64 KiB its page map needs next does
    not, and the allocation fails with ``ArrowMemoryError``: budgets of 128
    and 1024 MB, the two arena sizes, failed a node's first 64 bytes. pandas
    reaches Arrow for any string, column labels included, since its default
    string dtype is Arrow-backed. Under a cap Arrow allocates through glibc
    instead (``ARROW_DEFAULT_MEMORY_POOL``), which maps only what it uses, in
    the arenas capped above. Arrow reads that variable once, when it is
    loaded, and the zygote loads it before its first fork, so a child could
    not change it; unlike ``MALLOC_ARENA_MAX``, a pool already named in the
    environment does not stand under a cap.
    """
    env = dict(os.environ if environ is None else environ)
    memory_mb = (limits or {}).get("memory_mb")
    if memory_mb:
        _cap_arenas(env, memory_mb)
        env["ARROW_DEFAULT_MEMORY_POOL"] = ARROW_POOL_UNDER_A_CAP
    return env


def _cap_arenas(env, memory_mb):
    """Cap *env*'s malloc arenas for *memory_mb* of budget; a lower
    ``MALLOC_ARENA_MAX`` already in *env* stands."""
    cap = malloc_arena_cap(memory_mb)
    try:
        current = int(env.get("MALLOC_ARENA_MAX", ""))
    except ValueError:
        current = 0
    env["MALLOC_ARENA_MAX"] = str(min(current, cap) if current > 0 else cap)


def server_environment(environ=None):
    """The sandbox server's environment: its malloc arenas capped as its
    isolated children's are, from the same budget (``CURIO_EXEC_MEMORY_MB``,
    4096 MB by default, so 16 arenas).

    The server runs node code itself when isolation is off, a local launch's
    default, and serves every run's outputs either way. glibc gives each thread
    that allocates an arena of its own, up to eight per core, and a block a
    thread frees goes back to the top of its arena, which glibc keeps while it
    is smaller than its trim threshold. That threshold rises with the blocks a
    process frees, up to 64 MiB. When the server goes idle it hands free memory
    back (``util/memory_release.py``), but ``malloc_trim`` trims only the main
    arena's top, so every other arena keeps its top.

    #408 measured this on four cores, 32 arenas at most. A 64-core CI runner
    allows 512, and a sandbox there runs about 500 threads: its libraries'
    pools, sized by the cores, and one per request. Each test pass left free
    memory in more of their arenas: in a repeat run of test-gpu, its six
    sandboxes grew 3.6 GiB in the second pass and 2.9 in the third, all of it
    free memory in arenas, while what each held in use stayed at 140 to 190
    MiB (run 40715721924). With the cap, threads beyond it share the arenas
    there are, as an isolated child's do; how many threads a library starts
    is unchanged.

    Set in the environment the server starts with, because glibc settles its
    arena limit once per process. The server's children inherit it, the
    zygote among them, whose own cap from the same budget is the same number.
    """
    from utk_curio.sandbox.isolation.supervisor import DEFAULT_LIMITS

    env = dict(os.environ if environ is None else environ)
    try:
        memory_mb = int(env.get("CURIO_EXEC_MEMORY_MB") or DEFAULT_LIMITS["memory_mb"])
    except ValueError:
        memory_mb = DEFAULT_LIMITS["memory_mb"]
    _cap_arenas(env, memory_mb)
    # Diagnostic branch only: Arrow allocates through glibc, as under a cap.
    env["ARROW_DEFAULT_MEMORY_POOL"] = ARROW_POOL_UNDER_A_CAP
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
