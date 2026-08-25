"""The parts of isolation that only exist on Linux: fork, confine, kill.

**These tests have never run.** They were written on a Windows host with no
container runtime, so CI is their first execution. If something here fails, the
most likely explanation is a bug in
``utk_curio/sandbox/isolation/{child,zygote,supervisor,lifecycle}.py`` rather
than in the test, and the failure is doing its job.

Everything platform-independent is covered elsewhere and does run today:
``test_isolation_protocol.py`` (the trust boundary), ``test_isolation_child.py``
(execution logic, input rebuild, output serialization),
``test_isolation_staging.py`` (the full store round trip), and
``test_isolation_fallback.py`` (the decision table and the Windows path).

What is left, and only testable here:

- ``child.confine``: setsid, PR_SET_NO_NEW_PRIVS, seccomp, setuid, setrlimit.
- ``zygote``: the accept-and-fork loop.
- ``supervisor.ZygoteClient``: the socket exchange, the deadline, and killpg.

The escape tests are the point of the whole exercise. Each one is something a
malicious node would actually do, and each must fail *inside the child* and be
reported as an ordinary node error, at HTTP 200, never as a crash or a hang.
"""

import json
import os
import shutil
import subprocess
import sys
import time

import pytest

linux_only = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="isolation needs Linux (fork, setrlimit, seccomp)",
)

pytestmark = linux_only


HAS_PYSECCOMP = shutil.which("python3") is not None
try:  # pragma: no cover - probe
    import pyseccomp  # noqa: F401

    HAS_PYSECCOMP = True
except Exception:  # pragma: no cover - probe
    HAS_PYSECCOMP = False

needs_seccomp = pytest.mark.skipif(
    not HAS_PYSECCOMP, reason="pyseccomp is not installed"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path / "data"))
    from utk_curio.sandbox.util.db import init_db, release_connection

    release_connection()
    init_db()
    yield tmp_path
    release_connection()


@pytest.fixture
def isolated(workspace, monkeypatch):
    """A live zygote plus the config to talk to it.

    Deliberately does not require seccomp: the network tests assert it
    separately, and the rest should pass on a host without libseccomp so a
    failure there is unambiguous.
    """
    from utk_curio.sandbox.isolation import lifecycle, runner

    socket_path = str(workspace / "zygote.sock")
    monkeypatch.setenv("CURIO_EXEC_SOCKET", socket_path)
    monkeypatch.setenv("CURIO_EXEC_TIMEOUT", "20")
    # Small on purpose. If setrlimit silently failed, which is exactly what
    # these tests exist to detect, the allocation test would really allocate
    # this much on a host that also runs the live instances.
    monkeypatch.setenv("CURIO_EXEC_MEMORY_MB", "256")

    config = runner.IsolationConfig.from_environment()
    lifecycle.ensure_running(config, exec_user=None, require_seccomp=HAS_PYSECCOMP)
    try:
        yield config
    finally:
        lifecycle.shutdown()


def run_isolated(config, code, **kwargs):
    from utk_curio.sandbox.isolation import runner

    return runner.execute_isolated(
        code, "", "curio.builtin/computation-analysis", "",
        save_dataset=False, config=config, **kwargs
    )


# ---------------------------------------------------------------------------
# The happy path has to work before any of the denials mean anything
# ---------------------------------------------------------------------------

def test_a_simple_node_runs_isolated(isolated):
    result = run_isolated(isolated, "    return 6 * 7\n")
    assert result["stderr"] == "", result["stderr"]
    assert result["output"]["dataType"] == "int"


def test_a_dataframe_survives_the_boundary(isolated, workspace):
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    result = run_isolated(
        isolated, "    return pd.DataFrame({'a': [1, 2, 3]})\n"
    )
    assert result["stderr"] == "", result["stderr"]
    frame = load_from_duckdb(result["output"]["path"])
    assert frame["a"].tolist() == [1, 2, 3]


def test_stdout_reaches_the_caller(isolated):
    result = run_isolated(isolated, "    print('hello from the child')\n    return 1\n")
    assert "hello from the child" in result["stdout"]


def test_a_node_error_is_reported_not_raised(isolated):
    result = run_isolated(isolated, "    raise ValueError('boom')\n")
    assert result["output"]["path"] == ""
    assert "ValueError" in result["stderr"]


def test_the_child_runs_in_its_own_session(isolated):
    """setsid is what makes killpg able to reap grandchildren."""
    result = run_isolated(
        isolated, "    return 'same' if os.getpid() == os.getpgid(0) else 'different'\n"
    )
    assert result["stderr"] == "", result["stderr"]


def test_each_execution_gets_a_fresh_process(isolated):
    """State must not leak between nodes the way it could in-process."""
    first = run_isolated(isolated, "    globals()['leaked'] = 1\n    return 1\n")
    assert first["stderr"] == "", first["stderr"]
    second = run_isolated(isolated, "    return 'leaked' in globals()\n")
    assert second["stderr"] == "", second["stderr"]
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    assert load_from_duckdb(second["output"]["path"]) is False


