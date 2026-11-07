"""pyseccomp is imported without ctypes.util or a process, and once per zygote.

A JavaScript run's Node starts on Linux through an exec wrapper, a fresh
interpreter that imports pyseccomp to install its filter, and an isolated
Python child installs its filter with pyseccomp too
(``isolation/seccomp_filter.py``, ``child._install_seccomp_filter``).
pyseccomp's import finds libc and libseccomp with ``ctypes.util.find_library``:
importing ``ctypes.util`` imports shutil, subprocess and tempfile, and each
call runs ``ldconfig -p`` in a subprocess. So every JavaScript run paid for
both before Node started, and every isolated child after its fork.

``seccomp_filter.import_pyseccomp`` finds both libraries by soname instead,
and the zygote imports pyseccomp before its first fork. The first two tests
watch the real wrapper and a real zygote's child through an audit hook, which
a ``sitecustomize`` on PYTHONPATH installs in the interpreters they start. The
others import pyseccomp through the helper in fresh interpreters: where the
sonames load and where they do not, where pyseccomp reads more of
``ctypes.util``, and what ``ctypes.util`` is left as.
"""

import importlib.util
import json
import os
import subprocess
import sys

import pytest

pytestmark = [
    pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the seccomp filters exist only on Linux"),
    pytest.mark.skipif(importlib.util.find_spec("pyseccomp") is None, reason="pyseccomp is not installed"),
]

#: The audit events that start a process.
_STARTS_A_PROCESS = ("subprocess.Popen", "os.system", "os.posix_spawn", "os.spawn", "os.fork", "os.forkpty")

#: A ``sitecustomize`` the interpreters a test starts find first on PYTHONPATH.
#: Its audit hook writes ``<pid> <event> <detail>`` for each event named in
#: CURIO_AUDIT_EVENTS (an import only in a process forked after the hook was
#: installed) to the file CURIO_AUDIT_RECORD names, through a descriptor
#: opened once, as an open per event would be an event of its own. Then it
#: runs any sitecustomize later on the path, as the interpreter would have.
_SITECUSTOMIZE = r'''
import os
import sys

_RECORD = os.environ.get("CURIO_AUDIT_RECORD")
_WATCHED = frozenset(filter(None, os.environ.get("CURIO_AUDIT_EVENTS", "").split(",")))
_STARTED_AS = os.getpid()
# Which of an event's arguments says what it did.
_DETAIL = {"import": 0, "os.chdir": 0, "os.exec": 0, "os.system": 0,
           "os.posix_spawn": 1, "os.spawn": 2, "subprocess.Popen": 1}

if _RECORD:
    _FD = os.open(_RECORD, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)

    def _write(event, args):
        if event not in _WATCHED or (event == "import" and os.getpid() == _STARTED_AS):
            return
        index = _DETAIL.get(event)
        detail = args[index] if index is not None and index < len(args) else ""
        os.write(_FD, f"{os.getpid()} {event} {detail!r}\n".encode())

    sys.addaudithook(_write)

import importlib.machinery
import importlib.util

_HERE = os.path.dirname(os.path.abspath(__file__))
_LATER = importlib.machinery.PathFinder.find_spec(
    "sitecustomize", [entry for entry in sys.path if os.path.abspath(entry or os.curdir) != _HERE])
if _LATER is not None:
    _LATER.loader.exec_module(importlib.util.module_from_spec(_LATER))
'''


def _audit(tmp_path, monkeypatch, events):
    """Have every interpreter this test starts record *events*; the file of
    the record."""
    site = tmp_path / "audit-site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(_SITECUSTOMIZE, encoding="utf-8")
    record = tmp_path / "audit-record.txt"
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(
        path for path in (str(site), os.environ.get("PYTHONPATH")) if path
    ))
    monkeypatch.setenv("CURIO_AUDIT_RECORD", str(record))
    monkeypatch.setenv("CURIO_AUDIT_EVENTS", ",".join(events))
    return record


def _recorded(record):
    """``(pid, event, detail)`` for each line of the record."""
    if not record.exists():
        return []
    return [tuple(line.split(" ", 2)) for line in record.read_text(encoding="utf-8").splitlines()]


