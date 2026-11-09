"""The isolation boundary for a JavaScript node, asserted against a live stack with an execution user.

The JavaScript twin of ``test_exec_user_boundary.py``, which asserts the
boundary for a Python node. A JavaScript node runs in Node.js, which the
sandbox starts for each run (``worker.run_js_script``) through the exec
wrapper of ``isolation/seccomp_filter.py``. Under fork isolation, with an
execution user and a root sandbox, as here and on a deployed stack, the
wrapper drops Node to that account before its exec, as an isolated Python
child drops: no new privileges, the filter, then groups, gid and uid. Node
keeps its network: an Autark data node fetches its files from the backend.

So the same denials are asserted from Node's side: who it runs as, and the
paths it cannot list or open. Two more are Node's own, since a Python child
has no network: the sandbox's token is in no environment Node can read, so
Node cannot call the sandbox as the backend does, and the zygote's socket
refuses it. And Node's packages are readable, never writable, as the Python
twin asserts for a Python node.

Like its twin, it keeps its own literals, so widening hardening's lists cannot
quietly widen these tests, and it imports nothing from the project. It is
skipped unless ``CURIO_LIVE_SANDBOX_URL`` names a running sandbox, so it is
inert in the unit run and does something only in the ``test-exec-user`` job,
through ``/execJs`` with the sandbox's token.
"""

import hashlib
import json
import os
import textwrap
import urllib.error
import urllib.request

import pytest


# As in test_exec_user_boundary.py: not CURIO_SANDBOX_TOKEN, which the parent
# conftest pops for the whole session.
BASE_URL = os.environ.get("CURIO_LIVE_SANDBOX_URL", "").rstrip("/")
TOKEN = os.environ.get("CURIO_LIVE_SANDBOX_TOKEN", "")

# Where the stack was launched inside the container: Node's working directory,
# and what the sensitive paths are relative to.
LAUNCH_DIR = os.environ.get("CURIO_LIVE_LAUNCH_DIR", "/app")

EXEC_USER = os.environ.get("CURIO_LIVE_EXEC_USER", "curio-exec")

NODE_TYPE = "curio.builtin/js-computation"

#: The zygote's socket, where the sandbox keeps it when nothing names another
#: place (``runner.IsolationConfig.from_environment``).
ZYGOTE_SOCKET = LAUNCH_DIR + "/.curio/exec-zygote.sock"

#: Curio's copy of DuckDB's extensions in the image, which the launcher seeds
#: where duckdb-wasm looks for them (``node_runtime.duckdb_extensions_dir``).
VENDORED_EXTENSIONS = LAUNCH_DIR + "/vendor/duckdb-extensions"

pytestmark = pytest.mark.skipif(
    not BASE_URL,
    reason="CURIO_LIVE_SANDBOX_URL is unset; this suite needs a live stack with an execution user",
)


def _request(path, payload=None, *, timeout=180):
    """Call the sandbox, returning the decoded JSON body."""
    url = BASE_URL + path
    data = None
    headers = {}
    method = "GET"
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


def run_js(code, *, timeout=180):
    """Execute *code* as a JavaScript node and return the sandbox's response.

    *code* is a node's code as its author writes it: its ``import`` lines
    first, at the start of their lines, where the worker turns them into
    ``await import()`` calls, then the body of the async function it runs.
    """
    return _request("/execJs", {
        "code": textwrap.dedent(code).strip("\n") + "\n",
        "file_path": "",
        "nodeType": NODE_TYPE,
        "dataType": "",
        "save_dataset": False,
    }, timeout=timeout)


def assert_ran(result, context=""):
    """Fail with the node's own error when it stored no result. A JavaScript
    node's stderr is Node's, which can hold a warning beside a result, so the
    stored result is what says the node ran."""
    if not (result.get("output") or {}).get("path"):
        where = " (%s)" % context if context else ""
        raise AssertionError(
            "the node failed%s:\n%s" % (where, result.get("stderr") or "(no error text)")
        )
    return result


