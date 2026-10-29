"""The sandbox gives freed memory back once it is idle (#408).

When the last request in flight has finished, the sandbox returns what its
allocators keep free to the system (``sandbox/util/memory_release.py``). These
tests pin the parts: the release runs once the last response has been sent and
never while one is still being served, the sandbox app is served through it,
on glibc the release returns the freed heap memory a request thread left
behind, and on a many-core host what hundreds of threads freed does not stay
in hundreds of arenas, since the launcher starts the server with its allocators
fitted as its isolated children's are: arenas capped, Arrow allocating in them,
and glibc's thresholds held fixed, so an arena gives back a big block a thread
frees rather than keeping it at its top. ``test_rerun_memory.py`` measures the
whole effect on a real sandbox.
"""

import ctypes
import io
import json
import os
import subprocess
import sys
import textwrap
import types

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))


def _start_response(status, headers, exc_info=None):
    return lambda data: None


def _streaming_app(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/plain")])
    return iter([b"first", b"second"])


def test_memory_is_released_when_the_last_request_in_flight_finishes():
    from utk_curio.sandbox.util.memory_release import ReleaseMemoryWhenIdle

    released = []
    served = ReleaseMemoryWhenIdle(_streaming_app, release=lambda: released.append(True))

    first = served({}, _start_response)
    second = served({}, _start_response)
    assert list(first) == [b"first", b"second"]
    first.close()
    assert released == [], "released while another request was still being served"

    assert next(second) == b"first"
    assert released == [], "released while a response was still streaming"
    second.close()
    assert released == [True]

    third = served({}, _start_response)
    list(third)
    third.close()
    assert released == [True, True], "each time the sandbox goes idle, not only the first"


def test_a_request_that_raises_still_finishes():
    from utk_curio.sandbox.util.memory_release import ReleaseMemoryWhenIdle

    def broken(environ, start_response):
        raise RuntimeError("the view failed")

    released = []
    served = ReleaseMemoryWhenIdle(broken, release=lambda: released.append(True))
    with pytest.raises(RuntimeError):
        served({}, _start_response)
    assert released == [True]


def test_the_sandbox_app_releases_memory_once_a_request_is_served(monkeypatch):
    from utk_curio.sandbox.app import app
    from utk_curio.sandbox.util.memory_release import ReleaseMemoryWhenIdle

    assert isinstance(app.wsgi_app, ReleaseMemoryWhenIdle)
    released = []
    monkeypatch.setattr(app.wsgi_app, "_release", lambda: released.append(True))
    # The suite's other test-client responses are never closed, so they still
    # count as in flight; this test starts from none.
    monkeypatch.setattr(app.wsgi_app, "_in_flight", 0)

    response = app.test_client().get("/live")
    assert response.status_code == 200
    assert released == [], "released before the response was closed"
    response.close()
    assert released == [True]


#: In a fresh interpreter: a thread fills its malloc arena with 4 KiB blocks
#: and frees all but one in 64, as a request thread does with a frame it
#: returned (what stays allocated keeps the freed blocks off the top of the
#: heap, which glibc would trim by itself). Prints the resident memory before
#: and after one release as a ``RESULT`` line of JSON.
FRAGMENT_THEN_RELEASE = textwrap.dedent("""
    import ctypes
    import json
    import os
    import threading

    from utk_curio.sandbox.util.memory_release import release_free_memory

    libc = ctypes.CDLL(None)
    libc.malloc.restype = ctypes.c_void_p
    libc.malloc.argtypes = [ctypes.c_size_t]
    libc.free.argtypes = [ctypes.c_void_p]
    libc.memset.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t]

    BLOCK, BLOCKS, KEEP_EVERY = 4096, 50_000, 64
    kept = []

    def request_thread():
        blocks = [libc.malloc(BLOCK) for _ in range(BLOCKS)]
        for block in blocks:
            libc.memset(block, 1, BLOCK)
        for index, block in enumerate(blocks):
            if index % KEEP_EVERY:
                libc.free(block)
            else:
                kept.append(block)

    def resident_mb():
        with open("/proc/self/statm") as handle:
            return int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20

    thread = threading.Thread(target=request_thread)
    thread.start()
    thread.join()
    before = resident_mb()
    release_free_memory()
    after = resident_mb()
    freed = BLOCK * (BLOCKS - len(kept)) / 2**20
    print("RESULT " + json.dumps({"freed": freed, "before": before, "after": after}))
""")


@pytest.mark.skipif(
    not sys.platform.startswith("linux") or not hasattr(ctypes.CDLL(None), "malloc_trim"),
    reason="malloc_trim is glibc's",
)
def test_a_release_returns_the_heap_memory_a_request_thread_freed():
    done = subprocess.run(
        [sys.executable, "-c", FRAGMENT_THEN_RELEASE],
        cwd=REPO_ROOT, env={**os.environ, "PYTHONPATH": REPO_ROOT},
        capture_output=True, text=True, timeout=300,
    )
    lines = [line for line in done.stdout.splitlines() if line.startswith("RESULT ")]
    assert done.returncode == 0 and lines, (
        f"exit {done.returncode}\n{done.stdout[-2000:]}\n{done.stderr[-4000:]}"
    )
    seen = json.loads(lines[-1][len("RESULT "):])
    returned = seen["before"] - seen["after"]
    assert returned >= 0.75 * seen["freed"], (
        f"the release returned {returned:.0f} MB of the {seen['freed']:.0f} MB "
        f"a request thread freed (resident {seen['before']:.0f} MB -> {seen['after']:.0f} MB)"
    )


#: In a fresh interpreter: one block bigger than the others is mapped on its
#: own and freed, which raises glibc's mmap and trim thresholds as a sandbox's
#: first runs do. Then request threads, all alive at once, take turns to
#: allocate a block, fill it and free it, so each block goes back to the top of
#: its thread's arena. Prints the resident anonymous memory before the threads
#: and after one release, and how many arenas glibc made, as a ``RESULT`` line
#: of JSON. ``CURIO_TEST_PRIMER_MIB`` and ``CURIO_TEST_BLOCK_MIB`` size the two
#: kinds of block (9 and 8 MiB unless set).
THREADS_FREE_THEN_RELEASE = textwrap.dedent("""
    import ctypes
    import json
    import os
    import re
    import tempfile
    import threading

    from utk_curio.sandbox.util.memory_release import release_free_memory

    libc = ctypes.CDLL(None)
    libc.malloc.restype = ctypes.c_void_p
    libc.malloc.argtypes = [ctypes.c_size_t]
    libc.free.argtypes = [ctypes.c_void_p]
    libc.memset.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t]
    libc.fopen.restype = ctypes.c_void_p
    libc.fopen.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    libc.fclose.argtypes = [ctypes.c_void_p]
    libc.malloc_info.argtypes = [ctypes.c_int, ctypes.c_void_p]

    MIB = 2**20
    PRIMER = int(os.environ.get("CURIO_TEST_PRIMER_MIB", "9")) * MIB
    BLOCK = int(os.environ.get("CURIO_TEST_BLOCK_MIB", "8")) * MIB
    THREADS = 96

    def anon_mib():
        with open("/proc/self/status") as handle:
            for line in handle:
                if line.startswith("RssAnon:"):
                    return int(line.split()[1]) / 1024

    def arenas():
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "malloc.xml")
            stream = libc.fopen(path.encode(), b"w")
            libc.malloc_info(0, stream)
            libc.fclose(stream)
            with open(path) as handle:
                return len(re.findall(r"<heap nr=", handle.read()))

    primer = libc.malloc(PRIMER)
    libc.memset(primer, 1, PRIMER)
    libc.free(primer)
    release_free_memory()
    before = anon_mib()

    together = threading.Barrier(THREADS)
    turn = threading.Lock()

    def request_thread():
        together.wait()
        with turn:
            block = libc.malloc(BLOCK)
            libc.memset(block, 1, BLOCK)
            libc.free(block)
        together.wait()

    threads = [threading.Thread(target=request_thread) for _ in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    release_free_memory()
    print("RESULT " + json.dumps({
        "before": before, "after": anon_mib(), "arenas": arenas(), "threads": THREADS,
        "block": BLOCK / MIB, "arena_max": os.environ.get("MALLOC_ARENA_MAX"),
        "mmap_threshold": os.environ.get("MALLOC_MMAP_THRESHOLD_"),
        "trim_threshold": os.environ.get("MALLOC_TRIM_THRESHOLD_"),
    }))
""")


def _sandbox_launch_environment(monkeypatch):
    """The environment the launcher starts the sandbox server with
    (``utk_curio.cli.services.start_sandbox``), no process started."""
    from utk_curio.cli import services

    started = {}

    class _Started:
        def __init__(self):
            self.stdout = io.StringIO("")
            self.stderr = None

        def poll(self):
            return 0

    def popen(args, **kwargs):
        started["env"] = kwargs["env"]
        return _Started()

    monkeypatch.setattr(services, "subprocess", types.SimpleNamespace(
        Popen=popen, PIPE=subprocess.PIPE, STDOUT=subprocess.STDOUT))
    monkeypatch.setattr(services, "_kill_port", lambda port: None)
    monkeypatch.setattr(services, "_skip_dep_install", lambda: True)
    services.start_sandbox("127.0.0.1", 2999)
    return started["env"]


@pytest.mark.skipif(
    not sys.platform.startswith("linux") or not hasattr(ctypes.CDLL(None), "malloc_trim"),
    reason="malloc_trim is glibc's",
)
def test_on_a_many_core_host_the_idle_sandbox_keeps_little_of_what_its_threads_freed(monkeypatch):
    from utk_curio.sandbox.isolation.lifecycle import malloc_arena_cap

    # glibc's own limit on a 64-core host (eight arenas a core), as on the CI
    # GPU runners, whatever this runner has.
    monkeypatch.setenv("MALLOC_ARENA_MAX", "512")
    monkeypatch.setenv("CURIO_EXEC_MEMORY_MB", "4096")
    cap = malloc_arena_cap(4096)
    env = _sandbox_launch_environment(monkeypatch)
    done = subprocess.run(
        [sys.executable, "-c", THREADS_FREE_THEN_RELEASE],
        cwd=REPO_ROOT, env={**env, "PYTHONPATH": REPO_ROOT},
        capture_output=True, text=True, timeout=300,
    )
    lines = [line for line in done.stdout.splitlines() if line.startswith("RESULT ")]
    assert done.returncode == 0 and lines, (
        f"exit {done.returncode}\n{done.stdout[-2000:]}\n{done.stderr[-4000:]}"
    )
    seen = json.loads(lines[-1][len("RESULT "):])
    kept = seen["after"] - seen["before"]
    # One freed block at the top of each arena the cap allows, and some slack.
    allowed = cap * seen["block"] + 64
    assert kept <= allowed, (
        f"after the idle release the sandbox kept {kept:.0f} MiB of what "
        f"{seen['threads']} request threads freed, in {seen['arenas']} malloc arenas "
        f"(MALLOC_ARENA_MAX {seen['arena_max']}); at most {allowed:.0f} MiB, with its "
        f"arenas capped at {cap} as an isolated child's are"
    )
    assert seen["arenas"] <= cap, seen


@pytest.mark.skipif(
    not sys.platform.startswith("linux") or not hasattr(ctypes.CDLL(None), "malloc_trim"),
    reason="malloc_trim is glibc's",
)
def test_the_idle_sandbox_keeps_none_of_the_big_blocks_its_threads_freed(monkeypatch):
    """With the thresholds glibc raises by itself, a big block a request
    thread frees goes back to the top of the thread's arena. A 24 MiB block
    freed first raises the trim threshold to 48 MiB, so each arena keeps a
    12 MiB block at its top, and the idle release cannot trim it
    (``malloc_trim`` trims only the main arena's top): one block an arena,
    16 arenas under the cap. Held fixed, as the launcher holds them, the
    arena gives the block back when it is freed."""
    monkeypatch.setenv("MALLOC_ARENA_MAX", "512")
    monkeypatch.setenv("CURIO_EXEC_MEMORY_MB", "4096")
    monkeypatch.delenv("MALLOC_MMAP_THRESHOLD_", raising=False)
    monkeypatch.delenv("MALLOC_TRIM_THRESHOLD_", raising=False)
    env = _sandbox_launch_environment(monkeypatch)
    sizes = {"CURIO_TEST_PRIMER_MIB": "24", "CURIO_TEST_BLOCK_MIB": "12"}
    done = subprocess.run(
        [sys.executable, "-c", THREADS_FREE_THEN_RELEASE],
        cwd=REPO_ROOT, env={**env, **sizes, "PYTHONPATH": REPO_ROOT},
        capture_output=True, text=True, timeout=300,
    )
    lines = [line for line in done.stdout.splitlines() if line.startswith("RESULT ")]
    assert done.returncode == 0 and lines, (
        f"exit {done.returncode}\n{done.stdout[-2000:]}\n{done.stderr[-4000:]}"
    )
    seen = json.loads(lines[-1][len("RESULT "):])
    kept = seen["after"] - seen["before"]
    assert kept <= seen["block"], (
        f"after the idle release the sandbox kept {kept:.0f} MiB of the {seen['block']:.0f} MiB "
        f"blocks {seen['threads']} request threads freed, in {seen['arenas']} malloc arenas "
        f"(MALLOC_ARENA_MAX {seen['arena_max']}, MALLOC_MMAP_THRESHOLD_ {seen['mmap_threshold']}, "
        f"MALLOC_TRIM_THRESHOLD_ {seen['trim_threshold']}); at most one block: a block glibc "
        "did not map on its own stays at the top of its arena"
    )


#: In a fresh interpreter: the pool Arrow allocates from, as a ``RESULT`` line.
ARROW_POOL = textwrap.dedent("""
    import json

    import pyarrow

    print("RESULT " + json.dumps({"pool": pyarrow.default_memory_pool().backend_name}))
""")


def test_the_sandbox_server_allocates_arrow_memory_in_its_capped_arenas(monkeypatch):
    monkeypatch.delenv("ARROW_DEFAULT_MEMORY_POOL", raising=False)
    env = _sandbox_launch_environment(monkeypatch)
    done = subprocess.run(
        [sys.executable, "-c", ARROW_POOL],
        cwd=REPO_ROOT, env={**env, "PYTHONPATH": REPO_ROOT},
        capture_output=True, text=True, timeout=120,
    )
    lines = [line for line in done.stdout.splitlines() if line.startswith("RESULT ")]
    assert done.returncode == 0 and lines, (
        f"exit {done.returncode}\n{done.stdout[-2000:]}\n{done.stderr[-4000:]}"
    )
    pool = json.loads(lines[-1][len("RESULT "):])["pool"]
    assert pool == "system", (
        f"the sandbox server's Arrow allocates from {pool}, not from glibc's capped arenas; "
        "in test-gpu's repeat runs its mimalloc pool kept up to about 500 MiB a sandbox "
        "that the idle release did not reach"
    )


def test_the_sandbox_server_fits_its_allocators_as_its_isolated_children_do():
    from utk_curio.sandbox.isolation.lifecycle import (
        malloc_arena_cap,
        server_environment,
        zygote_environment,
    )

    fixed = {"MALLOC_MMAP_THRESHOLD_": str(32 * 2**20), "MALLOC_TRIM_THRESHOLD_": str(8 * 2**20)}
    for budget in (4096, 16384):
        server = server_environment({"CURIO_EXEC_MEMORY_MB": str(budget), "MALLOC_ARENA_MAX": "512"})
        assert server["MALLOC_ARENA_MAX"] == str(malloc_arena_cap(budget))
        assert server["ARROW_DEFAULT_MEMORY_POOL"] == "system"
        assert {name: server.get(name) for name in fixed} == fixed, (
            "glibc's thresholds rise by themselves unless they are set; risen, a big block a "
            "request frees stays at the top of an arena the idle release cannot trim"
        )
        # The zygote inherits the server's environment: its children's cap is
        # the one their budget gives, not lowered by the server's.
        children = zygote_environment({"memory_mb": budget}, server)
        assert children["MALLOC_ARENA_MAX"] == str(malloc_arena_cap(budget))
        assert children["ARROW_DEFAULT_MEMORY_POOL"] == "system"
        assert {name: children.get(name) for name in fixed} == fixed
    assert server_environment({})["MALLOC_ARENA_MAX"] == "16", "the default budget, 4096 MB"
    assert server_environment({"CURIO_EXEC_MEMORY_MB": "oops"})["MALLOC_ARENA_MAX"] == "16"
    assert server_environment({"MALLOC_ARENA_MAX": "4"})["MALLOC_ARENA_MAX"] == "4", (
        "an operator's lower cap stands"
    )
    assert server_environment({"ARROW_DEFAULT_MEMORY_POOL": "jemalloc"})[
        "ARROW_DEFAULT_MEMORY_POOL"] == "jemalloc", "an operator's pool stands"
    operator = server_environment({"MALLOC_MMAP_THRESHOLD_": "65536"})
    assert (operator.get("MALLOC_MMAP_THRESHOLD_"), operator.get("MALLOC_TRIM_THRESHOLD_")) == (
        "65536", fixed["MALLOC_TRIM_THRESHOLD_"]), "an operator's threshold stands"