#: A program the wrapper execs: whether ``setsid`` is refused it. The wrapper
#: runs here in the test's process group, not as its leader, so nothing but
#: the wrapper's filter refuses it.
_TRIES_SETSID = (
    "import os\n"
    "try:\n"
    "    os.setsid()\n"
    "    print('allowed')\n"
    "except PermissionError:\n"
    "    print('PermissionError')\n"
)


def test_the_exec_wrapper_of_a_javascript_run_installs_its_filter_without_starting_a_process(tmp_path, monkeypatch):
    """The wrapper Node starts through on Linux installs its filter, then
    execs: it starts no process on the way, where its import of pyseccomp ran
    ``ldconfig -p`` twice before every JavaScript run."""
    from utk_curio.sandbox.isolation import seccomp_filter

    record = _audit(tmp_path, monkeypatch, (*_STARTS_A_PROCESS, "os.exec"))
    command = seccomp_filter.exec_command([sys.executable, "-I", "-S", "-c", _TRIES_SETSID], required=True)
    done = subprocess.run(command, capture_output=True, text=True, timeout=60)

    assert done.returncode == 0, f"the wrapper, or the program it execs, failed: {done.stderr}"
    assert done.stdout.strip() == "PermissionError", (
        f"the program the wrapper execs was not refused setsid, so the wrapper installed no filter: {done.stdout!r}"
    )
    events = [(event, detail) for _pid, event, detail in _recorded(record)]
    assert events[-1:] and events[-1][0] == "os.exec", (
        f"no exec was recorded, so the audit hook never ran in the wrapper: {events}"
    )
    assert events[:-1] == [], (
        f"the wrapper started a process before it execed the program, as it would before every "
        f"JavaScript run's Node: {events[:-1]}"
    )


#: Node code that says whether its child may make a network socket.
_TRIES_A_SOCKET = (
    "    import socket\n"
    "    try:\n"
    "        socket.socket(socket.AF_INET, socket.SOCK_DGRAM).close()\n"
    "        return 'allowed'\n"
    "    except PermissionError:\n"
    "        return 'PermissionError'\n"
)


def test_an_isolated_child_installs_its_filter_with_the_pyseccomp_its_zygote_imported(tmp_path, monkeypatch):
    """A zygote started as the sandbox starts it imports pyseccomp before its
    first fork, so its child installs its filter without importing pyseccomp
    or starting a process, where each run's child did both after its fork."""
    from utk_curio.sandbox.isolation import lifecycle, runner
    from utk_curio.sandbox.util.db import init_db, release_connection
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CURIO_EXEC_SOCKET", str(tmp_path / "zygote.sock"))
    monkeypatch.setenv("CURIO_EXEC_TIMEOUT", "20")
    monkeypatch.setenv("CURIO_EXEC_MEMORY_MB", "256")
    record = _audit(tmp_path, monkeypatch, ("import", "os.chdir", *_STARTS_A_PROCESS))
    release_connection()
    init_db()
    config = runner.IsolationConfig.from_environment()
    # As lifecycle.ensure_running starts it, but this test's own, so no
    # zygote another test started stands in for it.
    zygote = subprocess.Popen(
        [sys.executable, "-u", "-m", "utk_curio.sandbox.isolation.zygote",
         "--socket", config.socket_path, "--require-seccomp"],
        stdout=subprocess.PIPE, stderr=None, text=True,
        env=lifecycle.zygote_environment(config.limits), start_new_session=True,
    )
    try:
        lifecycle._wait_for_ready(zygote, config.socket_path)
        result = runner.execute_isolated(
            _TRIES_A_SOCKET, "", "curio.builtin/python-computation", "",
            save_dataset=False, config=config,
        )
        assert result["stderr"] == "", result["stderr"]
        seen = load_from_duckdb(result["output"]["path"])
    finally:
        zygote.terminate()
        try:
            zygote.wait(timeout=10)
        except subprocess.TimeoutExpired:
            zygote.kill()
        release_connection()

    assert seen == "PermissionError", f"the child made a network socket, so it installed no filter: {seen}"
    in_the_child = [(event, detail) for pid, event, detail in _recorded(record) if pid != str(zygote.pid)]
    assert any(event == "os.chdir" for event, _detail in in_the_child), (
        f"no chdir of the child's was recorded, so the audit hook never ran in a child: {in_the_child}"
    )
    imported = [detail for event, detail in in_the_child if event == "import"]
    assert repr("pyseccomp") not in imported, (
        f"the child imported pyseccomp after its fork, as each run's child would: {in_the_child}"
    )
    started = [(event, detail) for event, detail in in_the_child if event in _STARTS_A_PROCESS]
    assert started == [], f"the child started a process before it ran the node: {started}"