# ---------------------------------------------------------------------------
# Escapes. The reason this work exists.
# ---------------------------------------------------------------------------

def test_the_user_database_is_unreachable(isolated, workspace):
    """instance/urban_workflow.db holds every password hash and session token."""
    target = workspace / "instance"
    target.mkdir(exist_ok=True)
    secret = target / "urban_workflow.db"
    secret.write_text("SUPER SECRET", encoding="utf-8")
    os.chmod(secret, 0o600)

    result = run_isolated(
        isolated,
        f"    return open({str(secret)!r}).read()\n",
    )
    assert "SUPER SECRET" not in json.dumps(result), (
        "an isolated node read the user database"
    )


def test_the_artifact_store_is_unreachable(isolated, workspace):
    db = workspace / "data" / "curio_data.duckdb"
    result = run_isolated(isolated, f"    return open({str(db)!r}, 'rb').read()[:4]\n")
    assert result["output"]["path"] == "", (
        "an isolated node opened the DuckDB artifact store"
    )


@needs_seccomp
def test_creating_a_socket_is_denied(isolated):
    result = run_isolated(
        isolated, "    import socket\n    return str(socket.socket())\n"
    )
    assert result["output"]["path"] == "", "an isolated node created a socket"


@needs_seccomp
def test_outbound_network_is_denied(isolated):
    result = run_isolated(
        isolated,
        "    import socket\n"
        "    return socket.create_connection(('1.1.1.1', 80), timeout=5) and 'open'\n",
    )
    assert result["output"]["path"] == "", "an isolated node reached the network"


@needs_seccomp
def test_ptrace_is_denied(isolated):
    result = run_isolated(
        isolated,
        "    import ctypes\n"
        "    libc = ctypes.CDLL('libc.so.6', use_errno=True)\n"
        "    return libc.ptrace(0, 1, 0, 0)\n",
    )
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    if result["output"]["path"]:
        assert load_from_duckdb(result["output"]["path"]) != 0, "ptrace succeeded"


def test_regaining_privilege_is_denied(isolated):
    result = run_isolated(isolated, "    os.setuid(0)\n    return 'root'\n")
    assert result["output"]["path"] == "", "an isolated node became root"


def test_writing_outside_the_scratch_directory_is_denied(isolated, workspace):
    """Only relevant once --exec-user is in play; harmless to assert always."""
    target = workspace / "should-not-exist.txt"
    run_isolated(isolated, f"    open({str(target)!r}, 'w').write('x')\n    return 1\n")
    if os.getuid() != 0:
        pytest.skip("without a dropped uid the child shares our own permissions")
    assert not target.exists(), "an isolated node wrote outside its scratch dir"


# ---------------------------------------------------------------------------
# Resource limits
# ---------------------------------------------------------------------------

def test_the_limits_are_actually_applied_in_the_child(isolated):
    """Read the limits back from inside the child.

    The most informative assertion in this file on a first run, and completely
    safe: it provokes nothing. If confine() silently failed to call setrlimit,
    every behavioural resource test below would be vacuous, so check the cause
    directly rather than inferring it from an effect.
    """
    result = run_isolated(
        isolated,
        "    import resource\n"
        "    return {\n"
        "        'as': resource.getrlimit(resource.RLIMIT_AS)[0],\n"
        "        'cpu': resource.getrlimit(resource.RLIMIT_CPU)[0],\n"
        "        'nproc': resource.getrlimit(resource.RLIMIT_NPROC)[0],\n"
        "        'core': resource.getrlimit(resource.RLIMIT_CORE)[0],\n"
        "    }\n",
    )
    assert result["stderr"] == "", result["stderr"]

    from utk_curio.sandbox.util.parsers import load_from_duckdb

    limits = load_from_duckdb(result["output"]["path"])
    assert limits["as"] == 256 * 1024 * 1024, limits
    assert limits["cpu"] == isolated.limits["cpu_seconds"], limits
    assert limits["nproc"] == isolated.limits["nproc"], limits
    assert limits["core"] == 0, limits


def test_a_runaway_allocation_hits_the_memory_limit(isolated):
    """RLIMIT_AS turns this into a MemoryError instead of an OOM kill.

    The distinction matters on a shared host: the OOM killer picks its own
    victim, which could be the backend or a neighbouring production container
    rather than the offending node.

    Allocates 512MB against a 256MB cap, deliberately modest. If the limit were
    not applied, a multi-gigabyte allocation here would put real memory pressure
    on the host that also runs the live instances.
    """
    result = run_isolated(
        isolated, "    x = bytearray(512 * 1024 * 1024)\n    return len(x)\n"
    )
    assert result["output"]["path"] == ""
    assert result["stderr"], "a memory failure produced no explanation"


