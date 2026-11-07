"""The parts of isolation that only exist on Linux: fork, confine, kill.

**Run by the sandbox half of the ``unit`` CI job, and by nothing else.** Not by
``test-isolated``, which boots a stack with ``CURIO_ISOLATION=fork`` and
runs ``scripts/test.sh --e2e-only`` against it, and not by
``test-exec-user``, which runs ``sandbox/tests/live``. Nothing here touches
a running stack: each test builds its own ``IsolationConfig`` and starts its
own zygote, so the ambient ``CURIO_ISOLATION`` is not consulted and a green run
of either other job says nothing about this file.

If something here fails, the most likely explanation is a bug in
``utk_curio/sandbox/isolation/{child,zygote,supervisor,lifecycle}.py`` rather
than in the test, and the failure is doing its job.

Everything platform-independent is covered elsewhere:
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

import os
import re
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

# Headroom above the interpreter's own footprint (see child._apply_rlimits),
# not an absolute ceiling.
MEMORY_HEADROOM_MB = 256

# Created by the Dockerfile. Only exists inside the image.
EXEC_USER = "curio-exec"


def _memory_bytes(text):
    """Parse a DuckDB memory_limit reading into bytes.

    DuckDB does not echo the string it was given: "256MB" comes back as
    "244.1 MiB", because it reads MB as 10^6 and reports in MiB. Comparing
    magnitudes is the only way to assert a budget rather than a formatting
    detail.
    """
    m = re.match(r"^\s*([\d.]+)\s*(B|KB|MB|GB|KiB|MiB|GiB)\s*$", str(text))
    assert m, f"unparseable memory_limit: {text!r}"
    scale = {"B": 1, "KB": 10 ** 3, "MB": 10 ** 6, "GB": 10 ** 9,
             "KiB": 1 << 10, "MiB": 1 << 20, "GiB": 1 << 30}[m.group(2)]
    return float(m.group(1)) * scale


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
def isolated(request, workspace, monkeypatch):
    """A live zygote plus the config to talk to it.

    Deliberately does not require seccomp: the network tests assert it
    separately, and the rest should pass on a host without libseccomp so a
    failure there is unambiguous.

    Parametrize indirectly to run a test at a different memory budget; the
    tests that care read it back off ``config.limits`` rather than the module
    constant, so they stay true whichever budget they were given.
    """
    from utk_curio.sandbox.isolation import lifecycle, runner

    budget_mb = getattr(request, "param", MEMORY_HEADROOM_MB)
    socket_path = str(workspace / "zygote.sock")
    monkeypatch.setenv("CURIO_EXEC_SOCKET", socket_path)
    monkeypatch.setenv("CURIO_EXEC_TIMEOUT", "20")
    # Headroom above the warm interpreter's own footprint, not a total: see
    # child._apply_rlimits. Small, so a runaway allocation is caught quickly,
    # but the interpreter's baseline is excluded so ordinary pandas work fits.
    monkeypatch.setenv("CURIO_EXEC_MEMORY_MB", str(budget_mb))

    config = runner.IsolationConfig.from_environment()
    lifecycle.ensure_running(config, exec_user=None, require_seccomp=HAS_PYSECCOMP)
    try:
        yield config
    finally:
        lifecycle.shutdown()


@pytest.fixture
def isolated_dropped(tmp_path_factory, monkeypatch):
    """A zygote whose children run as an unprivileged user.

    The default ``isolated`` fixture configures no execution user, so inside the
    container the child runs as root, exactly as a launch without
    an execution user would. That is the right default to test, but it means the
    filesystem half of the boundary is not exercised: root ignores mode bits.

    This fixture drops to ``curio-exec`` (created by the Dockerfile) so the
    privilege and filesystem tests mean something. It needs its own workspace
    because pytest's ``tmp_path`` is mode 0700 and root-owned, so a dropped
    child could not even traverse into its own scratch directory.
    """
    import pwd

    from utk_curio.sandbox.isolation import lifecycle, runner
    from utk_curio.sandbox.util.db import init_db, release_connection

    if os.getuid() != 0:
        pytest.skip("dropping privileges requires starting as root")
    try:
        pwd.getpwnam(EXEC_USER)
    except KeyError:
        pytest.skip(f"the {EXEC_USER} account does not exist on this host")

    root = tmp_path_factory.mktemp("dropped", numbered=True)
    # 0711 up the chain: the child must traverse to its scratch dir without
    # being able to list any level of it.
    current = root
    while str(current) != os.path.dirname(str(current)):
        try:
            os.chmod(current, 0o711)
        except OSError:
            break
        current = current.parent

    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(root))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(root / "data"))
    monkeypatch.setenv("CURIO_EXEC_SOCKET", str(root / "zygote.sock"))
    monkeypatch.setenv("CURIO_EXEC_TIMEOUT", "20")
    monkeypatch.setenv("CURIO_EXEC_MEMORY_MB", str(MEMORY_HEADROOM_MB))
    monkeypatch.setenv("CURIO_EXEC_USER", EXEC_USER)

    release_connection()
    init_db()
    os.chmod(root / "data", 0o711)

    config = runner.IsolationConfig.from_environment()
    lifecycle.ensure_running(
        config, exec_user=EXEC_USER, require_seccomp=HAS_PYSECCOMP
    )
    try:
        yield config
    finally:
        lifecycle.shutdown()
        release_connection()


def run_isolated(config, code, **kwargs):
    from utk_curio.sandbox.isolation import runner

    return runner.execute_isolated(
        code, "", "curio.builtin/python-computation", "",
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
    """setsid is what makes killpg able to reap grandchildren: the child's pid
    is its session's id and its process group's."""
    result = run_isolated(
        isolated,
        "    return 'same' if os.getpid() == os.getsid(0) == os.getpgid(0) else 'different'\n",
    )
    assert result["stderr"] == "", result["stderr"]

    from utk_curio.sandbox.util.parsers import load_from_duckdb

    assert load_from_duckdb(result["output"]["path"]) == "same", (
        "the child does not lead both its own session and its own process group"
    )


def test_each_execution_gets_a_fresh_process(isolated):
    """State must not leak between nodes the way it could in-process."""
    first = run_isolated(isolated, "    globals()['leaked'] = 1\n    return 1\n")
    assert first["stderr"] == "", first["stderr"]
    second = run_isolated(isolated, "    return 'leaked' in globals()\n")
    assert second["stderr"] == "", second["stderr"]
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    assert load_from_duckdb(second["output"]["path"]) is False


def test_a_node_reads_a_file_by_relative_path(isolated, workspace):
    """Node code addresses its data relative to the launch directory.

    Every bundled example does this -- `gpd.read_file("docs/examples/data/
    access_score.geojson")` -- and `confine` used to chdir into the scratch
    directory, so all of them failed with "No such file or directory". Not a
    permissions failure: the child could read the file perfectly well, it was
    looking in the wrong place. The isolated CI job found it; nothing in this
    suite did, because every test here passes its data in rather than reading
    it off disk.
    """
    data = workspace / "docs" / "examples" / "data"
    data.mkdir(parents=True)
    (data / "thing.txt").write_text("42", encoding="utf-8")
    os.chmod(workspace / "docs", 0o755)
    os.chmod(data, 0o755)
    os.chmod(data / "thing.txt", 0o644)

    result = run_isolated(
        isolated,
        "    with open('docs/examples/data/thing.txt') as f:\n"
        "        return int(f.read())\n",
        launch_dir=str(workspace),
    )

    assert result["stderr"] == "", result["stderr"]
    assert result["output"]["dataType"] == "int"


def test_a_node_reads_the_shipped_example_data_from_a_launch_folder_without_docs(isolated, workspace):
    """A pip install starts from a folder of the user's, which holds no
    `docs/`, and keeps the `docs/` Curio ships inside `utk_curio/`. The
    shipped examples read their data by its path all the same: a user's run
    through the `docs/` its work directory links, and a run without one (an
    unauthenticated launch) in the launch folder itself.
    """
    import hashlib

    from utk_curio import shipped

    raster = "docs/examples/data/niteroi_lst_verao_2001_2024.tif"
    code = (
        "    import hashlib\n"
        f"    with open({raster!r}, 'rb') as f:\n"
        "        print(hashlib.sha256(f.read()).hexdigest())\n"
        "    return 1\n"
    )
    digest = hashlib.sha256(shipped.path(raster).read_bytes()).hexdigest()
    assert not (workspace / "docs").exists()

    for user_key in ("7", None):
        result = run_isolated(isolated, code, launch_dir=str(workspace), user_key=user_key)

        assert result["stderr"] == "", (user_key, result["stderr"])
        assert digest in result["stdout"], (user_key, result["stdout"])


def test_the_scratch_directory_is_still_where_output_lands(isolated, workspace):
    """Moving the cwd must not move where the child writes its result.

    Every child-side write joins scratch_dir explicitly, so this holds by
    construction -- pinned because a future "simplification" to relative paths
    would put node output in the launch tree, which the child cannot write.
    """
    result = run_isolated(
        isolated, "    return {'a': 1}\n", launch_dir=str(workspace)
    )

    assert result["stderr"] == "", result["stderr"]
    assert result["output"]["path"]


def test_a_node_writes_and_reads_back_in_its_user_directory(isolated, workspace):
    """The point of the per-user work directory.

    A node writing a file and reading it back is ordinary: a cache, an
    intermediate, a `to_csv` the next node picks up. Before this, the write
    either vanished with the per-execution scratch directory or landed in the
    application tree.
    """
    result = run_isolated(
        isolated,
        "    with open('note.txt', 'w') as f:\n"
        "        f.write('kept')\n"
        "    with open('note.txt') as f:\n"
        "        return f.read()\n",
        launch_dir=str(workspace),
        user_key="7",
    )

    assert result["stderr"] == "", result["stderr"]
    assert result["output"]["dataType"] == "str"


def test_what_a_node_writes_survives_to_the_next_execution(isolated, workspace):
    """Persistent, unlike the per-execution scratch directory."""
    first = run_isolated(
        isolated,
        "    with open('carried.txt', 'w') as f:\n"
        "        f.write('across')\n"
        "    return 'written'\n",
        launch_dir=str(workspace),
        user_key="7",
    )
    assert first["stderr"] == "", first["stderr"]

    second = run_isolated(
        isolated,
        "    with open('carried.txt') as f:\n"
        "        return f.read()\n",
        launch_dir=str(workspace),
        user_key="7",
    )

    assert second["stderr"] == "", second["stderr"]


def test_one_user_does_not_land_in_anothers_directory(isolated, workspace):
    """Separate directories.

    Not an OS-enforced boundary: every child runs as the same uid, so this
    keeps users' files apart by construction, not against a determined node.
    Session scoping in the parent is what actually separates their data.
    """
    run_isolated(
        isolated,
        "    with open('mine.txt', 'w') as f:\n"
        "        f.write('7')\n"
        "    return 'ok'\n",
        launch_dir=str(workspace),
        user_key="7",
    )
    other = run_isolated(
        isolated,
        "    import os\n"
        "    return os.path.exists('mine.txt')\n",
        launch_dir=str(workspace),
        user_key="8",
    )

    assert other["stderr"] == "", other["stderr"]
    assert other["output"]["dataType"] == "bool"


def test_an_editors_run_imports_the_owners_libraries_after_his_own(isolated, workspace, monkeypatch):
    """A run of an editor the dataflow's owner invited, as ``/exec`` takes it
    (``library_keys``, which the backend sends for such a run alone): the
    child imports a library only she installed from her folder, and one both
    installed from his own, which comes first. Her own run, and the run of an
    account she never invited, read their own folder alone."""
    import json

    from utk_curio.sandbox.app import api, app
    from utk_curio.sandbox.isolation import runner, supervisor
    from utk_curio.sandbox.util.parsers import _shared_data_dir

    monkeypatch.setattr(api, "_isolation_state", (runner.execute_isolated, isolated))
    installed = {"7": {"flood_lib": "hers", "tide_lib": "hers"}, "8": {"tide_lib": "his"}}
    for key, libraries in installed.items():
        folder = supervisor.user_overlay_dir(str(_shared_data_dir()), key)
        os.makedirs(folder, exist_ok=True)
        for name, whose in libraries.items():
            with open(os.path.join(folder, f"{name}.py"), "w") as f:
                f.write(f"WHOSE = {whose!r}\n")

    def imported(user_key, **body):
        resp = app.test_client().post("/exec", json={
            "code": (
                "    import importlib\n"
                "    found = []\n"
                "    for name in ('flood_lib', 'tide_lib'):\n"
                "        try:\n"
                "            found.append(name + '=' + importlib.import_module(name).WHOSE)\n"
                "        except ImportError:\n"
                "            found.append(name + '=none')\n"
                "    print(' '.join(found))\n"
                "    return 1\n"
            ),
            "file_path": "", "nodeType": "curio.builtin/python-computation", "dataType": "",
            "session_id": "session-editor-libraries", "save_dataset": False, "user_key": user_key, **body,
        })
        reply = json.loads(resp.get_data(as_text=True))
        resp.close()
        assert reply["stderr"] == "", reply["stderr"]
        return reply["stdout"]

    assert "flood_lib=hers tide_lib=his" in imported("8", library_keys=["7"])
    assert "flood_lib=hers tide_lib=hers" in imported("7")
    assert "flood_lib=none tide_lib=none" in imported("9")


# ---------------------------------------------------------------------------
# Escapes. The reason this work exists.
# ---------------------------------------------------------------------------

def test_the_user_database_is_unreachable(isolated_dropped, tmp_path):
    """instance/urban_workflow.db holds every password hash and session token.

    Uses the dropped-privilege fixture deliberately. Without an execution user
    the child runs as the sandbox's own user, and inside the container that is
    root, which ignores mode bits: the test would pass or fail for reasons that
    have nothing to do with the boundary.

    Asserts on the *artifact*, not on the response. An earlier version checked
    that the secret was absent from the response JSON, which it always is
    because a node's return value is stored and only its id comes back. That
    version passed no matter what the child could read.
    """
    secret = tmp_path / "urban_workflow.db"
    secret.write_text("SUPER SECRET", encoding="utf-8")
    os.chmod(secret, 0o600)
    os.chmod(tmp_path, 0o711)

    result = run_isolated(
        isolated_dropped, f"    return open({str(secret)!r}).read()\n"
    )

    if result["output"]["path"]:
        from utk_curio.sandbox.util.parsers import load_from_duckdb

        assert load_from_duckdb(result["output"]["path"]) != "SUPER SECRET", (
            "an isolated node read a root-owned 0600 file"
        )
    else:
        assert "Permission denied" in result["stderr"] or "Errno 13" in result["stderr"], (
            f"expected a permission error, got: {result['stderr'][:400]}"
        )


def test_the_artifact_store_is_unreachable(isolated_dropped):
    """Reading curio_data.duckdb directly would bypass session scoping entirely."""
    from utk_curio.sandbox.util.parsers import _shared_data_dir

    db = _shared_data_dir() / "curio_data.duckdb"
    os.chmod(db, 0o600)

    result = run_isolated(
        isolated_dropped, f"    return open({str(db)!r}, 'rb').read()[:4].hex()\n"
    )
    assert result["output"]["path"] == "", (
        f"an isolated node opened the DuckDB artifact store: {result['stderr'][:300]}"
    )
    assert "Permission denied" in result["stderr"] or "Errno 13" in result["stderr"], (
        f"expected a permission error, got: {result['stderr'][:400]}"
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
@pytest.mark.parametrize("family", ["AF_INET", "AF_INET6", "AF_NETLINK", "AF_PACKET"])
def test_a_socket_of_every_other_family_is_denied(isolated, family):
    """Only the local family, AF_UNIX, is open: every other reaches a network."""
    result = run_isolated(
        isolated,
        f"    import socket\n    return str(socket.socket(socket.{family}, socket.SOCK_DGRAM))\n",
    )
    assert result["output"]["path"] == "", f"an isolated node created an {family} socket"


@needs_seccomp
def test_a_local_socket_may_listen_but_never_connect_or_accept(isolated):
    """CUDA's driver binds and listens on a local socket when it starts, so a
    child may do that; but it may not connect a socket or accept on one, so no
    socket carries anything into or out of it."""
    result = run_isolated(
        isolated,
        "    import os\n"
        "    import socket\n"
        "    seen = {}\n"
        "    address = '\\0curio-isolation-probe-' + str(os.getpid())\n"
        "    listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)\n"
        "    listener.bind(address)\n"
        "    listener.listen(1)\n"
        "    listener.setblocking(False)\n"
        "    seen['listens'] = True\n"
        "    caller = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)\n"
        "    for name, call in (('connect', lambda: caller.connect(address)),\n"
        "                       ('accept', listener.accept)):\n"
        "        try:\n"
        "            call()\n"
        "            seen[name] = 'allowed'\n"
        "        except OSError as error:\n"
        "            seen[name] = type(error).__name__\n"
        "    return seen\n",
    )
    assert result["stderr"] == "", result["stderr"]

    from utk_curio.sandbox.util.parsers import load_from_duckdb

    assert load_from_duckdb(result["output"]["path"]) == {
        "listens": True, "connect": "PermissionError", "accept": "PermissionError",
    }


@needs_seccomp
def test_a_local_socket_does_not_reach_the_zygote(isolated_dropped):
    """The execution account makes a local socket, and cannot connect it to
    the zygote's."""
    result = run_isolated(
        isolated_dropped,
        "    import socket\n"
        "    local = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
        "    try:\n"
        f"        local.connect({os.environ['CURIO_EXEC_SOCKET']!r})\n"
        "    except PermissionError:\n"
        "        return 'refused'\n"
        "    return 'connected'\n",
    )
    assert result["stderr"] == "", result["stderr"]

    from utk_curio.sandbox.util.parsers import load_from_duckdb

    assert load_from_duckdb(result["output"]["path"]) == "refused", "a node reached the zygote"


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