def logged(result):
    """The last line the node logged, as JSON: each node here ends by logging
    what it saw."""
    lines = result.get("stdout") or []
    assert lines, "the node logged nothing: %r" % (result,)
    return json.loads(lines[-1])


# ---------------------------------------------------------------------------
# The stack is what it claims to be
# ---------------------------------------------------------------------------

def test_the_sandbox_reports_fork_isolation():
    """Node drops only under fork isolation, so on a stack that fell back to
    in-process execution every denial below would prove nothing."""
    assert _request("/version").get("isolation") == "fork"


def test_node_runs_as_the_unprivileged_exec_user():
    """The fact every denial below rests on, read from the kernel's own record
    of the process: all four uids the account's, all four gids its group's, no
    supplementary group, and no capability in the effective, permitted or
    ambient set. Node's ``process.getgroups()`` always adds the effective gid,
    so the groups are read from ``/proc/self/status``."""
    result = assert_ran(run_js(r"""
        const fs = require('fs');
        const os = require('os');
        const status = {};
        for (const line of fs.readFileSync('/proc/self/status', 'utf8').split('\n')) {
          const at = line.indexOf(':');
          if (at > 0) status[line.slice(0, at)] = line.slice(at + 1).trim();
        }
        const account = os.userInfo();
        console.log(JSON.stringify({ name: account.username, gid: account.gid, status }));
        return 1;
    """), "reading Node's identity")
    seen = logged(result)
    status = seen["status"]
    assert seen["name"] == EXEC_USER, "Node ran as %r, not %r" % (seen["name"], EXEC_USER)
    uids = status["Uid"].split()
    assert len(uids) == 4 and len(set(uids)) == 1 and uids[0] != "0", (
        "Node's real, effective, saved and filesystem uids are %s" % uids
    )
    assert status["Gid"].split() == [str(seen["gid"])] * 4, (
        "Node's gids are %s, not the account's %s" % (status["Gid"].split(), seen["gid"])
    )
    assert status["Groups"] == "", "Node kept supplementary groups: %r" % status["Groups"]
    for name in ("CapEff", "CapPrm", "CapAmb"):
        assert int(status[name], 16) == 0, "Node holds capabilities: %s %s" % (name, status[name])
    assert status["NoNewPrivs"] == "1", "nothing Node runs is kept from gaining privileges"


# ---------------------------------------------------------------------------
# What Node must still be able to do
# ---------------------------------------------------------------------------

def test_an_ordinary_javascript_node_produces_a_result():
    """The floor: a node that computes and returns, with nothing to read."""
    result = assert_ran(run_js("""
        const total = [1, 2, 3].reduce((sum, n) => sum + n, 0);
        console.log(JSON.stringify(total));
        return total;
    """))
    assert logged(result) == 6


def test_the_bundled_examples_are_readable_by_relative_path():
    """Node's working directory is the launch directory, so a node addresses
    the bundled examples' data as ``docs/examples/data/...``, as a Python node
    does. The tree is root's, so this reads and does not write."""
    result = assert_ran(run_js("""
        const fs = require('fs');
        const listed = fs.readdirSync('docs/examples/data').includes('back_bay.osm.pbf');
        const handle = fs.openSync('docs/examples/data/back_bay.osm.pbf', 'r');
        const read = fs.readSync(handle, Buffer.alloc(16), 0, 16, 0);
        fs.closeSync(handle);
        console.log(JSON.stringify({ listed, read }));
        return 1;
    """), "reading docs/examples/data")
    assert logged(result) == {"listed": True, "read": 16}


