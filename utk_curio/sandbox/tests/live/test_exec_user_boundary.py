"""The isolation boundary, asserted against a live stack running --exec-user.

Every other isolation test runs its children as **root**, and root ignores mode
bits. ``test_isolation_linux.py`` builds its own workspace and drops privileges
by hand; the ``test-gpu-isolated`` CI job boots ``--isolation fork`` with no
exec user at all, because setting one hardens ``.curio/data`` and the e2e
harness writes its ground truth there from the host process. So the filesystem
half of the boundary -- the part that only exists when the child is an
unprivileged account -- had no end-to-end coverage, and two of the defects
found on this branch lived precisely in that gap:

* the artifact store was hardened by *file* mode, so a staged input, which
  reaches the child as a **hardlink** and therefore shares its source's inode,
  arrived 0600 root-owned and unreadable. Every dataframe node would have
  failed under an exec user.
* ``confine`` chdir'd into a scratch directory that lived *inside* the store,
  which hardening had just made 0700 root-owned, so no node could have run.

Both were found by reading and by a deployed stack, not by CI. This module
closes that: it drives the real HTTP API of a stack booted exactly the way
``docker-compose.deploy.yml`` boots one, and asserts what the child can and
cannot reach from the other side of the fork.

It is skipped unless ``CURIO_LIVE_SANDBOX_URL`` names a running sandbox, so it
is inert during the ordinary unit run (``scripts/test.sh``, which collects this
whole tree) and only does anything in the ``test-gpu-exec-user`` job.

Note the deliberate asymmetry with the unit suites: nothing here reaches into
the container's filesystem or reads a log. The only channel is the API a node
actually executes through, because a boundary that holds under inspection but
not under ``/exec`` is not a boundary.
"""

import json
import os
import textwrap
import urllib.error
import urllib.request

import pytest


# Deliberately NOT ``CURIO_SANDBOX_TOKEN``. The parent conftest pops that name
# for the whole session so the in-container unit suite reaches the sandbox's
# unauthenticated local mode, and this module needs a value that survives.
BASE_URL = os.environ.get("CURIO_LIVE_SANDBOX_URL", "").rstrip("/")
TOKEN = os.environ.get("CURIO_LIVE_SANDBOX_TOKEN", "")

# Where the stack was launched inside the container, i.e. what
# ``CURIO_LAUNCH_CWD`` holds and what the sensitive paths are relative to. The
# child's cwd is its own work directory, not this, so every path a test wants
# denied has to be absolute or the failure would just be "no such file" and
# would pass for the wrong reason.
LAUNCH_DIR = os.environ.get("CURIO_LIVE_LAUNCH_DIR", "/app")

EXEC_USER = os.environ.get("CURIO_LIVE_EXEC_USER", "curio-exec")

# An arbitrary but fixed storage key. ``/exec`` only uses it to name the work
# directory, and using one value throughout means the tests exercise the
# persistent-directory path rather than creating a fresh one each time.
USER_KEY = "ci-exec-user-boundary"

NODE_TYPE = "curio.builtin/computation-analysis"

pytestmark = pytest.mark.skipif(
    not BASE_URL,
    reason="CURIO_LIVE_SANDBOX_URL is unset; this suite needs a live --exec-user stack",
)


def _request(path, payload=None, *, method="GET", timeout=180):
    """Call the sandbox, returning the decoded JSON body."""
    url = BASE_URL + path
    data = None
    headers = {}
    if TOKEN:
        headers["X-Curio-Sandbox-Token"] = TOKEN
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise AssertionError(
            "%s %s returned %s: %s" % (method, path, exc.code, body)
        ) from exc


def run_node(code, *, file_path="", data_type="", user_key=USER_KEY,
             save_dataset=False):
    """Execute *code* as a Python node and return the sandbox's response.

    ``code`` is written here as an ordinary top-level snippet and indented on
    the way out, because the worker drops it into ``def userCode(arg):`` --
    see ``worker.execute_code``. Its input, when there is one, arrives as
    ``arg``.
    """
    body = textwrap.indent(textwrap.dedent(code).strip("\n"), "    ")
    return _request("/exec", {
        "code": body + "\n",
        "file_path": file_path,
        "nodeType": NODE_TYPE,
        "dataType": data_type,
        "user_key": user_key,
        "save_dataset": save_dataset,
    })


def assert_ran(result, context=""):
    """Fail with the node's own stderr when it did not complete."""
    if result.get("stderr"):
        where = " (%s)" % context if context else ""
        raise AssertionError(
            "the node failed%s:\n%s" % (where, result["stderr"])
        )
    return result