#: Node code that tries each way out of its run's process group, each in a
#: fresh process of its own, so one that got out cannot spoil the next, and
#: returns what each got. The node's own process leads its group and its
#: session (``child.confine``), and the kernel refuses both calls to such a
#: process, so every try is made in a process the node starts.
_TRIES_TO_LEAVE_ITS_GROUP = r'''
    import os, subprocess
    run_group = os.getpgid(0)

    def tried(leave, double_fork=False):
        read_end, write_end = os.pipe()
        first = os.fork()
        if first == 0:
            try:
                os.close(read_end)
                if double_fork and os.fork() != 0:
                    os._exit(0)
                try:
                    leave()
                    outcome = "allowed"
                except OSError as error:
                    outcome = type(error).__name__
                where = "in" if os.getpgid(0) == run_group else "out of"
                os.write(write_end, f"{outcome}, {where} the run's group".encode())
            finally:
                os._exit(0)
        os.close(write_end)
        os.waitpid(first, 0)
        with os.fdopen(read_end, "rb") as reading:
            return reading.read().decode()

    seen = {
        "os.setsid() after a double fork": tried(os.setsid, double_fork=True),
        "os.setpgid(0, 0)": tried(lambda: os.setpgid(0, 0)),
        "os.setpgrp()": tried(os.setpgrp),
    }
    for keyword, value in (("start_new_session", True), ("process_group", 0)):
        try:
            subprocess.Popen(["true"], **{keyword: value}).wait()
            seen[f"Popen({keyword}={value})"] = "allowed"
        except OSError as error:
            seen[f"Popen({keyword}={value})"] = type(error).__name__
    return seen
'''


@needs_seccomp
def test_a_process_a_node_starts_cannot_leave_its_runs_process_group(isolated):
    """The zygote's deadline kill and the kill of a dead zygote's run reach a
    run's processes through its process group. A process the node started
    that left the group, as a daemon does with a double fork and ``setsid``,
    escaped both and ran on for nobody.

    Each way out must fail with PermissionError, and leave the process in the
    run's group: ``setsid`` in the grandchild of a double fork, ``setpgid``,
    glibc's ``setpgrp`` (``setpgid(0, 0)``), and ``subprocess.Popen`` asked
    for a session or a process group of its own.
    """
    result = run_isolated(isolated, _TRIES_TO_LEAVE_ITS_GROUP)
    assert result["output"]["path"], result["stderr"][:2000]

    from utk_curio.sandbox.util.parsers import load_from_duckdb

    seen = load_from_duckdb(result["output"]["path"])
    assert seen == {
        "os.setsid() after a double fork": "PermissionError, in the run's group",
        "os.setpgid(0, 0)": "PermissionError, in the run's group",
        "os.setpgrp()": "PermissionError, in the run's group",
        "Popen(start_new_session=True)": "PermissionError",
        "Popen(process_group=0)": "PermissionError",
    }, f"a process the node started could leave its run's process group: {seen}"


def test_the_child_actually_runs_as_the_execution_user(isolated_dropped):
    """The privilege drop is the foundation the filesystem tests rest on."""
    result = run_isolated(isolated_dropped, "    return os.getuid()\n")
    assert result["stderr"] == "", result["stderr"]

    from utk_curio.sandbox.util.parsers import load_from_duckdb

    assert load_from_duckdb(result["output"]["path"]) != 0, (
        "the child is still root, so no filesystem boundary exists"
    )


def test_regaining_privilege_is_denied(isolated_dropped):
    """setuid back to root must fail once privileges are dropped.

    Needs the dropped fixture: with no execution user the child runs as the
    sandbox's own user, which inside the container is root, and setuid(0)
    trivially succeeds. That is correct behaviour for that configuration, not a
    boundary failure, so asserting it there tested nothing.
    """
    result = run_isolated(isolated_dropped, "    os.setuid(0)\n    return 'root'\n")
    assert result["output"]["path"] == "", "an isolated node became root"


def test_writing_outside_the_scratch_directory_is_denied(isolated_dropped, tmp_path):
    target = tmp_path / "should-not-exist.txt"
    os.chmod(tmp_path, 0o700)  # root-owned, so the exec user cannot write here
    result = run_isolated(
        isolated_dropped,
        f"    open({str(target)!r}, 'w').write('x')\n    return 1\n",
    )
    assert not target.exists(), "an isolated node wrote outside its scratch dir"
    assert result["output"]["path"] == "", result["stderr"][:300]


def test_the_child_can_write_inside_its_own_scratch_directory(isolated_dropped):
    """The other half: confinement must not break legitimate work.

    A node that writes a temporary file in its working directory is ordinary,
    and the dropped uid owns its scratch dir precisely so that keeps working.
    """
    result = run_isolated(
        isolated_dropped,
        "    open('scratch-probe.txt', 'w').write('ok')\n"
        "    return open('scratch-probe.txt').read()\n",
    )
    assert result["stderr"] == "", result["stderr"]

    from utk_curio.sandbox.util.parsers import load_from_duckdb

    assert load_from_duckdb(result["output"]["path"]) == "ok"


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
    headroom = isolated.limits["memory_mb"] * 1024 * 1024

    # RLIMIT_AS is the interpreter's own footprint plus the configured budget
    # (child._apply_rlimits), so it must exceed the budget but stay sane. An
    # equality check here is what previously hid the fact that the cap was
    # below the interpreter's baseline, which made every allocation fail and
    # the runaway-allocation test pass for the wrong reason.
    assert limits["as"] != resource_unlimited(), "RLIMIT_AS was not applied"
    assert limits["as"] > headroom, limits
    assert limits["as"] < headroom + (8 << 30), (
        f"RLIMIT_AS looks like it lost the budget: {limits}"
    )

    assert limits["cpu"] == isolated.limits["cpu_seconds"], limits
    assert limits["nproc"] == isolated.limits["nproc"], limits
    assert limits["core"] == 0, limits