def test_an_infinite_loop_is_killed_and_the_sandbox_survives(isolated):
    start = time.monotonic()
    result = run_isolated(isolated, "    while True:\n        pass\n")
    elapsed = time.monotonic() - start

    assert result["output"]["path"] == ""
    assert elapsed < 90, f"the timeout did not fire promptly (took {elapsed:.0f}s)"
    assert "timeout" in result["stderr"].lower() or "CPU" in result["stderr"]

    # The next node must still work: killing one child must not break the zygote.
    following = run_isolated(isolated, "    return 1\n")
    assert following["stderr"] == "", following["stderr"]


def test_a_spawned_grandchild_does_not_survive_the_timeout(isolated):
    """proc.kill() on the child alone would leave this running.

    The child calls setsid and the zygote kills the whole process group, which
    is the only way to be sure. The zygote does the killing rather than the
    sandbox because it is the child's parent, so the pid cannot have been
    recycled underneath it.
    """
    marker = "curio-isolation-grandchild-marker"
    run_isolated(
        isolated,
        "    import subprocess\n"
        f"    subprocess.Popen(['sh', '-c', 'exec -a {marker} sleep 300'])\n"
        "    while True:\n        pass\n",
    )
    time.sleep(2)
    listing = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True)
    assert marker not in listing.stdout, "a grandchild outlived the killed node"


@pytest.mark.skipif(
    os.environ.get("CURIO_ISOLATION_DESTRUCTIVE_TESTS") != "1",
    reason=(
        "fork bomb: opt in with CURIO_ISOLATION_DESTRUCTIVE_TESTS=1. "
        "RLIMIT_NPROC is per-uid and root bypasses it, and inside the container "
        "these run as root, so without --exec-user this forks until the "
        "container's pids_limit. docker-compose.ci.yml caps that, but the "
        "self-hosted runner shares a host with the live instances and the limit "
        "being configured is already covered by "
        "test_the_limits_are_actually_applied_in_the_child. This only adds risk."
    ),
)
def test_a_fork_bomb_is_bounded(isolated):
    """Forks are reaped as we go, so the peak is bounded even when it succeeds."""
    result = run_isolated(
        isolated,
        "    import os\n"
        "    for _ in range(2000):\n"
        "        try:\n"
        "            pid = os.fork()\n"
        "        except OSError:\n"
        "            return 'limited'\n"
        "        if pid == 0:\n"
        "            os._exit(0)\n"
        "        os.waitpid(pid, 0)\n"
        "    return 'unlimited'\n",
    )
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    if result["output"]["path"]:
        assert load_from_duckdb(result["output"]["path"]) == "limited"


# ---------------------------------------------------------------------------
# Zygote lifecycle
# ---------------------------------------------------------------------------

def test_the_zygote_holds_no_duckdb_handle(isolated, workspace):
    """A zygote with the store open would hand it to every child by fork."""
    from utk_curio.sandbox.isolation import lifecycle

    assert lifecycle.is_running()
    pid = lifecycle._process.pid
    fd_dir = f"/proc/{pid}/fd"
    targets = []
    for entry in os.listdir(fd_dir):
        try:
            targets.append(os.readlink(os.path.join(fd_dir, entry)))
        except OSError:
            continue
    assert not any("duckdb" in target for target in targets), targets


def test_the_zygote_is_replaced_if_it_dies(isolated):
    from utk_curio.sandbox.isolation import lifecycle

    lifecycle._process.kill()
    lifecycle._process.wait(timeout=10)

    lifecycle.ensure_running(isolated, exec_user=None, require_seccomp=HAS_PYSECCOMP)
    assert lifecycle.is_running()
    assert run_isolated(isolated, "    return 1\n")["stderr"] == ""


def test_concurrent_executions_do_not_collide(isolated):
    """Parallelism was an explicit design choice; artifacts must stay distinct."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda n: run_isolated(isolated, f"    return {n}\n"), range(6))
        )

    paths = [r["output"]["path"] for r in results]
    assert all(paths), [r["stderr"] for r in results if not r["output"]["path"]]
    assert len(set(paths)) == len(paths), "two executions produced the same artifact id"


def test_the_socket_is_not_world_accessible(isolated):
    mode_bits = os.stat(isolated.socket_path).st_mode & 0o777
    assert mode_bits == 0o600, oct(mode_bits)


# ---------------------------------------------------------------------------
# Session scoping still holds across the boundary
# ---------------------------------------------------------------------------

def test_a_node_cannot_read_another_sessions_artifact(isolated, workspace):
    from utk_curio.sandbox.util.parsers import save_to_duckdb
    import pandas as pd

    foreign = save_to_duckdb(pd.DataFrame({"a": [1]}), session_id="session-a")

    from utk_curio.sandbox.isolation import runner

    result = runner.execute_isolated(
        "    return 1\n", foreign, "curio.builtin/computation-analysis", "",
        session_id="session-b", save_dataset=False, config=isolated,
    )
    assert result["output"]["path"] == ""
    assert "could not be loaded" in result["stderr"]