def printed(result):
    """The node's stdout as a single string."""
    return "\n".join(result.get("stdout") or [])


# ---------------------------------------------------------------------------
# The stack is what it claims to be
# ---------------------------------------------------------------------------

def test_the_sandbox_reports_fork_isolation():
    """A silently degraded boot would make every assertion below vacuous.

    Without this, a stack that fell back to in-process execution -- no fork
    available, pyseccomp missing -- would run every test here as the sandbox's
    own root user and pass the ones that matter for entirely the wrong reason.
    """
    assert _request("/version").get("isolation") == "fork"


def test_node_code_runs_as_the_unprivileged_exec_user():
    """The single fact the whole permissions model rests on.

    Every denial below is meaningless if the child is root, because root reads
    through any mode bits. This is the assertion CI has never made: the
    isolated job's children *are* root.
    """
    result = assert_ran(run_node("""
        import os, pwd
        print(pwd.getpwuid(os.getuid()).pw_name)
        print(os.getuid())
    """))
    name, uid = printed(result).splitlines()
    assert name == EXEC_USER, "the child ran as %r, not %r" % (name, EXEC_USER)
    assert int(uid) != 0, "the child still has uid 0"


# ---------------------------------------------------------------------------
# What the child must still be able to do
# ---------------------------------------------------------------------------

def test_an_ordinary_node_produces_a_result():
    """The floor. Hardening that denies the child its own workspace shows up
    here first, and did: the scratch root used to live inside ``.curio/data``,
    which hardening set to 0700 root-owned, so ``confine``'s final chdir failed
    and no node could run at all."""
    result = assert_ran(run_node("""
        import pandas as pd
        frame = pd.DataFrame({"n": [1, 2, 3]})
        print(int(frame["n"].sum()))
    """))
    assert printed(result).strip() == "6"


def test_a_staged_dataframe_input_reaches_the_child():
    """A hardlinked input, read by an unprivileged child. Defect 2 exactly.

    ``stage_input`` hardlinks ``.curio/data/artifacts/<id>.parquet`` into the
    scratch directory, and a hardlink shares its source's inode -- so while the
    store's *files* were being chmod'd to 0600 root-owned, the staged copy was
    too, and the child could not read its own input. The fix made the
    *directory* the control (``hardening.HARDLINK_SOURCES``); this is the test
    that would have caught the original.
    """
    produced = assert_ran(run_node("""
        import pandas as pd
        return pd.DataFrame({"n": [1, 2, 3, 4]})
    """, save_dataset=True), "producing the upstream dataframe")

    artifact_id = produced["output"]["path"]
    assert artifact_id, (
        "the upstream node stored nothing: %r" % (produced["output"],)
    )

    consumed = assert_ran(run_node("""
        print(len(arg))
        print(int(arg["n"].sum()))
    """, file_path=artifact_id, data_type=produced["output"]["dataType"]),
        "consuming the staged dataframe")

    rows, total = printed(consumed).splitlines()
    assert (int(rows), int(total)) == (4, 10)


def test_the_work_directory_is_writable_and_owned_by_the_exec_user():
    """The one place an isolated node may write, and it must actually own it.

    Root-owned would make every relative write in node code fail; anything
    looser than 0700 would put one user's work in reach of the next, which the
    shared uid already makes delicate enough.
    """
    result = assert_ran(run_node("""
        import os, stat
        with open("written-by-the-node.txt", "w") as handle:
            handle.write("ok")
        print(open("written-by-the-node.txt").read())
        info = os.stat(".")
        print(oct(stat.S_IMODE(info.st_mode)))
        print(info.st_uid == os.getuid())
    """))
    content, mode, owned = printed(result).splitlines()
    assert content == "ok"
    assert mode == "0o700", "the work directory is %s, not 0o700" % mode
    assert owned == "True", "the work directory is not owned by the execution user"


def test_the_bundled_examples_are_still_readable():
    """Defect 3's fix, from the child's side.

    ``confine`` chdirs off the launch directory, so
    ``gpd.read_file("docs/examples/data/...")`` -- how every bundled example
    addresses its data -- resolves to nothing unless the work directory carries
    the ``docs`` symlink ``prepare_user_work_dir`` drops in. Reading through it
    is the point: it is a link into a root-owned tree, so it reads and does not
    write.
    """
    result = assert_ran(run_node("""
        import os
        print(os.path.isdir("docs/examples"))
    """))
    assert printed(result).strip() == "True", (
        "the work directory has no traversable docs/ link, so every bundled "
        "example's relative read would fail"
    )


