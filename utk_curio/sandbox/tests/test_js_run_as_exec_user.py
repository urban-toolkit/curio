"""A JavaScript node's Node runs as the execution account, as an isolated Python child does.

``worker.run_js_script`` starts Node through the exec wrapper of
``isolation/seccomp_filter.py``. Node drops exactly when an isolated Python
child does: under ``CURIO_ISOLATION=fork``, with ``CURIO_EXEC_USER`` naming an
account and the sandbox running as root. The wrapper drops it in the child's
order before its exec (no new privileges, the filter, then groups, gid and
uid) and execs Node only once all three ids are the account's and it holds no
group; where that fails, Node never starts. Its HOME and TMPDIR are a folder
of the run's own, 0700 and the account's, which holds DuckDB's extensions as
links into Curio's copy and ends with the run.

These run in the unit (sandbox) job, as root in the CI image, which carries
``curio-exec``. A fixture sets the two variables and gives each run a folder
the account owns, under folders it can traverse, as ``test_isolation_linux.py``'s
``isolated_dropped`` does. The kill-at-return scenarios of
``test_js_run_kills_at_return.py`` run again here, with Node as the account:
the owner rule holds whoever Node runs as. That file stays as it is.
"""

import inspect
import json
import os
import stat
import sys
import types

import pytest

from utk_curio.sandbox.tests import test_js_run_kills_at_return as kills

#: Created by the Dockerfile. Only exists inside the image.
EXEC_USER = "curio-exec"

#: An account no host has.
MISSING_ACCOUNT = "curio-exec-no-such-account"

#: An account whose ids are ``(uid_t) -1``, which names no one: the kernel
#: refuses setgid and setuid to it with EINVAL.
REFUSED_ACCOUNT = "curio-exec-refused-ids"
REFUSED_ID = 4294967295

#: Node code that returns the lines of its ``/proc/self/status``, by name.
_READS_ITS_STATUS = r"""
const fs = await import('node:fs');
const status = {};
for (const line of fs.readFileSync('/proc/self/status', 'utf8').split('\n')) {
  const at = line.indexOf(':');
  if (at > 0) status[line.slice(0, at)] = line.slice(at + 1).trim();
}
return status;
"""

#: Node code that returns its HOME and TMPDIR, the mode and owner of the folder
#: HOME names, and what it holds where duckdb-wasm looks for DuckDB's
#: extensions: each file there, by its path under that folder, with the file a
#: link there resolves to, or null for a file that is no link. It makes and
#: removes a folder in TMPDIR, as a node that writes its own files does.
_READS_ITS_HOME = r"""
const fs = await import('node:fs');
const os = await import('node:os');
const path = await import('node:path');
const home = os.homedir();
const info = fs.statSync(home);
const looks = path.join(home, '.duckdb', 'extensions', 'extensions.duckdb.org');
const extensions = {};
if (fs.existsSync(looks)) {
  for (const name of fs.readdirSync(looks, { recursive: true }).map(String)) {
    const at = path.join(looks, name);
    if (!fs.statSync(at).isFile()) continue;
    extensions[name.split(path.sep).join('/')] = fs.lstatSync(at).isSymbolicLink() ? fs.realpathSync(at) : null;
  }
}
fs.rmSync(fs.mkdtempSync(path.join(os.tmpdir(), 'written-by-the-node-')), { recursive: true });
return {
  home, tmp: os.tmpdir(), HOME: process.env.HOME ?? null, TMPDIR: process.env.TMPDIR ?? null,
  mode: info.mode & 0o777, uid: info.uid, extensions,
};
"""


@pytest.fixture
def as_the_account(tmp_path_factory, monkeypatch):
    """Node run as the sandbox runs it under fork isolation with an execution
    user, and a folder the account owns for its working directory, where the
    scenarios write their records. The folders above it gain execute for
    everyone where they lack it, so the account reaches its own without
    listing any of them."""
    import pwd

    if not sys.platform.startswith("linux"):
        pytest.skip("Node drops to the execution account only on Linux")
    if os.getuid() != 0:
        pytest.skip("dropping to the execution account requires a root sandbox")
    try:
        account = pwd.getpwnam(EXEC_USER)
    except KeyError:
        pytest.skip(f"the {EXEC_USER} account does not exist on this host")

    root = tmp_path_factory.mktemp("js-as-the-account", numbered=True)
    current = root
    while str(current) != os.path.dirname(str(current)):
        mode = stat.S_IMODE(os.stat(current).st_mode)
        if not mode & stat.S_IXOTH:
            os.chmod(current, mode | 0o011)
        current = current.parent
    work = root / "work"
    work.mkdir()
    os.chown(work, account.pw_uid, account.pw_gid)
    os.chmod(work, 0o700)

    monkeypatch.setenv("CURIO_ISOLATION", "fork")
    monkeypatch.setenv("CURIO_EXEC_USER", EXEC_USER)
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(root))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(root / "data"))
    return types.SimpleNamespace(account=account, work=work)