#: Burns CPU on every CPU this process may use, with threads that release the
#: GIL (hashlib does for large buffers), until it has spent CPU_GOAL seconds
#: of CPU time or WALL_CAP seconds of wall time.
_BURN_EVERY_CPU = r'''
    import hashlib, os, resource, threading, time
    block = os.urandom(1 << 20)
    start = time.monotonic()
    def cpu():
        ru = resource.getrusage(resource.RUSAGE_SELF)
        return ru.ru_utime + ru.ru_stime
    def burn():
        while cpu() < CPU_GOAL and time.monotonic() - start < WALL_CAP:
            for _ in range(64):
                hashlib.sha256(block).digest()
    threads = [threading.Thread(target=burn) for _ in os.sched_getaffinity(0)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return {"cpu": cpu(), "wall": time.monotonic() - start, "threads": len(threads)}
'''


def test_a_node_may_spend_more_cpu_time_than_its_wall_allowance(isolated):
    """A node busy on every CPU for half its wall allowance must finish.

    RLIMIT_CPU counts every thread, and it was set to the wall allowance, so
    a node whose library runs a thread per core was killed long before its
    wall clock ran out: example 10's Image Segmentation spent its 300 CPU-
    seconds in 9 s on the 64-CPU deploy host. The kill was a SIGKILL, which
    the node then reported as the memory limit.
    """
    if len(os.sched_getaffinity(0)) < 2:
        pytest.skip("needs at least two CPUs to spend CPU time faster than wall time")
    wall_allowance = isolated.wall_timeout
    code = (_BURN_EVERY_CPU
            .replace("CPU_GOAL", str(1.5 * wall_allowance))
            .replace("WALL_CAP", str(0.75 * wall_allowance)))
    result = run_isolated(isolated, code)
    assert result["stderr"] == "", result["stderr"]

    from utk_curio.sandbox.util.parsers import load_from_duckdb

    spent = load_from_duckdb(result["output"]["path"])
    # The claim is only made when the node really outran the wall clock.
    assert spent["cpu"] > wall_allowance, spent
    assert spent["wall"] < wall_allowance, spent


def test_a_node_past_its_cpu_allowance_is_told_so(isolated):
    """The kernel warns at the soft limit and kills at the hard one.

    With the two equal, its first signal was SIGKILL, which the node reported
    as the memory limit. With the hard limit above the soft one, SIGXCPU
    comes first, and the node says which allowance it ran out of.
    """
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    probe = run_isolated(
        isolated,
        "    import resource\n"
        "    return list(resource.getrlimit(resource.RLIMIT_CPU))\n",
    )
    assert probe["stderr"] == "", probe["stderr"]
    soft, hard = load_from_duckdb(probe["output"]["path"])
    assert soft == isolated.limits["cpu_seconds"], (soft, hard)
    assert hard > soft, f"RLIMIT_CPU soft {soft} and hard {hard}: the first signal is SIGKILL"

    # And SIGXCPU reaches the node's message: a node that lowers its own soft
    # limit (always allowed) and then burns past it is told about CPU time.
    burn = (
        "    import resource\n"
        "    soft, hard = resource.getrlimit(resource.RLIMIT_CPU)\n"
        "    resource.setrlimit(resource.RLIMIT_CPU, (1, hard))\n"
        "    while True:\n"
        "        pass\n"
    )
    result = run_isolated(isolated, burn)
    assert result["output"]["path"] == ""
    assert "CPU allowance" in result["stderr"], result["stderr"]
    assert "memory" not in result["stderr"], result["stderr"]


def resource_unlimited():
    import resource

    return resource.RLIM_INFINITY


@pytest.mark.parametrize("isolated", [128, 256, 1024], indirect=True)
def test_a_dataframe_writes_parquet_under_the_memory_cap(isolated):
    """#334's actual failure mode, exercised rather than approximated (#358).

    Writing three integers to parquet used to fail with "Failed to allocate
    block of 32768 bytes" inside the isolated child: ``codec`` opened DuckDB
    with its defaults - ``threads`` = host cores, ``memory_limit`` ~80% of
    system RAM - and DuckDB sized its buffers against the HOST while the child
    ran under an RLIMIT_AS cap. On a many-core CI runner that was enough to
    exhaust the cap before any data was written.

    ``test_codec.py::TestParquetWriterFootprint`` verifies the fix by spying on
    the kwargs handed to ``duckdb.connect`` and asserting the two literals. That
    cannot catch a regression that breaks the cap/DuckDB interaction for any
    other reason - a new extension, a different default, a change to how the
    child computes its budget - because it never runs the writer under a cap at
    all. This does: real zygote, real RLIMIT_AS, real parquet write.

    Deliberately a tiny frame. The claim is not "big frames fit", it is "the
    writer's own footprint fits", which is what #334 broke.

    Runs at 256MB, the fixture's default budget, and at 128 and 1024MB on
    either side of it. Deriving the writer's limit is what moved the 256 case
    off the boundary it used to sit on: 256 was both the fixture's budget and
    the writer's fixed ``memory_limit``, so the test could not distinguish a
    writer sized against the child's budget from one that ignores it. The
    writer now gets 128MB at 256, so it can; it gets 64MB at 128 and reaches
    its 256MB cap at 1024.

    128 and 1024 are #376's budgets, and the sizes of mimalloc's two arenas.
    While mimalloc, pyarrow's default pool, served the child, both failed here
    with an ArrowMemoryError in user code, before serialization, and 256
    passed: pandas builds even the column labels as Arrow strings, and the
    first allocation reserved an arena that fit under the cap but left no room
    for the page map mimalloc extends next. Under a cap the zygote now gives
    Arrow glibc's allocator (``lifecycle.zygote_environment``).
    ``--exec-memory-mb`` is an operator's knob with a floor of 64, so a tiny
    frame has to fit at budgets other than this suite's default. The probe
    below proves the cap itself is applied at each budget, so a failure past
    it is downstream of ``_apply_rlimits``.
    """
    # Read the cap the child is actually running under FIRST, so a failure
    # below comes with the numbers rather than just a traceback. An
    # ArrowMemoryError here is indistinguishable between "the budget is too
    # small" and "the cap is not what the budget says", and those want
    # opposite fixes.
    probe = run_isolated(
        isolated,
        "    import os, resource\n"
        "    from utk_curio.sandbox.util import codec\n"
        "    with open('/proc/self/statm') as h:\n"
        "        pages = int(h.read().split()[0])\n"
        "    return {\n"
        "        'as_mb': resource.getrlimit(resource.RLIMIT_AS)[0] // (1024 * 1024),\n"
        "        'baseline_mb': (pages * os.sysconf('SC_PAGE_SIZE')) // (1024 * 1024),\n"
        "        'budget_env': os.environ.get('CURIO_EXEC_MEMORY_MB', '<unset>'),\n"
        "        'writer': codec._writer_config()['memory_limit'],\n"
        "    }\n",
    )
    assert probe["stderr"] == "", probe["stderr"]

    from utk_curio.sandbox.util.parsers import load_from_duckdb

    seen = load_from_duckdb(probe["output"]["path"])
    diagnostics = (
        f"budget={isolated.limits['memory_mb']}MB env={seen['budget_env']} "
        f"RLIMIT_AS={seen['as_mb']}MB baseline={seen['baseline_mb']}MB "
        f"writer={seen['writer']}"
    )
    # The cap has to be the baseline plus the budget, within a page or two of
    # drift between the two reads. If this is wrong, nothing below means
    # anything.
    expected_as = seen["baseline_mb"] + isolated.limits["memory_mb"]
    assert abs(seen["as_mb"] - expected_as) <= 8, diagnostics

    result = run_isolated(
        isolated,
        "    import pandas as pd\n"
        "    return pd.DataFrame({'a': [1, 2, 3], 'b': ['x', 'y', 'z']})\n",
    )
    assert result["stderr"] == "", f"{diagnostics}\n{result['stderr']}"
    assert result["output"]["path"], f"the writer produced no artifact ({diagnostics})"

    frame = load_from_duckdb(result["output"]["path"])
    # Round-tripped, not merely written: a truncated file would still exist.
    assert len(frame["a"]) == 3, frame
    assert list(frame["a"]) == [1, 2, 3], frame


def test_the_writer_tracks_a_lowered_budget_into_the_child(isolated):
    """The writer's limit follows ``--exec-memory-mb`` down.

    While it was a module constant it did not. An operator lowering the budget
    to fit more parallelism on a small host - which USAGE.md invites - left
    DuckDB sizing its buffers against 256MB inside a child that had less, which
    is #334's shape with the host swapped for a stale constant.

    The fixture's default budget is the launcher's floor, and the writer
    derives 128MB from it, so this runs where the derivation is what decides
    the number rather than the cap.

    Read from inside the child, so what is asserted is the value DuckDB
    actually adopted under the cap, not what the parent computed.
    """
    from utk_curio.sandbox.util import codec
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    budget_mb = isolated.limits["memory_mb"]
    expected_mb = codec._writer_memory_limit_mb(
        {"CURIO_EXEC_MEMORY_MB": str(budget_mb)}
    )
    assert expected_mb < codec._WRITER_MEMORY_CAP_MB, (
        "this budget does not exercise the derivation - it is still capped"
    )

    result = run_isolated(
        isolated,
        "    import duckdb\n"
        "    from utk_curio.sandbox.util import codec\n"
        "    con = duckdb.connect(database=':memory:', config=codec._writer_config())\n"
        "    try:\n"
        "        value = con.execute(\n"
        "            \"SELECT value FROM duckdb_settings() WHERE name = 'memory_limit'\"\n"
        "        ).fetchone()[0]\n"
        "    finally:\n"
        "        con.close()\n"
        "    return str(value)\n",
    )
    assert result["stderr"] == "", result["stderr"]

    adopted = load_from_duckdb(result["output"]["path"])
    got = _memory_bytes(adopted)
    want = expected_mb * 10 ** 6
    assert abs(got - want) / want < 0.02, (
        f"the child adopted {adopted!r} against a {budget_mb}MB budget, not "
        f"the derived {expected_mb}MB"
    )

    # And it is genuinely below the child's own budget, which is the invariant
    # #334 broke. A derivation that tracked the budget upward but not downward
    # would satisfy the comparison above and still fail here.
    assert expected_mb <= budget_mb // 2, (expected_mb, budget_mb)