def test_autk_db_loads_spatial_and_json_from_curios_copy():
    """autk-db's ``init()`` installs and loads DuckDB's spatial extension, and a
    JSON function loads the json extension. duckdb-wasm's Node worker looks for
    each under ``os.homedir()/.duckdb/extensions/extensions.duckdb.org`` and
    downloads only one that is missing. Both answer the query, and afterwards
    that folder holds Curio's copy and nothing else, each file there before
    the node started: nothing was downloaded."""
    result = assert_ran(run_js(r"""
        import { AutkDb } from '@urban-toolkit/autk-db';
        const crypto = require('crypto');
        const fs = require('fs');
        const os = require('os');
        const path = require('path');
        const started = Date.now();
        const db = new AutkDb();
        await db.init();
        const rows = await db.rawQuery({
          query: "SELECT ST_Contains(ST_GeomFromText('POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))'), ST_Point(3, 4)) AS inside, "
            + "json_extract_string(json_object('city', 'Boston'), '$.city') AS city",
          output: { type: 'RETURN_OBJECT' },
        });
        const files = (root) => fs.readdirSync(root, { recursive: true })
          .map((name) => String(name))
          .filter((name) => fs.statSync(path.join(root, name)).isFile())
          .sort()
          .map((name) => ({
            name: name.split(path.sep).join('/'),
            digest: crypto.createHash('sha256').update(fs.readFileSync(path.join(root, name))).digest('hex'),
            before: fs.lstatSync(path.join(root, name)).mtimeMs < started,
          }));
        const looks = path.join(os.homedir(), '.duckdb', 'extensions', 'extensions.duckdb.org');
        console.log(JSON.stringify({
          rows,
          installed: fs.existsSync(looks) ? files(looks) : null,
          vendored: files(__VENDORED__),
        }));
        return 1;
    """.replace("__VENDORED__", json.dumps(VENDORED_EXTENSIONS)), timeout=600), "querying autk-db")
    seen = logged(result)
    assert seen["rows"] == [{"inside": True, "city": "Boston"}], seen["rows"]
    vendored = {
        entry["name"]: entry["digest"] for entry in seen["vendored"]
        if entry["name"].endswith(".duckdb_extension.wasm")
    }
    names = {name.rsplit("/", 1)[-1] for name in vendored}
    assert {"spatial.duckdb_extension.wasm", "json.duckdb_extension.wasm"} <= names, (
        "Curio's copy of DuckDB's extensions lacks spatial or json: %s" % sorted(vendored)
    )
    assert seen["installed"] is not None, "Node's HOME holds no DuckDB extensions, so duckdb-wasm downloaded them"
    installed = {entry["name"]: entry["digest"] for entry in seen["installed"]}
    assert installed == vendored, (
        "where duckdb-wasm looks are other extensions than Curio's copy, so it downloaded them: "
        "found %s, Curio has %s" % (sorted(installed), sorted(vendored))
    )
    written = [entry["name"] for entry in seen["installed"] if not entry["before"]]
    assert not written, "duckdb-wasm wrote %s while the node ran: it downloaded them" % written


def test_an_autark_data_load_runs_within_its_share_of_threads(record_property):
    """An Autark node whose document only loads data runs on the server as the
    JavaScript ``autk_data_compiler`` compiles: these are its calls for example
    06's loader, the Back Bay extract fetched from the backend's ``/file/``
    over loopback. Node runs as the execution account, whose threads every
    isolated child's ``RLIMIT_NPROC`` counts, so its slot adds 256 to that
    shared budget, and a load ends with fewer threads than that."""
    result = assert_ran(run_js("""
        import { AutkDb } from '@urban-toolkit/autk-db';
        const fs = require('fs');
        const db = new AutkDb();
        await db.init();
        await db.loadOsm({
          pbfFileUrl: '__CURIO_BACKEND_URL__/file/docs/examples/data/back_bay.osm.pbf',
          queryArea: { geocodeArea: 'Boston', areas: ['Back Bay'] },
          outputTableName: 'table_osm',
          autoLoadLayers: { layers: ['surface', 'parks', 'water', 'roads', 'buildings'] },
        });
        const features = {};
        for (const table of db.getLayersMetadata()) {
          features[table.name] = (await db.getLayer(table.name)).features.length;
        }
        console.log(JSON.stringify({ features, threads: fs.readdirSync('/proc/self/task').length }));
        return 1;
    """, timeout=900), "loading example 06's Back Bay extract")
    seen = logged(result)
    record_property("node_threads", seen["threads"])
    assert sorted(seen["features"]) == [
        "table_osm_buildings", "table_osm_parks", "table_osm_roads", "table_osm_surface", "table_osm_water",
    ], seen["features"]
    assert all(count > 0 for count in seen["features"].values()), seen["features"]
    assert seen["threads"] < 256, (
        "an Autark load ended with %d threads, past the 256 its slot adds to the "
        "execution account's budget" % seen["threads"]
    )