def _ran(code, cwd, node_type):
    """Run *code* as a JavaScript node, as ``execute_js_code`` does, and return
    ``(value, stderr)``: the value it returned, or None when the run gave no
    result, and its stderr lines."""
    run = kills._Run(code, cwd, node_type)
    assert run.ended_within(kills.WAIT), f"the run has not returned {kills.WAIT} s after it started"
    result, _logs, stderr = run.result()
    if result is None:
        return None, stderr
    outcome = json.loads(result)
    assert outcome["success"], outcome
    return outcome["value"], stderr


def _writes_then_returns(marker):
    """Node code whose first act is to write *marker*: a Node that started
    leaves it, with its uid."""
    return (
        "const fs = await import('node:fs');\n"
        f"fs.writeFileSync({json.dumps(str(marker))}, String(process.getuid()));\n"
        "return 1;\n"
    )


def test_node_runs_as_the_execution_account(as_the_account):
    """All four of Node's uids are the account's and all four gids its group's,
    it holds no supplementary group and no effective, permitted or ambient
    capability, and nothing it runs can gain privileges. Node's
    ``process.getgroups()`` always adds the effective gid, so the groups are
    read from ``/proc/self/status``."""
    status, stderr = _ran(_READS_ITS_STATUS, as_the_account.work, "READS_ITS_IDS")
    assert status is not None, "\n".join(stderr)
    account = as_the_account.account
    assert status["Uid"].split() == [str(account.pw_uid)] * 4, (
        f"Node ran with the uids {status['Uid'].split()}, not {EXEC_USER}'s {account.pw_uid}"
    )
    assert status["Gid"].split() == [str(account.pw_gid)] * 4, (
        f"Node ran with the gids {status['Gid'].split()}, not {EXEC_USER}'s {account.pw_gid}"
    )
    assert status["Groups"] == "", f"Node kept supplementary groups: {status['Groups']!r}"
    for name in ("CapEff", "CapPrm", "CapAmb"):
        assert int(status[name], 16) == 0, f"Node holds capabilities: {name} {status[name]}"
    assert status["NoNewPrivs"] == "1", "nothing Node runs is kept from gaining privileges"


def test_home_and_tmpdir_are_a_folder_of_the_runs_own_that_ends_with_it(as_the_account):
    """HOME and TMPDIR name one folder, the run's own: 0700, the account's, and
    gone once the run has ended, so no other run's files are in it and nothing
    of it outlives the run. It holds, where duckdb-wasm's Node worker looks, a
    link to each of Curio's DuckDB extensions, so a node finds them as the
    sandbox's own Node does and downloads nothing."""
    from utk_curio.sandbox.util import node_runtime

    copy = node_runtime.duckdb_extensions_dir()
    vendored = {
        path.relative_to(copy).as_posix(): os.path.realpath(path) for path in sorted(copy.rglob("*.wasm"))
    }
    assert vendored, f"Curio's copy of DuckDB's extensions at {copy} holds none, so this proves nothing"
    folders = []
    for run in ("FIRST", "SECOND"):
        seen, stderr = _ran(_READS_ITS_HOME, as_the_account.work, f"READS_ITS_HOME_{run}")
        assert seen is not None, "\n".join(stderr)
        assert seen["home"] == seen["tmp"] == seen["HOME"] == seen["TMPDIR"], (
            f"HOME and TMPDIR are not one folder of the run's own: {seen}"
        )
        assert (seen["mode"], seen["uid"]) == (0o700, as_the_account.account.pw_uid), (
            f"the run's folder {seen['home']} is 0o{seen['mode']:03o}, owned by uid {seen['uid']}, "
            f"not 0o700 and {EXEC_USER}'s"
        )
        assert seen["extensions"] == vendored, (
            f"where duckdb-wasm looks, the run's folder holds {seen['extensions']}, "
            f"not a link to each of Curio's extensions {vendored}"
        )
        assert not os.path.exists(seen["home"]), f"the run's folder {seen['home']} outlived the run"
        folders.append(seen["home"])
    assert folders[0] != folders[1], f"two runs had the same folder: {folders[0]}"


def test_a_missing_account_stops_the_run_before_node_starts(as_the_account, monkeypatch):
    """As the zygote does not start for an execution user that does not exist,
    a JavaScript run does not start Node, and says why, naming the account.
    Node never runs as the sandbox in its place."""
    monkeypatch.setenv("CURIO_EXEC_USER", MISSING_ACCOUNT)
    marker = as_the_account.work / "node-started"
    value, stderr = _ran(_writes_then_returns(marker), as_the_account.work, "WITH_A_MISSING_ACCOUNT")
    assert not marker.exists(), (
        f"Node started, as uid {marker.read_text()}, although the account {MISSING_ACCOUNT} does not exist"
    )
    assert value is None, f"the run gave a result: {value}"
    assert any(MISSING_ACCOUNT in line for line in stderr), f"the run did not say which account is missing: {stderr}"