def test_the_writer_is_configured_for_a_capped_child(isolated):
    """The other half of #334, read from INSIDE the child.

    ``test_codec.py`` asserts the two values in the parent process, where the
    cap does not apply. This reads the values DuckDB actually adopted in the
    child, so a config that is silently ignored under RLIMIT_AS - or overridden
    by an environment variable the child inherits - shows up here.
    """
    result = run_isolated(
        isolated,
        "    import duckdb\n"
        "    from utk_curio.sandbox.util import codec\n"
        "    con = duckdb.connect(database=':memory:', config=codec._writer_config())\n"
        "    try:\n"
        "        rows = con.execute(\n"
        "            \"SELECT name, value FROM duckdb_settings() \"\n"
        "            \"WHERE name IN ('threads', 'memory_limit')\"\n"
        "        ).fetchall()\n"
        "    finally:\n"
        "        con.close()\n"
        "    return {name: str(value) for name, value in rows}\n",
    )
    assert result["stderr"] == "", result["stderr"]

    from utk_curio.sandbox.util.parsers import load_from_duckdb

    settings = load_from_duckdb(result["output"]["path"])
    adopted = dict(zip(settings["name"], settings["value"])) if "name" in settings else settings
    assert str(adopted.get("threads")) == "1", adopted

    # Compare the MAGNITUDE, derived from the writer's own config rather than
    # from a literal, or this test pins a formatting detail instead of a
    # budget. The config is computed against the same budget the child runs
    # under, so this stays true at whatever budget the fixture was given.
    from utk_curio.sandbox.util import codec

    want_config = codec._writer_config(
        {"CURIO_EXEC_MEMORY_MB": str(isolated.limits["memory_mb"])}
    )
    want = _memory_bytes(want_config["memory_limit"])
    got = _memory_bytes(adopted.get("memory_limit"))
    assert abs(got - want) / want < 0.02, (
        f"the child adopted {adopted.get('memory_limit')!r}, which is not the "
        f"configured {want_config['memory_limit']!r}"
    )


#: glibc's own arena limit on a 64-core host, eight per core. Handed to the
#: zygote, which the children inherit it from, so a four-core runner allows
#: what a deployment's host does; ``lifecycle.zygote_environment`` lowers it
#: to the budget's cap.
MANY_CORE_ARENA_MAX = 8 * 64


def test_the_zygote_starts_with_the_budgets_arena_cap():
    """The cap is in the zygote's environment, where glibc reads it first.

    16 arenas at the default 4096 MB, a quarter of the budget at 64 MiB each;
    an operator's lower ``MALLOC_ARENA_MAX`` stands, and with no memory cap
    the environment is left as it is.
    """
    from utk_curio.sandbox.isolation import lifecycle

    assert lifecycle.zygote_environment({"memory_mb": 4096}, {})["MALLOC_ARENA_MAX"] == "16"
    assert lifecycle.zygote_environment({"memory_mb": 256}, {})["MALLOC_ARENA_MAX"] == "2"
    many = {"MALLOC_ARENA_MAX": str(MANY_CORE_ARENA_MAX), "PATH": "/bin"}
    env = lifecycle.zygote_environment({"memory_mb": 4096}, many)
    assert env == {"MALLOC_ARENA_MAX": "16", "ARROW_DEFAULT_MEMORY_POOL": "system", "PATH": "/bin"}
    lower = lifecycle.zygote_environment({"memory_mb": 4096}, {"MALLOC_ARENA_MAX": "4"})
    assert lower["MALLOC_ARENA_MAX"] == "4"
    assert lifecycle.zygote_environment({"memory_mb": None}, {"PATH": "/bin"}) == {"PATH": "/bin"}


def test_a_capped_zygote_gives_arrow_the_system_allocator():
    """Under a cap Arrow allocates through glibc, whatever pool was inherited (#376).

    mimalloc, pyarrow's default, reserves a 1 GiB or 128 MiB arena of address
    space on a child's first Arrow allocation, and RLIMIT_AS counts all of it.
    Arrow reads the pool's name once, when it is loaded, so the name goes into
    the zygote's environment and an inherited one does not stand. With no cap
    the environment is left as it is.
    """
    from utk_curio.sandbox.isolation import lifecycle

    for budget in (64, 128, 1024, 4096):
        env = lifecycle.zygote_environment({"memory_mb": budget}, {})
        assert env["ARROW_DEFAULT_MEMORY_POOL"] == "system", (budget, env)
    inherited = {"ARROW_DEFAULT_MEMORY_POOL": "mimalloc"}
    env = lifecycle.zygote_environment({"memory_mb": 1024}, inherited)
    assert env["ARROW_DEFAULT_MEMORY_POOL"] == "system"
    assert lifecycle.zygote_environment({"memory_mb": None}, inherited) == inherited


def test_arrow_allocates_through_glibc_in_a_capped_child(isolated):
    """The pool the zygote's environment names is the one a child's Arrow uses.

    Read inside the child, after the zygote loaded pyarrow and forked. Were
    pyarrow to stop reading ``ARROW_DEFAULT_MEMORY_POOL``, the budget test
    would only show #376's ArrowMemoryError again; this names the cause.
    """
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    result = run_isolated(
        isolated,
        "    import pyarrow as pa\n"
        "    return pa.default_memory_pool().backend_name\n",
    )
    assert result["stderr"] == "", result["stderr"]
    assert load_from_duckdb(result["output"]["path"]) == "system"


@pytest.fixture
def isolated_deployed(request, workspace, monkeypatch):
    """A zygote at the budget and wall allowance a deployment runs with.

    Parametrize indirectly with ``"many-core"`` to give it a 64-core host's
    malloc arena limit (``MANY_CORE_ARENA_MAX``).
    """
    from utk_curio.sandbox.isolation import lifecycle, runner, supervisor

    if getattr(request, "param", None) == "many-core":
        monkeypatch.setenv("MALLOC_ARENA_MAX", str(MANY_CORE_ARENA_MAX))
    monkeypatch.setenv("CURIO_EXEC_SOCKET", str(workspace / "zygote.sock"))
    monkeypatch.setenv("CURIO_EXEC_TIMEOUT", str(supervisor.DEFAULT_WALL_TIMEOUT_SECONDS))
    monkeypatch.setenv("CURIO_EXEC_MEMORY_MB", str(supervisor.DEFAULT_LIMITS["memory_mb"]))
    config = runner.IsolationConfig.from_environment()
    lifecycle.ensure_running(config, exec_user=None, require_seccomp=HAS_PYSECCOMP)
    try:
        yield config
    finally:
        lifecycle.shutdown()


#: Starts *threads* threads that each malloc and stay alive, then counts the
#: process's malloc arenas from glibc's own report (one ``<heap nr=...>`` each).
_COUNT_MALLOC_ARENAS = r'''
    import ctypes, os, re, tempfile, threading
    libc = ctypes.CDLL("libc.so.6")
    libc.malloc.restype = ctypes.c_void_p
    libc.malloc.argtypes = [ctypes.c_size_t]
    libc.free.argtypes = [ctypes.c_void_p]
    libc.fopen.restype = ctypes.c_void_p
    libc.fopen.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    libc.fclose.argtypes = [ctypes.c_void_p]
    libc.malloc_info.argtypes = [ctypes.c_int, ctypes.c_void_p]
    ready = threading.Barrier(THREADS + 1)
    done = threading.Event()
    def work():
        block = libc.malloc(4096)
        ready.wait()
        done.wait()
        libc.free(block)
    threads = [threading.Thread(target=work) for _ in range(THREADS)]
    for thread in threads:
        thread.start()
    ready.wait()
    path = os.path.join(tempfile.mkdtemp(), "arenas.xml")
    handle = libc.fopen(path.encode(), b"w")
    libc.malloc_info(0, handle)
    libc.fclose(handle)
    done.set()
    for thread in threads:
        thread.join()
    with open(path, encoding="utf-8") as fh:
        report = fh.read()
    return {"arenas": len(re.findall(r"<heap nr=", report)), "cpus": os.cpu_count()}
'''


@pytest.mark.parametrize("isolated_deployed", ["many-core"], indirect=True)
def test_threads_share_a_bounded_number_of_malloc_arenas(isolated_deployed):
    """However many threads a node's libraries start, the arenas are capped.

    glibc gives each thread that mallocs an arena of its own, up to eight per
    core, and each reserves 64 MiB of the address space RLIMIT_AS counts.
    Counted from glibc's own ``malloc_info`` rather than inferred from VmSize,
    with twice the cap's threads alive at once.
    """
    from utk_curio.sandbox.isolation import lifecycle
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    cap = lifecycle.malloc_arena_cap(isolated_deployed.limits["memory_mb"])
    threads = max(64, 2 * cap)
    result = run_isolated(
        isolated_deployed, _COUNT_MALLOC_ARENAS.replace("THREADS", str(threads))
    )
    assert result["stderr"] == "", result["stderr"]
    seen = load_from_duckdb(result["output"]["path"])
    assert seen["arenas"] <= cap, (
        f"{threads} threads made {seen['arenas']} malloc arenas on {seen['cpus']} "
        f"cores, above the cap of {cap} for a "
        f"{isolated_deployed.limits['memory_mb']}MB budget"
    )


DDRNET = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
    "packages", "model.curio.ddrnet23-slim@1",
)

#: Example 10's shipped model, DDRNet23-Slim's model package, run once at its
#: own input size with *THREADS* intra-op threads, as ``curio_segment`` runs it.
_RUN_DDRNET = r'''
    import json, os
    import numpy as np
    import onnxruntime as ort
    folder = curio_load_model("model.curio.ddrnet23-slim").folder
    with open(os.path.join(folder, "manifest.json"), encoding="utf-8") as fh:
        block = json.load(fh)["model"]
    options = ort.SessionOptions()
    options.intra_op_num_threads = THREADS
    session = ort.InferenceSession(
        os.path.join(folder, block["entry"]), sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    size = block["input"]
    pixels = np.zeros((1, 3, int(size["height"]), int(size["width"])), dtype=np.uint8)
    scores = session.run(None, {session.get_inputs()[0].name: pixels})[0]
    return "x".join(str(n) for n in scores.shape)
'''


@pytest.mark.parametrize("isolated_deployed", ["many-core"], indirect=True)
def test_the_street_vision_model_runs_on_a_many_core_host(isolated_deployed):
    """Example 10's Image Segmentation, DDRNet23-Slim's node, at the default
    budget, on 64 cores.

    onnxruntime starts a thread per physical core, and each took a malloc
    arena of its own: at 64 threads the session reserved the whole budget and
    failed at creation with ``std::bad_alloc``. On a deployment the same run
    failed on a model buffer (``BFCArena ... Failed to allocate memory for
    requested buffer of size 67108864``). The threads are the library's own
    choice and stay as they are; the cap on arenas is what keeps them inside
    the budget.
    """
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    result = run_isolated(
        isolated_deployed,
        _RUN_DDRNET.replace("THREADS", "64"),
        models={"model.curio.ddrnet23-slim": os.path.abspath(DDRNET)},
    )
    assert result["stderr"] == "", result["stderr"][-2000:]
    # 19 Cityscapes classes over the model's 128x256 output grid.
    assert load_from_duckdb(result["output"]["path"]) == "1x19x128x256"


#: Intra-op threads for the session below, set explicitly so the test does not
#: depend on the runner's cores. At the 8 MiB stack glibc derives from
#: RLIMIT_STACK, 512 stacks reserve 4 GiB, the whole default budget, before
#: the model's own memory.
MANY_THREADS = 512