def test_an_isolated_nodes_code_finds_ctypes_util_imported_as_it_did(tmp_path, monkeypatch):
    """A guard, not a repro. When each child imported pyseccomp itself, the
    import imported ``ctypes.util``, so node code that calls ``ctypes.util``
    after a bare ``import ctypes`` ran under isolation. The zygote, which now
    imports pyseccomp for its children, imports ``ctypes.util`` with it, so
    such code still runs."""
    from utk_curio.sandbox.isolation import lifecycle, runner
    from utk_curio.sandbox.util.db import init_db, release_connection
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CURIO_EXEC_SOCKET", str(tmp_path / "zygote.sock"))
    monkeypatch.setenv("CURIO_EXEC_TIMEOUT", "20")
    monkeypatch.setenv("CURIO_EXEC_MEMORY_MB", "256")
    release_connection()
    init_db()
    config = runner.IsolationConfig.from_environment()
    lifecycle.ensure_running(config, exec_user=None, require_seccomp=True)
    try:
        result = runner.execute_isolated(
            "    import ctypes\n    return ctypes.util.__name__\n",
            "", "curio.builtin/python-computation", "",
            save_dataset=False, config=config,
        )
    finally:
        lifecycle.shutdown()
        release_connection()

    assert result["stderr"] == "", f"node code found no ctypes.util after a bare import ctypes: {result['stderr']}"
    assert load_from_duckdb(result["output"]["path"]) == "ctypes.util"


#: Loads ``seccomp_filter.py`` from its path, as the wrapper runs it, and
#: imports pyseccomp through it in a fresh interpreter: with sonames that
#: load nothing (``--sonames-load-nothing``) or as they are; with
#: ``ctypes.util`` imported first and its ``find_library`` recorded
#: (``--ctypes-util-imported``) or not; with a stand-in pyseccomp first on
#: the path (``--stand-in <folder>``) or not. Prints what pyseccomp loaded,
#: what the real ``find_library`` was asked, what ``ctypes.util`` is after
#: the import, and what the real ``find_library`` gives.
_THROUGH_THE_HELPER = r'''
import importlib.util, json, sys

path, arguments = sys.argv[1], sys.argv[2:]
spec = importlib.util.spec_from_file_location("seccomp_filter", path)
seccomp_filter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seccomp_filter)
if "--sonames-load-nothing" in arguments:
    seccomp_filter._SONAMES = {name: soname + ".not-here" for name, soname in seccomp_filter._SONAMES.items()}
if "--stand-in" in arguments:
    sys.path.insert(0, arguments[arguments.index("--stand-in") + 1])
asked, before, recording = [], None, None
if "--ctypes-util-imported" in arguments:
    import ctypes.util
    before, real = ctypes.util, ctypes.util.find_library

    def recording(name):
        asked.append(name)
        return real(name)

    ctypes.util.find_library = recording
outcome = {}
try:
    pyseccomp = seccomp_filter.import_pyseccomp()
    outcome["loaded"] = [pyseccomp._libc._name, pyseccomp._libseccomp._name]
except ImportError as error:
    outcome["ImportError"] = str(error)
outcome["asked"] = list(asked)
import ctypes

after = sys.modules.get("ctypes.util")
if getattr(ctypes, "util", None) is not after:
    outcome["ctypes.util"] = f"sys.modules holds {after!r}, ctypes.util is {getattr(ctypes, 'util', None)!r}"
elif after is None:
    outcome["ctypes.util"] = "not imported"
elif after is before and after.find_library is recording:
    outcome["ctypes.util"] = "as it was"
elif before is None and after.__name__ == "ctypes.util" and hasattr(after, "__file__"):
    outcome["ctypes.util"] = "imported"
else:
    outcome["ctypes.util"] = f"something else: {after!r}"
import ctypes.util as real_ctypes_util

outcome["found"] = [real_ctypes_util.find_library("c"), real_ctypes_util.find_library("seccomp")]
print(json.dumps(outcome))
'''