def test_a_uid_the_kernel_refuses_stops_the_run_before_node_starts(as_the_account, monkeypatch):
    """Where the kernel refuses the drop, here to an account whose ids are
    ``(uid_t) -1``, the wrapper exits before its exec with one line that names
    the id: Node never starts, so it never runs as root in the account's
    place. The sandbox resolves the account by its name, the wrapper takes its
    numbers."""
    import pwd

    real = pwd.getpwnam
    refused = pwd.struct_passwd(
        (REFUSED_ACCOUNT, "x", REFUSED_ID, REFUSED_ID, "", "/nonexistent", "/usr/sbin/nologin")
    )
    monkeypatch.setattr(pwd, "getpwnam", lambda name: refused if name == REFUSED_ACCOUNT else real(name))
    monkeypatch.setenv("CURIO_EXEC_USER", REFUSED_ACCOUNT)
    marker = as_the_account.work / "node-started"
    value, stderr = _ran(_writes_then_returns(marker), as_the_account.work, "WITH_A_REFUSED_UID")
    assert not marker.exists(), (
        f"Node started, as uid {marker.read_text()}, although the kernel refuses the account's ids"
    )
    assert value is None, f"the run gave a result: {value}"
    assert len(stderr) == 1 and str(REFUSED_ID) in stderr[0], (
        f"the wrapper did not say in one line which id it could not drop to: {stderr}"
    )


@pytest.mark.parametrize("isolation, user", [("off", EXEC_USER), ("fork", None)],
                         ids=["isolation off", "no execution user"])
def test_node_stays_the_sandboxs_account_where_an_isolated_child_would(isolation, user, as_the_account,
                                                                       monkeypatch):
    """Node drops only when an isolated child would: not with isolation off,
    the in-process CI stacks' case, whose launcher names the account all the
    same, and not without an execution user. There it runs as the sandbox
    does, here root."""
    monkeypatch.setenv("CURIO_ISOLATION", isolation)
    if user is None:
        monkeypatch.delenv("CURIO_EXEC_USER", raising=False)
    else:
        monkeypatch.setenv("CURIO_EXEC_USER", user)
    status, stderr = _ran(_READS_ITS_STATUS, as_the_account.work, f"STAYS_WITH_ISOLATION_{isolation.upper()}")
    assert status is not None, "\n".join(stderr)
    assert status["Uid"].split() == ["0"] * 4, f"Node dropped to the uids {status['Uid'].split()}"


def test_the_shared_thread_budget_counts_the_node_slots(monkeypatch):
    """Each isolated child's ``RLIMIT_NPROC`` counts every thread of the
    execution account, and Node runs as that account, so Node's threads count
    against it too. The budget the children share is 256 for each isolated
    slot and for each Node slot: each child keeps its 256, and no thread count
    changes."""
    from utk_curio.sandbox.isolation import runner, supervisor

    monkeypatch.delenv("CURIO_EXEC_NPROC", raising=False)
    monkeypatch.setenv("CURIO_EXEC_PARALLELISM", "3")
    monkeypatch.setenv("CURIO_JS_PARALLELISM", "5")
    config = runner.IsolationConfig.from_environment()
    assert config.parallelism == 3
    assert config.limits["nproc"] == supervisor.DEFAULT_LIMITS["nproc"] * (3 + 5), (
        f"the shared thread budget is {config.limits['nproc']}: 256 for each of the 3 isolated slots, "
        f"without the 5 Node slots whose threads count against it"
    )


#: The scenarios of ``test_js_run_kills_at_return.py``, run here with Node as
#: the execution account, each by its own code.
KILL_SCENARIOS = (
    "test_every_process_a_javascript_node_starts_ends_when_it_returns",
    "test_a_process_holding_a_javascript_nodes_output_ends_when_the_node_returns",
    "test_every_process_a_javascript_node_starts_ends_when_it_throws",
    "test_every_process_a_javascript_node_starts_ends_when_it_times_out",
    "test_every_process_a_javascript_node_starts_ends_when_it_returns_without_the_runs_mark",
    "test_no_process_a_javascript_node_starts_can_leave_nodes_process_group",
    "test_a_detached_child_of_a_javascript_node_starts_in_nodes_process_group",
)


@pytest.mark.parametrize("scenario", KILL_SCENARIOS)
def test_every_process_a_javascript_node_starts_ends_with_it_as_the_execution_account(scenario, as_the_account,
                                                                                     monkeypatch):
    # Owner rule, 11-07: every process a node starts ends when the node returns. Never weaken, skip or remove these tests.
    """Each scenario of ``test_js_run_kills_at_return.py``, run by its own code
    with Node as the execution account: what Node starts is the account's
    too, none can leave Node's process group, and the run still kills it all
    when Node ends."""
    record = kills._Record(as_the_account.work / "started.json")
    given = {"record": record, "tmp_path": as_the_account.work, "monkeypatch": monkeypatch}
    scenario_test = getattr(kills, scenario)
    try:
        scenario_test(**{name: given[name] for name in inspect.signature(scenario_test).parameters})
    finally:
        record.kill_the_rest()