#: Example 10's model with *THREADS* intra-op threads, reporting what the child
#: reserved instead of raising, so a failure carries the numbers. Spinning is
#: off so that the threads wait rather than spin on a runner with a few CPUs;
#: it does not change how many there are.
_RUN_DDRNET_REPORTING = r'''
    import ctypes, json, os, resource
    import numpy as np
    import onnxruntime as ort

    def vm_mb():
        with open("/proc/self/status", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("VmSize:"):
                    return int(line.split()[1]) // 1024
        return -1

    def kib(limit):
        return -1 if limit == resource.RLIM_INFINITY else limit // 1024

    libc = ctypes.CDLL(None)
    attr = ctypes.create_string_buffer(128)
    libc.pthread_getattr_default_np(attr)
    stack = ctypes.c_size_t()
    libc.pthread_attr_getstacksize(attr, ctypes.byref(stack))
    libc.pthread_attr_destroy(attr)
    seen = {
        "as_limit_mb": kib(resource.getrlimit(resource.RLIMIT_AS)[0]) // 1024,
        "rlimit_stack_kib": kib(resource.getrlimit(resource.RLIMIT_STACK)[0]),
        "thread_stack_kib": stack.value // 1024,
        "vm_before_mb": vm_mb(),
        "error": "",
        "shape": "",
    }
    folder = curio_load_model("model.curio.ddrnet23-slim").folder
    with open(os.path.join(folder, "manifest.json"), encoding="utf-8") as fh:
        block = json.load(fh)["model"]
    options = ort.SessionOptions()
    options.intra_op_num_threads = THREADS
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    session = None
    try:
        session = ort.InferenceSession(
            os.path.join(folder, block["entry"]), sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        size = block["input"]
        pixels = np.zeros((1, 3, int(size["height"]), int(size["width"])), dtype=np.uint8)
        scores = session.run(None, {session.get_inputs()[0].name: pixels})[0]
        seen["shape"] = "x".join(str(n) for n in scores.shape)
    except Exception as exc:
        seen["error"] = f"{type(exc).__name__}: {exc}"[:600]
    seen["threads"] = len(os.listdir("/proc/self/task"))
    seen["vm_after_mb"] = vm_mb()
    return seen
'''


@pytest.mark.parametrize("isolated_deployed", ["many-core"], indirect=True)
def test_an_onnx_session_starts_all_its_threads_inside_the_budget(isolated_deployed):
    """#743: an ONNX session with a thread per core, on any host size.

    onnxruntime starts an intra-op thread per physical core, and RLIMIT_AS
    counts each thread's whole stack. On CI's 192-CPU runners the stacks
    reserved about 1.5 GiB of the budget and the session failed to start with
    ``Resource temporarily unavailable``. Every thread asked for must start,
    at the default budget, with the model running to its output.
    """
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    result = run_isolated(
        isolated_deployed,
        _RUN_DDRNET_REPORTING.replace("THREADS", str(MANY_THREADS)),
        models={"model.curio.ddrnet23-slim": os.path.abspath(DDRNET)},
    )
    assert result["stderr"] == "", result["stderr"][-2000:]
    seen = load_from_duckdb(result["output"]["path"])
    numbers = (
        f"budget={isolated_deployed.limits['memory_mb']}MB "
        + " ".join(f"{key}={seen[key]}" for key in sorted(seen) if key != "error")
    )
    assert seen["error"] == "", f"{seen['error']} ({numbers})"
    assert seen["shape"] == "1x19x128x256", numbers
    # The main thread plus the pool's workers: no thread was given up.
    assert seen["threads"] >= MANY_THREADS, numbers


#: Measures the stack of a Python thread from inside it, with glibc's own
#: report of the thread's stack.
_PYTHON_THREAD_STACK = r'''
import ctypes, threading

def python_thread_stack_kib():
    libc = ctypes.CDLL(None)
    libc.pthread_self.restype = ctypes.c_ulong
    seen = {}

    def measure():
        attr = ctypes.create_string_buffer(128)
        libc.pthread_getattr_np(ctypes.c_ulong(libc.pthread_self()), attr)
        base, size = ctypes.c_void_p(), ctypes.c_size_t()
        libc.pthread_attr_getstack(attr, ctypes.byref(base), ctypes.byref(size))
        libc.pthread_attr_destroy(attr)
        seen["kib"] = size.value // 1024

    thread = threading.Thread(target=measure)
    thread.start()
    thread.join()
    return seen["kib"]
'''


def test_python_threads_keep_their_stack_in_a_capped_child(isolated_deployed):
    """A capped child gives library threads a smaller default stack (#743),
    and Python's own threads keep the one they have in process, so deep
    recursion in a ``threading`` or ``concurrent.futures`` thread behaves as
    it does without isolation."""
    import textwrap

    from utk_curio.sandbox.util.parsers import load_from_duckdb

    in_process = {}
    exec(_PYTHON_THREAD_STACK, in_process)
    want = in_process["python_thread_stack_kib"]()

    result = run_isolated(
        isolated_deployed,
        textwrap.indent(_PYTHON_THREAD_STACK, "    ")
        + "    return {'kib': python_thread_stack_kib()}\n",
    )
    assert result["stderr"] == "", result["stderr"][-2000:]
    got = load_from_duckdb(result["output"]["path"])["kib"]
    assert got >= want, (
        f"a Python thread has a {got} KiB stack in a capped child and {want} KiB in process"
    )


def test_a_runaway_allocation_hits_the_memory_limit(isolated):
    """RLIMIT_AS turns this into a MemoryError instead of an OOM kill.

    The distinction matters on a shared host: the OOM killer picks its own
    victim, which could be the backend or a neighbouring production container
    rather than the offending node.

    Allocates 512MB against a 256MB cap, deliberately modest. If the limit were
    not applied, a multi-gigabyte allocation here would put real memory pressure
    on the host that also runs the live instances.
    """
    # Derived from the configured headroom so the two cannot drift apart: if
    # someone raises the fixture's budget above this allocation, the test would
    # silently start asserting that a legal allocation fails.
    over_budget_mb = 2 * isolated.limits["memory_mb"]
    result = run_isolated(
        isolated,
        f"    x = bytearray({over_budget_mb} * 1024 * 1024)\n    return len(x)\n",
    )
    assert result["output"]["path"] == ""
    assert result["stderr"], "a memory failure produced no explanation"
    # And specifically a memory failure, not a crash: a SIGSEGV here would mean
    # the child died for an unrelated reason and this test proved nothing.
    assert "signal" not in result["stderr"].lower(), result["stderr"][:300]


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


def test_a_spawned_grandchild_does_not_survive_the_timeout(isolated, workspace):
    """proc.kill() on the child alone would leave this running.

    The child calls setsid and the zygote kills the whole process group, which
    is the only way to be sure. The zygote does the killing rather than the
    sandbox because it is the child's parent, so the pid cannot have been
    recycled underneath it.

    The node starts ``sleep`` itself and names its pid. Launched as
    ``sh -c 'exec -a <marker> sleep 300'``, it could not start: the image's
    ``/bin/sh`` is dash, whose ``exec`` takes no options (dash(1)), so the
    test found no process with the marker whatever the kill reached.
    """
    pid_file = workspace / "grandchild.pid"
    result = run_isolated(
        isolated, _starts_a_process(pid_file, then="    while True:\n        pass\n")
    )
    assert pid_file.exists(), f"the node never started its process: {result['stderr'][:300]}"
    grandchild = int(pid_file.read_text())
    give_up = time.monotonic() + 5
    while _alive(grandchild) and time.monotonic() < give_up:
        time.sleep(0.05)
    assert not _alive(grandchild), f"grandchild {grandchild} outlived the killed node"


#: A process that tries to leave its run's process group, as a daemon does,
#: and runs on whatever it got: it names its pid and what it got in the file
#: ``argv[1]`` names, then sleeps for two minutes. ``argv[2]`` is the run's
#: group. Written beside the file, then renamed, so a reader never sees half.
_TRIES_TO_LEAVE_THEN_SLEEPS = r'''
import os, sys, time
try:
    os.setsid()
    outcome = "allowed"
except OSError as error:
    outcome = type(error).__name__
where = "in" if os.getpgid(0) == int(sys.argv[2]) else "out of"
with open(sys.argv[1] + ".part", "w") as handle:
    handle.write(f"{os.getpid()} {outcome}, {where} the run's group")
os.replace(sys.argv[1] + ".part", sys.argv[1])
time.sleep(120)
'''


@needs_seccomp
def test_a_process_that_tried_to_leave_its_run_dies_at_the_deadline(isolated, workspace):
    """A process the node starts tries to leave its run's process group and
    sleeps for two minutes; the node waits for its report, then sleeps past
    its deadline. At the deadline the zygote kills the run's group, so that
    process must die with the node. One that got out ran on for nobody."""
    import copy
    import signal

    # Short, to keep the test quick, and long enough that the process has
    # reported before the deadline comes.
    config = copy.copy(isolated)
    config.wall_timeout = 10
    report = workspace / "leaver.txt"
    code = (
        "    import os, subprocess, sys, time\n"
        f"    subprocess.Popen([sys.executable, '-c', {_TRIES_TO_LEAVE_THEN_SLEEPS!r},\n"
        f"                      {str(report)!r}, str(os.getpgid(0))])\n"
        f"    while not os.path.exists({str(report)!r}):\n"
        "        time.sleep(0.05)\n"
        "    time.sleep(120)\n"
        "    return 1\n"
    )
    result = run_isolated(config, code)
    assert report.exists(), (
        f"the process the node started never reported: {result['stderr'][:300]}"
    )
    pid_text, got = report.read_text().split(" ", 1)
    pid = int(pid_text)
    try:
        assert "stopped after" in result["stderr"], result["stderr"][:300]
        give_up = time.monotonic() + 5
        while _alive(pid) and time.monotonic() < give_up:
            time.sleep(0.05)
        assert not _alive(pid), (
            f"process {pid}, which the node started, outlived its run's "
            f"{config.wall_timeout}s deadline; its os.setsid() was {got}"
        )
    finally:
        if _alive(pid):
            os.kill(pid, signal.SIGKILL)


# ---------------------------------------------------------------------------
# Every process a node starts ends when the node does
# ---------------------------------------------------------------------------

#: A process that closes its input and output, then sleeps for two minutes.
_CLOSES_ITS_OUTPUT = "import os, time\nos.closerange(0, 3)\ntime.sleep(120)\n"

#: A process that tries to leave its run's process group, writes what it got,
#: closes its output, then sleeps for two minutes.
_TRIES_TO_LEAVE_AND_SAYS = r'''
import os, time
try:
    os.setsid()
    outcome = "allowed"
except OSError as error:
    outcome = type(error).__name__
os.write(1, outcome.encode())
os.close(1)
time.sleep(120)
'''


def _starts_every_kind_of_process(record_file, then):
    """Node code that starts a process of every kind, each meant to sleep for
    two minutes, then runs *then*:

    - a ``subprocess.Popen``;
    - the grandchild of a double fork;
    - a ``multiprocessing.Process``, forked;
    - a process that closed its output, which looks finished to anything
      that waits for its output to end;
    - a process that tried to leave the run's process group.

    Before *then*, it writes to *record_file*, as JSON, each one's pid by kind
    and whether each was running then, so a process that never ran cannot
    pass for one that was stopped. It reads the last two's output to its end
    before it starts the next, so each has done what it says by then.
    """
    part = f"{record_file}.part"
    return (
        "    import json, multiprocessing, os, subprocess, sys, time\n"
        "    started = {'subprocess.Popen': subprocess.Popen(['sleep', '120']).pid}\n"
        "    read_end, write_end = os.pipe()\n"
        "    first = os.fork()\n"
        "    if first == 0:\n"
        "        try:\n"
        "            os.close(read_end)\n"
        "            if os.fork() == 0:\n"
        "                os.write(write_end, str(os.getpid()).encode())\n"
        "                os.close(write_end)\n"
        "                time.sleep(120)\n"
        "        finally:\n"
        "            os._exit(0)\n"
        "    os.close(write_end)\n"
        "    os.waitpid(first, 0)\n"
        "    with os.fdopen(read_end, 'rb') as reading:\n"
        "        started['the grandchild of a double fork'] = int(reading.read())\n"
        "    forked = multiprocessing.get_context('fork').Process(target=time.sleep, args=(120,))\n"
        "    forked.start()\n"
        "    started['multiprocessing.Process'] = forked.pid\n"
        "    python = [sys.executable, '-I', '-S', '-c']\n"
        f"    quiet = subprocess.Popen(python + [{_CLOSES_ITS_OUTPUT!r}],\n"
        "                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)\n"
        "    quiet.stdout.read()\n"
        "    quiet.stderr.read()\n"
        "    started['a process that closed its output'] = quiet.pid\n"
        f"    leaver = subprocess.Popen(python + [{_TRIES_TO_LEAVE_AND_SAYS!r}],\n"
        "                              stdout=subprocess.PIPE)\n"
        "    tried = leaver.stdout.read().decode()\n"
        "    started['a process that tried to leave its group (' + tried + ')'] = leaver.pid\n"
        "    def running(pid):\n"
        "        try:\n"
        "            with open('/proc/%d/status' % pid) as status:\n"
        "                states = [line.split()[1] for line in status if line.startswith('State:')]\n"
        "        except OSError:\n"
        "            return False\n"
        "        return bool(states) and states[0] not in ('Z', 'X')\n"
        "    record = {'started': started,\n"
        "              'running': {kind: running(pid) for kind, pid in started.items()}}\n"
        f"    with open({part!r}, 'w') as handle:\n"
        "        json.dump(record, handle)\n"
        f"    os.replace({part!r}, {str(record_file)!r})\n"
    ) + then