#: Node's packages: where a pip install keeps them, which the job's seed step
#: makes, and the image's. Each with a file a reader opens.
NODE_PACKAGES = (
    (LAUNCH_DIR + "/.curio/nodejs", "package.json"),
    (LAUNCH_DIR + "/node_modules", "@urban-toolkit/autk-db/package.json"),
)


def test_nodes_packages_are_readable_and_not_writable():
    """A JavaScript node imports Node's packages, so the account reads them; it
    must never write them, where a module it changed or added would run in
    every later run, and in the backend's own Node, which runs as root. Each
    write tried is a new file of a name of its own, removed if it was made, or
    an open of an existing file that writes nothing."""
    result = assert_ran(run_js(r"""
        const crypto = require('crypto');
        const fs = require('fs');
        const path = require('path');
        const seen = {};
        for (const [folder, member] of __PACKAGES__) {
          const file = path.join(folder, member);
          let read;
          try {
            fs.readdirSync(folder);
            JSON.parse(fs.readFileSync(file, 'utf8'));
            read = 'read';
          } catch (error) {
            read = String(error.code || error);
          }
          const wrote = [];
          for (const where of [...new Set([folder, path.dirname(file)])]) {
            const probe = path.join(where, 'written-by-node-code-' + crypto.randomBytes(8).toString('hex'));
            try {
              fs.closeSync(fs.openSync(probe, 'wx'));
              wrote.push('CREATED ' + probe);
            } catch (error) {
              wrote.push(String(error.code || error));
            } finally {
              fs.rmSync(probe, { force: true });
            }
          }
          try {
            fs.closeSync(fs.openSync(file, 'r+'));
            wrote.push('OPENED FOR WRITING ' + file);
          } catch (error) {
            wrote.push(String(error.code || error));
          }
          seen[folder] = { read, wrote };
        }
        console.log(JSON.stringify(seen));
        return 1;
    """.replace("__PACKAGES__", json.dumps(NODE_PACKAGES))), "reading and writing Node's packages")
    seen = logged(result)
    for folder, member in NODE_PACKAGES:
        assert seen[folder]["read"] == "read", (
            "Node cannot read %s/%s, a package a JavaScript node imports: %s" % (folder, member, seen[folder]["read"])
        )
        assert seen[folder]["wrote"] and set(seen[folder]["wrote"]) == {"EACCES"}, (
            "Node could write %s, so node code could change a module every later run imports: %s"
            % (folder, seen[folder]["wrote"])
        )


# ---------------------------------------------------------------------------
# What Node must not be able to do
# ---------------------------------------------------------------------------

#: Node code that lists __TARGET__ and logs "denied", "missing" or what it saw.
_LISTS = r"""
const fs = require('fs');
let outcome;
try {
  outcome = 'READ ' + JSON.stringify(fs.readdirSync(__TARGET__).slice(0, 5));
} catch (error) {
  outcome = { EACCES: 'denied', ENOENT: 'missing' }[error.code] || String(error.code || error);
}
console.log(JSON.stringify(outcome));
return 1;
"""

#: Node code that opens __TARGET__ and logs "denied", "missing" or what it read.
_OPENS = r"""
const fs = require('fs');
let outcome;
try {
  const handle = fs.openSync(__TARGET__, 'r');
  const head = Buffer.alloc(16);
  const read = fs.readSync(handle, head, 0, 16, 0);
  fs.closeSync(handle);
  outcome = 'READ ' + JSON.stringify(head.subarray(0, read).toString('latin1'));
} catch (error) {
  outcome = { EACCES: 'denied', ENOENT: 'missing' }[error.code] || String(error.code || error);
}
console.log(JSON.stringify(outcome));
return 1;
"""