def _through_the_helper(*arguments):
    from utk_curio.sandbox.isolation import seccomp_filter

    done = subprocess.run(
        [sys.executable, "-P", "-c", _THROUGH_THE_HELPER, seccomp_filter.__file__, *arguments],
        capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.parametrize("arguments, ctypes_util, asked", [
    # The wrapper's case on glibc: the sonames load, so ctypes.util is never imported.
    pytest.param([], "not imported", [], id="sonames-load"),
    pytest.param(["--ctypes-util-imported"], "as it was", [], id="sonames-load-ctypes-util-imported"),
    # As on musl: the real find_library, imported then and kept.
    pytest.param(["--sonames-load-nothing"], "imported", [], id="sonames-load-nothing"),
    pytest.param(["--sonames-load-nothing", "--ctypes-util-imported"], "as it was", ["c", "seccomp"],
                 id="sonames-load-nothing-ctypes-util-imported"),
])
def test_pyseccomp_loads_what_find_library_finds_and_ctypes_util_is_left_as_its_import_would_leave_it(
    arguments, ctypes_util, asked,
):
    """pyseccomp loads the libraries the real ``find_library`` finds: their
    sonames, without ``ctypes.util``, where those load, and what the real one
    finds where they do not, as musl's C library is not ``libc.so.6``. After
    the import, ``ctypes.util`` is what it was, or the real module where the
    real ``find_library`` was needed, never the stand-in."""
    outcome = _through_the_helper(*arguments)
    assert outcome.get("loaded") == outcome["found"], (
        f"pyseccomp did not load the libraries the real find_library finds: {outcome}"
    )
    assert outcome["ctypes.util"] == ctypes_util, f"ctypes.util after the import: {outcome}"
    assert outcome["asked"] == asked, f"what the real find_library was asked: {outcome}"


#: A stand-in pyseccomp whose import, between its two ``find_library`` calls,
#: reads an attribute of ``ctypes.util`` that pyseccomp 0.1.2 does not:
#: ``test``, which ``ctypes.util`` has on every platform.
_READS_MORE_OF_CTYPES_UTIL = (
    "import ctypes\n"
    "import ctypes.util\n"
    "_libc = ctypes.CDLL(ctypes.util.find_library('c'))\n"
    "TEST = ctypes.util.test\n"
    "_libseccomp = ctypes.CDLL(ctypes.util.find_library('seccomp'))\n"
)


@pytest.mark.parametrize("arguments, ctypes_util", [
    pytest.param([], "imported", id="ctypes-util-not-imported"),
    pytest.param(["--ctypes-util-imported"], "as it was", id="ctypes-util-imported"),
])
def test_a_pyseccomp_whose_import_reads_more_of_ctypes_util_still_imports(tmp_path, arguments, ctypes_util):
    """requirements.txt sets no upper bound on pyseccomp, and 0.1.2 reads
    only ``find_library`` from ``ctypes.util``. A later one whose import
    reads more, here a stand-in that reads ``ctypes.util.test``, gets the
    real module's attribute and imports, and ``ctypes.util`` is left as the
    plain import would leave it: the real module, imported then if it was
    not."""
    stand_in = tmp_path / "reads-more-of-ctypes-util"
    stand_in.mkdir()
    (stand_in / "pyseccomp.py").write_text(_READS_MORE_OF_CTYPES_UTIL, encoding="utf-8")
    outcome = _through_the_helper("--stand-in", str(stand_in), *arguments)
    assert outcome.get("loaded") == outcome["found"], (
        f"pyseccomp did not import, or did not load the libraries the real find_library finds: {outcome}"
    )
    assert outcome["ctypes.util"] == ctypes_util, f"ctypes.util after the import: {outcome}"


def test_ctypes_util_is_put_back_when_pyseccomp_cannot_be_imported(tmp_path):
    """An import that raises, here of a stand-in pyseccomp first on the path,
    raises ImportError as it would have, and leaves no stand-in
    ``ctypes.util`` behind."""
    stand_in = tmp_path / "without-libseccomp"
    stand_in.mkdir()
    (stand_in / "pyseccomp.py").write_text(
        "raise ImportError('a stand-in pyseccomp that cannot load libseccomp')\n", encoding="utf-8",
    )
    outcome = _through_the_helper("--stand-in", str(stand_in))
    assert "a stand-in pyseccomp" in outcome.get("ImportError", ""), outcome
    assert outcome["ctypes.util"] == "not imported", f"ctypes.util after the import raised: {outcome}"