def _still_running(started, *, within):
    """Those of *started* (kind to pid) still running after up to *within*
    seconds."""
    give_up = time.monotonic() + within
    while True:
        running = {kind: pid for kind, pid in started.items() if _alive(pid)}
        if not running or time.monotonic() >= give_up:
            return running
        time.sleep(0.05)


def _what_a_node_leaves_running(config, workspace, then):
    """Run node code that starts a process of every kind, then runs *then*.

    Returns the run's result, the record the node wrote, and the processes it
    started that still run 5 s after the run ended. Kills what is left, so a
    failure leaves nothing running.
    """
    import json
    import signal

    record_file = workspace / "started.json"
    result = run_isolated(config, _starts_every_kind_of_process(record_file, then))
    assert record_file.exists(), (
        f"the node did not start its processes: {result['stderr'][:2000]}"
    )
    record = json.loads(record_file.read_text())
    try:
        return result, record, _still_running(record["started"], within=5)
    finally:
        for pid in record["started"].values():
            if _alive(pid):
                os.kill(pid, signal.SIGKILL)


def _every_kind_ran(record):
    assert len(record["started"]) == 5 and all(record["running"].values()), (
        f"not every process the node started was running when it ended: {record}"
    )


# Owner rule, 11-07: every process a node starts ends when the node returns.
# Never weaken, skip or remove these tests.
def test_every_process_a_node_starts_ends_when_the_node_returns(isolated, workspace):
    """A node that returns leaves nothing it started running: the zygote
    kills the run's process group before it reaps the child."""
    result, record, running = _what_a_node_leaves_running(
        isolated, workspace, then="    return 1\n"
    )
    assert result["output"]["path"], f"the node did not return: {result['stderr'][:2000]}"
    _every_kind_ran(record)
    assert not running, f"the node returned and left these running: {running}"


# Owner rule, 11-07: every process a node starts ends when the node returns.
# Never weaken, skip or remove these tests.
def test_every_process_a_node_starts_ends_when_the_node_raises(isolated, workspace):
    """A node that raises leaves nothing it started running."""
    result, record, running = _what_a_node_leaves_running(
        isolated, workspace,
        then="    raise RuntimeError('this node fails after starting its processes')\n",
    )
    assert "this node fails after starting its processes" in result["stderr"], (
        result["stderr"][:2000]
    )
    _every_kind_ran(record)
    assert not running, f"the node raised and left these running: {running}"


# Owner rule, 11-07: every process a node starts ends when the node returns.
# Never weaken, skip or remove these tests.
def test_every_process_a_node_starts_ends_when_the_node_times_out(isolated, workspace):
    """A node stopped at its deadline leaves nothing it started running: the
    deadline kill reaches the run's process group, which no process the node
    starts can leave."""
    import copy

    # Short, to keep the test quick, and long enough that every process has
    # started before the deadline comes.
    config = copy.copy(isolated)
    config.wall_timeout = 10
    result, record, running = _what_a_node_leaves_running(
        config, workspace, then="    time.sleep(120)\n    return 1\n"
    )
    assert "stopped after" in result["stderr"], result["stderr"][:2000]
    _every_kind_ran(record)
    assert not running, f"the node timed out and left these running: {running}"


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


def _thread_names_of(pid):
    task_dir = f"/proc/{pid}/task"
    names = []
    for thread_id in os.listdir(task_dir):
        try:
            with open(os.path.join(task_dir, thread_id, "comm")) as handle:
                names.append(handle.read().strip())
        except OSError:
            continue
    return names


def test_the_zygote_is_single_threaded_once_it_has_forked(isolated):
    """After its first fork, only the accept loop may be left running.

    On DuckDB 1.x, ``import duckdb`` opens a connection with a pool of threads
    (2.0 opens it on first use only), and children forked with that pool alive
    crashed inside DuckDB, so the zygote closes it before serving
    (``zygote._release_import_time_duckdb``). numpy's OpenBLAS
    pool is still there when serving starts but tears itself down on the first
    fork, hence one execution before counting.

    pyarrow's jemalloc background thread ("jemalloc_bg_thd") is allowed: it is
    fork-aware, and no child crashed in 1,200 repro executions with it alive.
    Anything else left running is named in the failure.
    """
    from utk_curio.sandbox.isolation import lifecycle

    assert run_isolated(isolated, "    return 1\n")["stderr"] == ""
    names = _thread_names_of(lifecycle._process.pid)
    others = [name for name in names if name != "jemalloc_bg_thd"]
    assert len(others) == 1, f"the zygote has {len(names)} threads after forking: {names}"


def test_node_code_can_still_use_duckdb(isolated, workspace):
    """The zygote closed DuckDB's default connection; node code must not notice.

    Runs at the sandbox's default memory headroom, not the fixture's 256 MB. A
    connection opened in the child starts one thread per core, and at 8 MB of
    stack each that is about 0.5 GB of address space on a 64-core runner. At
    256 MB it failed intermittently with DuckDB's "Out of Memory Error".
    """
    import copy

    from utk_curio.sandbox.isolation import supervisor
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    config = copy.copy(isolated)
    config.limits = dict(isolated.limits,
                         memory_mb=supervisor.DEFAULT_LIMITS["memory_mb"])
    result = run_isolated(
        config, "    return duckdb.sql('select 42').fetchall()[0][0]\n"
    )
    assert result["stderr"] == "", result["stderr"]
    assert load_from_duckdb(result["output"]["path"]) == 42


def test_the_zygote_is_replaced_if_it_dies(isolated):
    from utk_curio.sandbox.isolation import lifecycle

    lifecycle._process.kill()
    lifecycle._process.wait(timeout=10)

    lifecycle.ensure_running(isolated, exec_user=None, require_seccomp=HAS_PYSECCOMP)
    assert lifecycle.is_running()
    assert run_isolated(isolated, "    return 1\n")["stderr"] == ""


def _ask_and_hang_up(socket_path, line):
    """Send *line* to the zygote as a caller that has stopped waiting for it.

    ``ZygoteClient.run`` waits ``connect_timeout`` (10 s) for the zygote's
    first answer and hangs up when that runs out. This caller shuts its
    reading half before it asks, so the answer finds no reader whatever the
    timing: the zygote's send breaks as it does on a caller already gone.
    Returns once nothing holds the zygote's end of the connection any more,
    or after 10 s.
    """
    import select
    import socket

    caller = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        caller.connect(socket_path)
        caller.shutdown(socket.SHUT_RD)
        caller.sendall(line)
        let_go = select.poll()
        let_go.register(caller, select.POLLHUP)
        let_go.poll(10_000)
    finally:
        caller.close()


def _children_of(pid):
    """The pids whose parent is *pid*, read from /proc (no procps in the image)."""
    children = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/status") as handle:
                parent = next(
                    (line.split()[1] for line in handle if line.startswith("PPid:")), None
                )
        except OSError:
            continue
        if parent == str(pid):
            children.append(int(entry))
    return children


def test_the_zygote_survives_a_caller_that_hangs_up_before_its_pid(isolated):
    """The zygote exited when its pid went to a caller that had hung up.

    The broken pipe left its accept loop, so every isolated run after it
    failed with "could not reach the execution zygote" until the stack
    restarted. The failed answer now closes that one connection, and the same
    zygote serves the next run. The child it forked for that caller is
    stopped: nothing will read its result.
    """
    from utk_curio.sandbox.isolation import lifecycle, protocol, supervisor
    from utk_curio.sandbox.util.parsers import _shared_data_dir

    zygote = lifecycle._process
    # A child that sleeps for two minutes, with a deadline as long, so only
    # the zygote stopping it ends it within the test.
    request = protocol.build_exec_request(
        code="    import time\n    time.sleep(120)\n    return 1\n",
        node_type="curio.builtin/python-computation",
        data_type="",
        scratch_dir=supervisor.make_scratch_dir(
            str(_shared_data_dir()), exec_uid=isolated.exec_uid
        ),
        input_spec=dict(protocol.INPUT_NONE),
        limits=isolated.limits,
        wall_timeout=120,
    )
    _ask_and_hang_up(isolated.socket_path, protocol.encode_request(request) + b"\n")

    following = run_isolated(isolated, "    return 1\n")
    assert following["stderr"] == "", following["stderr"]
    assert zygote.poll() is None, f"the zygote exited with {zygote.returncode}"
    assert lifecycle._process is zygote, "the zygote was replaced, not kept"

    give_up = time.monotonic() + 10
    while _children_of(zygote.pid) and time.monotonic() < give_up:
        time.sleep(0.1)
    assert not _children_of(zygote.pid), (
        "the child forked for the caller that hung up is still running, for nobody"
    )


def test_the_zygote_survives_a_caller_that_hangs_up_before_its_error(isolated):
    """The same for the error a malformed request is answered with, which
    forks nothing: the zygote exited on that answer too."""
    from utk_curio.sandbox.isolation import lifecycle

    zygote = lifecycle._process
    _ask_and_hang_up(isolated.socket_path, b"this is not a request\n")

    following = run_isolated(isolated, "    return 1\n")
    assert following["stderr"] == "", following["stderr"]
    assert zygote.poll() is None, f"the zygote exited with {zygote.returncode}"
    assert lifecycle._process is zygote, "the zygote was replaced, not kept"


def test_a_run_after_the_zygote_died_starts_it_again(isolated, monkeypatch):
    """Nothing started a zygote that had died again.

    Only the sandbox's first isolated run starts it, and the runner that run
    resolved is kept (``api._isolated_runner``). So after a death every Python
    node failed with "could not reach the execution zygote" until the stack
    restarted. A run that finds it gone now starts it again, as it was first
    started. ``test_the_zygote_is_replaced_if_it_dies`` calls
    ``ensure_running`` itself; this goes through ``/exec``, as the backend
    does.
    """
    import json

    from utk_curio.sandbox.app import api, app
    from utk_curio.sandbox.isolation import lifecycle, runner

    monkeypatch.setattr(api, "_isolation_state", (runner.execute_isolated, isolated))

    def run():
        resp = app.test_client().post("/exec", json={
            "code": "    return 1\n", "file_path": "",
            "nodeType": "curio.builtin/python-computation", "dataType": "",
            "session_id": "session-zygote-restart", "save_dataset": False,
        })
        reply = json.loads(resp.get_data(as_text=True))
        resp.close()
        return reply

    first = run()
    assert first["stderr"] == "", first["stderr"]

    dead = lifecycle._process
    dead.kill()
    dead.wait(timeout=10)

    after = run()
    assert after["stderr"] == "", after["stderr"]
    assert after["output"]["path"], after
    assert lifecycle.is_running() and lifecycle._process is not dead