# ---------------------------------------------------------------------------
# What the child must not be able to do
# ---------------------------------------------------------------------------

# (path relative to the launch directory, why it matters). Mirrors
# hardening.SENSITIVE_PATHS; kept as a separate literal on purpose, so that
# widening that tuple cannot quietly widen the test that guards it.
DENIED = (
    ("instance", "the user database: password hashes and session tokens"),
    (".curio/data", "the artifact store: every session's data"),
    (".curio/users", "every user's imported datasets, projects and packages"),
    ("datasets", "the shared Data Catalog's published files"),
)


@pytest.mark.parametrize("relative,reason", DENIED,
                         ids=[path for path, _ in DENIED])
def test_a_sensitive_directory_cannot_be_listed(relative, reason):
    """Denied by *traversal*, which is the model: no listing, no guessing.

    A node reaching these needs neither an exploit nor a syscall seccomp could
    filter -- ``open()`` is what a data node legitimately does all day. So the
    check has to be that the path cannot be walked at all.
    """
    target = os.path.join(LAUNCH_DIR, relative)
    result = run_node("""
        import os
        try:
            entries = os.listdir(%r)
        except PermissionError:
            print("denied")
        except FileNotFoundError:
            print("missing")
        else:
            print("READ " + repr(entries[:5]))
    """ % target)
    assert_ran(result, "listing " + target)
    outcome = printed(result).strip()
    assert outcome != "missing", (
        "%s does not exist, so this test proved nothing. It must exist and be "
        "denied -- %s." % (target, reason)
    )
    assert outcome == "denied", (
        "an isolated node could read %s (%s): %s" % (target, reason, outcome)
    )


def test_the_user_database_cannot_be_opened():
    """The listing test above proves the directory is closed; this proves the
    file behind it is unreachable even to a caller that already knows its name,
    which is the case that actually matters. ``instance/urban_workflow.db``
    holds every password hash and session token."""
    target = os.path.join(LAUNCH_DIR, "instance", "urban_workflow.db")
    result = run_node("""
        try:
            with open(%r, "rb") as handle:
                handle.read(16)
        except PermissionError:
            print("denied")
        except FileNotFoundError:
            print("missing")
        else:
            print("READ")
    """ % target)
    assert_ran(result, "opening " + target)
    outcome = printed(result).strip()
    assert outcome != "missing", (
        "%s does not exist, so this proved nothing; the stack boots with "
        "--auth, which creates it." % target
    )
    assert outcome == "denied", "an isolated node could read " + target


def test_another_users_dataset_cannot_be_read_by_absolute_path():
    """Defect 5, verbatim: reading another user's data by a path you know.

    ``SENSITIVE_PATHS`` used to cover ``instance/`` and ``.curio/data`` only,
    so an isolated node could open ``.curio/users/<someone else>/...`` directly
    and skip the permission check ``resolve_execution_paths`` performs on the
    way in. Knowing the path is the whole threat -- storage keys are not
    secrets -- so the listing test above is not sufficient on its own: this
    asks for the file by name.

    The canary is planted by the workflow before the stack boots, because an
    empty directory cannot demonstrate that it is closed.
    """
    target = os.path.join(LAUNCH_DIR, ".curio", "users",
                          "some-other-user", "canary.txt")
    result = run_node("""
        try:
            print("READ " + open(%r).read().strip())
        except PermissionError:
            print("denied")
        except FileNotFoundError:
            print("missing")
    """ % target)
    assert_ran(result, "reading " + target)
    outcome = printed(result).strip()
    assert outcome != "missing", (
        "%s was not planted, so this proved nothing. The workflow's seeding "
        "step creates it before the stack boots." % target
    )
    assert outcome == "denied", (
        "an isolated node read another user's file: %s" % outcome
    )


def test_the_deployment_secret_cannot_be_read():
    """``.env`` carries SECRET_KEY, which forges sessions. Unlike the paths
    above it is a plain file with no directory to hide behind, so it is
    hardened by mode -- and unlike them it legitimately may not exist, since a
    CI stack has no .env. Skip rather than pass in that case: a test that
    silently proves nothing is worse than an absent one."""
    target = os.path.join(LAUNCH_DIR, ".env")
    result = run_node("""
        import os
        if not os.path.exists(%r):
            print("absent")
        else:
            try:
                open(%r).read(1)
            except PermissionError:
                print("denied")
            else:
                print("READ")
    """ % (target, target))
    assert_ran(result, "reading " + target)
    outcome = printed(result).strip()
    if outcome == "absent":
        pytest.skip("this stack has no .env, so there is nothing to deny")
    assert outcome == "denied", "an isolated node could read " + target