def _outcome(code, target):
    """What *code*, one of the two above, saw at *target*."""
    result = assert_ran(run_js(code.replace("__TARGET__", json.dumps(target))), "reaching " + target)
    return logged(result)


# (path relative to the launch directory, why it matters). Its own literal, as
# test_exec_user_boundary.py keeps its own.
DENIED = (
    ("instance", "the user database: password hashes and session tokens"),
    (".curio/data", "the artifact store: every session's data"),
    (".curio/users", "every user's imported datasets, projects and packages"),
    ("datasets", "the shared Data Catalog's published files"),
    (".curio/discovery", "the operator's source manifests: each names a folder or host the server reads"),
    (".curio/fetched", "the catalog files a pip install downloaded"),
)


@pytest.mark.parametrize("relative,reason", DENIED, ids=[path for path, _ in DENIED])
def test_a_sensitive_directory_cannot_be_listed(relative, reason):
    """Denied by traversal: no listing, no guessing. Each must exist, or the
    denial would be a missing folder's."""
    target = os.path.join(LAUNCH_DIR, relative)
    outcome = _outcome(_LISTS, target)
    assert outcome != "missing", (
        "%s does not exist, so this test proved nothing. It must exist and be "
        "denied: %s." % (target, reason)
    )
    assert outcome == "denied", "a JavaScript node could read %s (%s): %s" % (target, reason, outcome)


def test_the_user_database_cannot_be_opened():
    """``instance/urban_workflow.db``, which holds every password hash and
    session token, asked for by its name."""
    target = os.path.join(LAUNCH_DIR, "instance", "urban_workflow.db")
    outcome = _outcome(_OPENS, target)
    assert outcome != "missing", (
        "%s does not exist, so this proved nothing; the stack boots with "
        "--deploy, which creates it." % target
    )
    assert outcome == "denied", "a JavaScript node could read %s: %s" % (target, outcome)


def test_another_users_dataset_cannot_be_read_by_absolute_path():
    """The canary the job's seed step plants in another account's folder,
    asked for by its path: knowing a path is the whole threat."""
    target = os.path.join(LAUNCH_DIR, ".curio", "users", "some-other-user", "canary.txt")
    outcome = _outcome(_OPENS, target)
    assert outcome != "missing", (
        "%s was not planted, so this proved nothing. The workflow's seeding "
        "step creates it before the stack boots." % target
    )
    assert outcome == "denied", "a JavaScript node read another user's file: %s" % outcome


def test_the_deployment_secret_cannot_be_read():
    """``.env``, which can hold the deployment's keys and tokens. The job
    plants one, world-readable, for the boot's hardening to close."""
    target = os.path.join(LAUNCH_DIR, ".env")
    outcome = _outcome(_OPENS, target)
    assert outcome != "missing", (
        "%s was not planted, so this proved nothing. The workflow's seeding "
        "step creates it before the stack boots." % target
    )
    assert outcome == "denied", "a JavaScript node could read %s: %s" % (target, outcome)