def _ask_for_a_sleeping_child(config):
    """Ask the zygote for a node that sleeps for two minutes, on a connection
    left open. Returns the connection and the child's pid once the node's
    code runs, so the child's confinement is over."""
    import json
    import socket

    from utk_curio.sandbox.isolation import protocol, supervisor
    from utk_curio.sandbox.util.parsers import _shared_data_dir

    scratch_dir = supervisor.make_scratch_dir(
        str(_shared_data_dir()), exec_uid=config.exec_uid
    )
    request = protocol.build_exec_request(
        # The node runs in its scratch directory, and leaves a mark there.
        code="    import time\n    open('running', 'w').close()\n    time.sleep(120)\n    return 1\n",
        node_type="curio.builtin/python-computation",
        data_type="",
        scratch_dir=scratch_dir,
        input_spec=dict(protocol.INPUT_NONE),
        limits=config.limits,
        wall_timeout=120,
    )
    caller = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    caller.connect(config.socket_path)
    caller.sendall(protocol.encode_request(request) + b"\n")
    caller.settimeout(30)
    answer = b""
    while not answer.endswith(b"\n"):
        chunk = caller.recv(64)
        assert chunk, f"the zygote closed the connection before the pid: {answer!r}"
        answer += chunk
    pid = json.loads(answer)["pid"]
    running = os.path.join(scratch_dir, "running")
    give_up = time.monotonic() + 60
    while not os.path.exists(running) and time.monotonic() < give_up:
        time.sleep(0.05)
    assert os.path.exists(running), f"the node of child {pid} never started"
    return caller, pid


def _sockets_of(pid):
    """The sockets *pid* holds open past its standard streams, which a child
    shares with the zygote on purpose, as /proc names them."""
    fd_dir = f"/proc/{pid}/fd"
    sockets = set()
    for entry in os.listdir(fd_dir):
        if int(entry) < 3:
            continue
        try:
            target = os.readlink(os.path.join(fd_dir, entry))
        except OSError:
            continue
        if target.startswith("socket:"):
            sockets.add(target)
    return sockets


def _alive(pid):
    """Whether *pid* still runs: neither gone nor a zombie."""
    try:
        with open(f"/proc/{pid}/status") as handle:
            for line in handle:
                if line.startswith("State:"):
                    return line.split()[1] not in ("Z", "X")
    except OSError:
        pass
    return False


def test_a_running_child_holds_none_of_the_zygotes_connections(isolated):
    """A child kept the zygote's end of the connections it was forked with:
    its own caller's, and that of any caller accepted and not read yet.

    Node code could read and write on them: another run's request, connection
    keys included, or a made-up answer to it. And once the zygote died, those
    callers read nothing until the child ended. The child now closes them
    before its node runs, so it shares no socket with the zygote.
    """
    import socket

    from utk_curio.sandbox.isolation import lifecycle

    # Accepted before the child is forked (the zygote accepts in order), and
    # never asks for anything.
    waiting = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    waiting.connect(isolated.socket_path)
    caller, pid = _ask_for_a_sleeping_child(isolated)
    try:
        shared = _sockets_of(lifecycle._process.pid) & _sockets_of(pid)
        assert not shared, (
            f"child {pid} holds the zygote's end of {len(shared)} of its "
            f"connections: {sorted(shared)}"
        )
    finally:
        waiting.close()
        caller.close()


def test_a_child_dies_with_its_zygote(isolated):
    """A child outlived a zygote that died: nothing enforced its deadline any
    more, and nothing would read its result, so it ran on for nobody. The
    kernel now kills it with the zygote (``PR_SET_PDEATHSIG``)."""
    from utk_curio.sandbox.isolation import lifecycle

    caller, pid = _ask_for_a_sleeping_child(isolated)
    try:
        lifecycle._process.kill()
        lifecycle._process.wait(timeout=10)
        give_up = time.monotonic() + 5
        while _alive(pid) and time.monotonic() < give_up:
            time.sleep(0.05)
        assert not _alive(pid), f"the zygote is dead and its child {pid} still runs, for nobody"
    finally:
        caller.close()


def _starts_a_process(pid_file, then):
    """Node code that starts ``sleep 120``, writes its pid to *pid_file*, then
    runs *then*.

    ``Popen`` raises when the program cannot start, so a pid in the file is a
    process that ran. Written beside the file, then renamed, so a reader never
    sees half of it.
    """
    part = f"{pid_file}.part"
    return (
        "    import os, subprocess\n"
        "    started = subprocess.Popen(['sleep', '120'])\n"
        f"    with open({part!r}, 'w') as handle:\n"
        "        handle.write(str(started.pid))\n"
        f"    os.replace({part!r}, {str(pid_file)!r})\n"
    ) + then


def test_a_process_its_node_started_dies_with_the_zygote(isolated, workspace):
    """A process that node code started outlived a zygote that died.

    The kernel kills the child with the zygote (``PR_SET_PDEATHSIG``), but a
    process the child starts loses that setting at its fork. So it ran on for
    nobody, outside the sandbox's count of running nodes, until it ended. The
    run, which reads end-of-file before its status, now kills the child's
    process group.
    """
    import copy
    import signal
    import threading

    from utk_curio.sandbox.isolation import lifecycle

    # A deadline as long as the process's life, so the zygote's own deadline
    # kill cannot end it within the test: only the kill this test is about can.
    config = copy.copy(isolated)
    config.wall_timeout = 120
    pid_file = workspace / "started.pid"
    code = _starts_a_process(
        pid_file, then="    import time\n    time.sleep(120)\n    return 1\n"
    )
    replies = []
    run = threading.Thread(
        target=lambda: replies.append(run_isolated(config, code)), daemon=True
    )
    run.start()
    started = None
    try:
        give_up = time.monotonic() + 60
        while not pid_file.exists() and time.monotonic() < give_up:
            time.sleep(0.05)
        assert pid_file.exists(), f"the node never started its process: {replies}"
        started = int(pid_file.read_text())
        assert _alive(started), f"process {started} ended before the zygote died"
        assert run.is_alive(), f"the run ended before the zygote died: {replies}"

        lifecycle._process.kill()
        lifecycle._process.wait(timeout=10)
        give_up = time.monotonic() + 10
        while _alive(started) and time.monotonic() < give_up:
            time.sleep(0.05)
        assert not _alive(started), (
            f"the zygote is dead and process {started}, which its node started, "
            "still runs, for nobody"
        )

        run.join(timeout=30)
        assert not run.is_alive(), "the run did not end when its zygote died"
        assert "before reporting the child" in replies[0]["stderr"], replies[0]
    finally:
        if started is not None and _alive(started):
            os.kill(started, signal.SIGKILL)


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
# The zygote learns that a child exited as the child exits
# ---------------------------------------------------------------------------

#: The poll of a zygote started by ``polling_slowly``: far longer than any run
#: here takes, so a run reported sooner was reported because its child exited,
#: not because the zygote looked.
SLOW_POLL_SECONDS = 15.0

#: How soon after its node returns a run must be reported: the child's exit,
#: the zygote's report and the output's store, with room for a loaded runner.
#: Well under SLOW_POLL_SECONDS.
REPORTED_WITHIN_SECONDS = 3.0


def _zygote_started_with(workspace, monkeypatch, prelude):
    """A zygote of the test's own, started as ``lifecycle.ensure_running``
    starts one, but with *prelude* run first in its process. Returns the
    process and the config that reaches it; stop it with :func:`_stop`."""
    from utk_curio.sandbox.isolation import lifecycle, runner

    socket_path = str(workspace / "own-zygote.sock")
    monkeypatch.setenv("CURIO_EXEC_SOCKET", socket_path)
    monkeypatch.setenv("CURIO_EXEC_TIMEOUT", "20")
    monkeypatch.setenv("CURIO_EXEC_MEMORY_MB", str(MEMORY_HEADROOM_MB))
    monkeypatch.setenv("CURIO_EXEC_PARALLELISM", "4")
    config = runner.IsolationConfig.from_environment()
    command = [
        sys.executable, "-u", "-c",
        prelude
        + "import sys\n"
        "from utk_curio.sandbox.isolation import zygote\n"
        "sys.exit(zygote.main(sys.argv[1:]))\n",
        "--socket", socket_path,
    ]
    if HAS_PYSECCOMP:
        command.append("--require-seccomp")
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=None, text=True,
        env=lifecycle.zygote_environment(config.limits), start_new_session=True,
    )
    try:
        lifecycle._wait_for_ready(process, socket_path)
    except BaseException:
        _stop(process)
        raise
    return process, config


def _stop(process):
    """Stop a zygote of a test's own. The kernel stops its children with it
    (``child._die_with_the_zygote``)."""
    process.kill()
    process.wait(timeout=10)


@pytest.fixture
def polling_slowly(workspace, monkeypatch):
    """A zygote that polls for exited children every SLOW_POLL_SECONDS, not
    every 50 ms, and the config that reaches it."""
    process, config = _zygote_started_with(
        workspace, monkeypatch,
        "from utk_curio.sandbox.isolation import zygote\n"
        f"zygote._REAP_POLL_SECONDS = {SLOW_POLL_SECONDS!r}\n",
    )
    try:
        yield config
    finally:
        _stop(process)


def test_a_run_is_reported_as_its_child_exits_not_at_the_zygotes_next_poll(polling_slowly):
    """Nothing woke the zygote's select when a child exited, so it learned of
    the exit only at its next poll, every 50 ms (``_REAP_POLL_SECONDS``).
    Every isolated run waited for it: a run of ``return 1`` took about 57 ms
    (run 42388636533). A pidfd of each child now wakes the select as the child
    exits. Here the poll is SLOW_POLL_SECONDS, so the report must come well
    before it."""
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    result = run_isolated(polling_slowly, "    return time.monotonic()\n")
    reported = time.monotonic()
    assert result["stderr"] == "", result["stderr"]
    late = reported - load_from_duckdb(result["output"]["path"])
    assert late < REPORTED_WITHIN_SECONDS, (
        f"the run was reported {late:.1f} s after its node returned: at the "
        f"zygote's next poll (every {SLOW_POLL_SECONDS:.0f} s here), not as "
        "its child exited"
    )


def test_two_runs_at_once_are_each_reported_as_their_child_exits(polling_slowly, workspace):
    """The pidfd of the child that exits wakes the select while the other
    child runs on, and that one's wakes it when it exits in turn: neither run
    waits for the poll."""
    import threading

    from utk_curio.sandbox.util.parsers import load_from_duckdb

    started = workspace / "slower-started"
    slower = {}

    def run_the_slower():
        slower["result"] = run_isolated(
            polling_slowly,
            f"    open({str(started)!r}, 'w').close()\n"
            "    time.sleep(2)\n"
            "    return time.monotonic()\n",
        )
        slower["reported"] = time.monotonic()

    thread = threading.Thread(target=run_the_slower, daemon=True)
    thread.start()
    give_up = time.monotonic() + 60
    while not started.exists() and time.monotonic() < give_up:
        time.sleep(0.02)
    assert started.exists(), f"the slower node never started: {slower}"

    quicker = run_isolated(polling_slowly, "    return time.monotonic()\n")
    quicker_reported = time.monotonic()
    thread.join(timeout=SLOW_POLL_SECONDS + 60)
    assert not thread.is_alive(), "the slower run was never reported"

    late = {}
    for name, result, reported in (
        ("the quicker run", quicker, quicker_reported),
        ("the slower run", slower["result"], slower["reported"]),
    ):
        assert result["stderr"] == "", f"{name}: {result['stderr']}"
        late[name] = round(reported - load_from_duckdb(result["output"]["path"]), 1)
    assert all(seconds < REPORTED_WITHIN_SECONDS for seconds in late.values()), (
        f"seconds from each node's return to its run's report: {late}. They "
        f"came at the zygote's next poll (every {SLOW_POLL_SECONDS:.0f} s "
        "here), not as each child exited"
    )


