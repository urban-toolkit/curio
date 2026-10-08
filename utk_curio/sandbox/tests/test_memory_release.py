"""The sandbox gives freed memory back once it is idle (#408).

When the last request in flight has finished, the sandbox returns what its
allocators keep free to the system (``sandbox/util/memory_release.py``). These
tests pin the parts: the release runs once the last response has been sent and
never while one is still being served, the sandbox app is served through it,
and on glibc the release returns the freed heap memory a request thread left
behind. ``test_rerun_memory.py`` measures the whole effect on a real sandbox.
"""

import ctypes
import json
import os
import subprocess
import sys
import textwrap

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