def test_node_finds_the_sandboxs_token_nowhere_it_can_read():
    """With the sandbox's token and its network, node code could call the
    sandbox as the backend does, and ``/exec`` stages any absolute path it is
    sent, another account's dataset among them. So the token is in no variable
    of Node's own, in no environment of a process Node can read (the sandbox's,
    Node's parent, refuses it), and the sandbox's ``/monitor``, which only the
    token opens, answers Node 401. The token is looked for by the digest of its
    value, so a variable of another name holding it counts too."""
    assert TOKEN, "CURIO_LIVE_SANDBOX_TOKEN is unset, so this test cannot know the token it looks for"
    digest = hashlib.sha256(TOKEN.encode("utf-8")).hexdigest()
    result = assert_ran(run_js(r"""
        const crypto = require('crypto');
        const fs = require('fs');
        const holding = (entries) => entries
          .filter((entry) => entry.indexOf('=') > 0
            && crypto.createHash('sha256').update(entry.slice(entry.indexOf('=') + 1)).digest('hex') === __DIGEST__)
          .map((entry) => entry.slice(0, entry.indexOf('=')));
        const own = holding(Object.entries(process.env).map(([name, value]) => name + '=' + value));
        let parent;
        try {
          fs.readFileSync('/proc/' + process.ppid + '/environ');
          parent = 'READ';
        } catch (error) {
          parent = String(error.code || error);
        }
        const holders = [];
        for (const pid of fs.readdirSync('/proc').filter((name) => /^\d+$/.test(name))) {
          let entries;
          try {
            entries = fs.readFileSync('/proc/' + pid + '/environ', 'latin1').split('\0');
          } catch (error) {
            continue;
          }
          const names = holding(entries);
          if (names.length > 0) holders.push({ pid: Number(pid), names });
        }
        const sandbox = 'http://127.0.0.1:' + (process.env.FLASK_SANDBOX_PORT || '2000');
        const live = (await fetch(sandbox + '/live')).status;
        const headers = process.env.CURIO_SANDBOX_TOKEN ? { 'X-Curio-Sandbox-Token': process.env.CURIO_SANDBOX_TOKEN } : {};
        const monitor = (await fetch(sandbox + '/monitor', { headers })).status;
        console.log(JSON.stringify({ own, parent, holders, live, monitor }));
        return 1;
    """.replace("__DIGEST__", json.dumps(digest))), "looking for the sandbox's token")
    seen = logged(result)
    assert seen["live"] == 200, (
        "Node could not reach the sandbox (/live answered %s), so /monitor's answer would prove nothing"
        % seen["live"]
    )
    assert seen["own"] == [], "Node's own environment holds the sandbox's token: %s" % seen["own"]
    assert seen["parent"] == "EACCES", (
        "Node could read its parent's environment, the sandbox's, which holds the token: %s" % seen["parent"]
    )
    assert seen["holders"] == [], "Node read the sandbox's token in these environments: %s" % seen["holders"]
    assert seen["monitor"] == 401, (
        "the sandbox's /monitor answered Node %s, not 401: Node holds a token that opens it" % seen["monitor"]
    )


def test_node_cannot_connect_to_the_zygotes_socket():
    """The zygote forks every isolated child, and its socket is root's alone
    (0600): whatever reaches it can ask for a run. A trivial Python node
    starts the zygote first, and the socket is looked at before the connect,
    so the refusal is the socket's, not a missing file's. Nothing is written
    on the connection: the zygote reads a request one byte at a time. The
    bucket mounts' control socket rests on the same rule."""
    started = _request("/exec", {
        "code": "    return 1\n",
        "file_path": "",
        "nodeType": "curio.builtin/python-computation",
        "dataType": "",
        "user_key": "ci-exec-user-boundary-js",
        "save_dataset": False,
    })
    assert not started.get("stderr"), "the trivial Python node failed: %s" % started.get("stderr")
    result = assert_ran(run_js("""
        const fs = require('fs');
        const net = require('net');
        let kind;
        try {
          kind = fs.lstatSync(__SOCKET__).isSocket() ? 'socket' : 'not a socket';
        } catch (error) {
          kind = String(error.code || error);
        }
        const outcome = kind !== 'socket' ? null : await new Promise((resolve) => {
          const connection = net.createConnection(__SOCKET__);
          connection.once('connect', () => { connection.destroy(); resolve('CONNECTED'); });
          connection.once('error', (error) => resolve(String(error.code || error)));
        });
        console.log(JSON.stringify({ kind, outcome }));
        return 1;
    """.replace("__SOCKET__", json.dumps(ZYGOTE_SOCKET))), "connecting to the zygote")
    seen = logged(result)
    assert seen["kind"] == "socket", (
        "there is no socket at %s (%s), so this proved nothing" % (ZYGOTE_SOCKET, seen["kind"])
    )
    assert seen["outcome"] == "EACCES", "a JavaScript node reached the zygote's socket: %s" % seen["outcome"]