def _pidfds_of(pid):
    """The pids *pid* holds a pidfd of, by descriptor. Read from the ``Pid:``
    line of each descriptor's fdinfo, since a pidfd's link reads differently
    across kernels."""
    held = {}
    fdinfo = f"/proc/{pid}/fdinfo"
    for entry in os.listdir(fdinfo):
        try:
            with open(os.path.join(fdinfo, entry)) as handle:
                for line in handle:
                    if line.startswith("Pid:"):
                        held[int(entry)] = int(line.split()[1])
                        break
        except (OSError, ValueError):
            continue
    return held


def _watched_by_epolls_of(pid):
    """The inodes of the files watched by the epoll instances *pid* holds,
    from the ``tfd:`` lines of their fdinfo (each target's inode, in hex)."""
    watched = set()
    fdinfo = f"/proc/{pid}/fdinfo"
    for entry in os.listdir(fdinfo):
        try:
            with open(os.path.join(fdinfo, entry)) as handle:
                for line in handle:
                    match = re.match(r"tfd:.*\bino:([0-9a-f]+)", line)
                    if match:
                        watched.add(int(match.group(1), 16))
        except OSError:
            continue
    return watched


def _socket_inodes(pid):
    """The inodes of the sockets *pid* holds past its standard streams."""
    return {int(target[len("socket:["):-1]) for target in _sockets_of(pid)}


def _catches_or_ignores_sigchld(pid):
    """Whether *pid* catches SIGCHLD, and whether it ignores it, from the
    SigCgt and SigIgn masks of its status."""
    import signal

    bit = 1 << (signal.SIGCHLD - 1)
    masks = {}
    with open(f"/proc/{pid}/status") as handle:
        for line in handle:
            name, _, value = line.partition(":")
            if name in ("SigCgt", "SigIgn"):
                masks[name] = int(value.strip(), 16)
    return bool(masks["SigCgt"] & bit), bool(masks["SigIgn"] & bit)


def test_a_running_child_holds_nothing_of_the_zygotes_select(isolated):
    """The zygote watches each running child through a pidfd, in the select
    that watches its callers' connections. A child forked while another ran
    would hold both:

    - the select's epoll, which it shares with the zygote, so node code could
      add descriptors of its own to the zygote's select, which would then
      never sleep. Every child held it before pidfds came;
    - the other child's pidfd, through which node code could wait on another
      run's child.

    Each child closes them after its fork, as it closes the connections. And
    SIGCHLD is left to it as the zygote found it, neither caught nor ignored.
    """
    from utk_curio.sandbox.isolation import lifecycle

    zygote = lifecycle._process.pid
    first_caller, first = _ask_for_a_sleeping_child(isolated)
    try:
        second_caller, second = _ask_for_a_sleeping_child(isolated)
        try:
            sockets = _socket_inodes(zygote)
            # The zygote's own select watches its listening socket, so the
            # child's check below cannot pass for reading nothing.
            assert _watched_by_epolls_of(zygote) & sockets, (
                "no epoll instance of the zygote watches its sockets"
            )
            assert not _watched_by_epolls_of(second) & sockets, (
                f"child {second} holds the zygote's select, which watches its sockets"
            )
            assert first in _pidfds_of(zygote).values(), (
                f"the zygote holds no pidfd of its running child {first}"
            )
            assert not _pidfds_of(second), (
                f"child {second} holds pidfds of {sorted(_pidfds_of(second).values())}"
            )
            assert _catches_or_ignores_sigchld(second) == (False, False), (
                f"child {second} catches or ignores SIGCHLD"
            )
        finally:
            second_caller.close()
    finally:
        first_caller.close()


def test_the_zygote_holds_a_pidfd_of_each_running_child_and_none_once_its_run_ends(isolated):
    """While a child runs, the zygote holds a pidfd of it, and of nothing
    else. Once the run is reported, that pidfd is closed, however the run
    ended: its node returned or raised, it reached its deadline, its child
    was killed, or its caller hung up before the pid came. A pidfd left open
    would be a descriptor lost per run, until the zygote ran out of them."""
    import copy
    import json
    import signal

    from utk_curio.sandbox.isolation import lifecycle, protocol, supervisor
    from utk_curio.sandbox.util.parsers import _shared_data_dir

    zygote = lifecycle._process.pid

    def descriptors():
        fd_dir = f"/proc/{zygote}/fd"
        held = {}
        for entry in os.listdir(fd_dir):
            try:
                held[int(entry)] = os.readlink(os.path.join(fd_dir, entry))
            except OSError:
                continue
        return held

    assert run_isolated(isolated, "    return 1\n")["stderr"] == ""
    before = descriptors()

    caller, child = _ask_for_a_sleeping_child(isolated)
    try:
        held = sorted(_pidfds_of(zygote).values())
        assert held == [child], (
            f"while child {child} runs, the zygote holds pidfds of {held}"
        )
        # Killed outright, as the kernel kills a child out of memory.
        os.kill(child, signal.SIGKILL)
        caller.settimeout(30)
        answer = b""
        while not answer.endswith(b"\n"):
            chunk = caller.recv(256)
            assert chunk, f"the zygote closed the connection before the status: {answer!r}"
            answer += chunk
        assert json.loads(answer)["signal"] == signal.SIGKILL, answer
    finally:
        caller.close()

    assert run_isolated(isolated, "    return 1\n")["stderr"] == ""
    raised = run_isolated(isolated, "    raise ValueError('boom')\n")
    assert "ValueError" in raised["stderr"], raised["stderr"]
    short = copy.copy(isolated)
    short.wall_timeout = 1
    timed_out = run_isolated(short, "    time.sleep(60)\n    return 1\n")
    assert "stopped after" in timed_out["stderr"], timed_out["stderr"]
    request = protocol.build_exec_request(
        code="    import time\n    time.sleep(120)\n    return 1\n",
        node_type="curio.builtin/python-computation",
        data_type="",
        scratch_dir=supervisor.make_scratch_dir(
            str(_shared_data_dir()), exec_uid=isolated.exec_uid
        ),
        input_spec=dict(protocol.INPUT_NONE),
        limits=isolated.limits,
        wall_timeout=120,
    )
    _ask_and_hang_up(isolated.socket_path, protocol.encode_request(request) + b"\n")

    give_up = time.monotonic() + 10
    while (descriptors() != before or _children_of(zygote)) and time.monotonic() < give_up:
        time.sleep(0.05)
    held = sorted(_pidfds_of(zygote).values())
    assert not held, f"with no child running, the zygote holds pidfds of {held}"
    kept = {fd: target for fd, target in descriptors().items() if before.get(fd) != target}
    assert not kept, f"the zygote kept descriptors of runs that ended: {kept}"


#: How a zygote's process is left without pidfds.
_WITHOUT_A_PIDFD = {
    # A Python whose os has no pidfd_open.
    "missing": "import os\ndel os.pidfd_open\n",
    # A kernel without the call, or a seccomp profile that refuses it.
    "refused": (
        "import errno, os\n"
        "def _refused(pid, flags=0):\n"
        "    raise OSError(errno.ENOSYS, 'pidfd_open is refused here')\n"
        "os.pidfd_open = _refused\n"
    ),
}


@pytest.mark.parametrize("pidfd_open", sorted(_WITHOUT_A_PIDFD))
def test_runs_are_reported_where_the_zygote_gets_no_pidfd(workspace, monkeypatch, pidfd_open):
    """Where a child gets no pidfd, the zygote finds it at its next poll, as
    it found every child before, and its run is reported."""
    process, config = _zygote_started_with(
        workspace, monkeypatch, _WITHOUT_A_PIDFD[pidfd_open]
    )
    try:
        returned = run_isolated(config, "    return 6 * 7\n")
        assert returned["stderr"] == "", returned["stderr"]
        raised = run_isolated(config, "    raise ValueError('boom')\n")
        assert "ValueError" in raised["stderr"], raised["stderr"]
        assert process.poll() is None, f"the zygote exited with {process.returncode}"
    finally:
        _stop(process)


# ---------------------------------------------------------------------------
# Session scoping still holds across the boundary
# ---------------------------------------------------------------------------

def test_a_node_cannot_read_another_sessions_artifact(isolated, workspace):
    from utk_curio.sandbox.util.parsers import save_to_duckdb
    import pandas as pd

    foreign = save_to_duckdb(pd.DataFrame({"a": [1]}), session_id="session-a")

    from utk_curio.sandbox.isolation import runner

    result = runner.execute_isolated(
        "    return 1\n", foreign, "curio.builtin/python-computation", "",
        session_id="session-b", save_dataset=False, config=isolated,
    )
    assert result["output"]["path"] == ""
    assert "could not be loaded" in result["stderr"]


# ---------------------------------------------------------------------------
# #468: a template imports the modules bundled beside it in its package
# ---------------------------------------------------------------------------

#: The layout of #468's report: a package of modules beside the caller
#: template, which imports a sibling relatively.
_HEIGHTS = {
    "building_height/__init__.py": "",
    "building_height/convert_to_raster.py": (
        "from .scale import FACTOR\n"
        "\n"
        "def convert_raster(value):\n"
        "    return value * FACTOR\n"
    ),
    "building_height/scale.py": "FACTOR = 2\n",
}

_CALLER = (
    "    from building_height.convert_to_raster import convert_raster\n"
    "    return convert_raster(21)\n"
)


def _package_sources(package_root, modules):
    """A package's ``sources/``, files 0644 and folders 0755, as an install
    leaves them, and the caller template beside the modules."""
    sources = package_root / "sources"
    for relative, text in modules.items():
        path = sources / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (sources / "caller.py").write_text(_CALLER, encoding="utf-8")
    for path in [sources, *sources.rglob("*")]:
        os.chmod(path, 0o755 if path.is_dir() else 0o644)
    return sources


def test_a_forked_child_imports_the_module_bundled_beside_it(isolated, tmp_path):
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    sources = _package_sources(tmp_path / "ai.test.heights@1", _HEIGHTS)
    result = run_isolated(
        isolated, _CALLER, package_modules={"root": str(sources), "names": ["building_height"]},
    )
    assert result["stderr"] == "", result["stderr"]
    assert load_from_duckdb(result["output"]["path"]) == 42


def test_forked_children_of_two_packages_each_import_their_own_module(isolated, tmp_path):
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    code = "    import shared_name\n    return shared_name.WHO\n"
    seen = []
    for package in ("a", "b", "a"):
        sources = tmp_path / f"ai.test.{package}@1" / "sources"
        if not sources.is_dir():
            _package_sources(sources.parent, {"shared_name.py": f"WHO = {package!r}\n"})
        result = run_isolated(
            isolated, code, package_modules={"root": str(sources), "names": ["shared_name"]},
        )
        assert result["stderr"] == "", result["stderr"]
        seen.append(load_from_duckdb(result["output"]["path"]))
    assert seen == ["a", "b", "a"]


def test_the_execution_user_imports_modules_whose_store_it_cannot_reach(isolated_dropped, tmp_path):
    """The package store is 0700 root-owned under isolation, so the execution
    user reads the modules through their staged links in its scratch
    directory, never at their path in the store."""
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    store = tmp_path / "packages"
    sources = _package_sources(store / "ai.test.heights@1", _HEIGHTS)
    os.chmod(store, 0o700)
    result = run_isolated(
        isolated_dropped, _CALLER,
        package_modules={"root": str(sources), "names": ["building_height"]},
    )
    assert result["stderr"] == "", result["stderr"]
    assert load_from_duckdb(result["output"]["path"]) == 42
