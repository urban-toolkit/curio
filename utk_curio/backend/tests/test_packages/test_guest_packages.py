"""``--guest-packages``: the catalog packages every hosted guest has.

A hosted guest (a guest on a Curio started with ``--deploy``) never adds a
package or installs a library (``users.capabilities.install_refusal``), so a
node of a package the shared guest account lacks fails for every guest: on
dev, Track Objects said ``No module named 'sam3_tracking'``. The operator
names the packages every guest has with ``--guest-packages``
(``CURIO_GUEST_PACKAGES``). The start, in the home process's startup work
(``server.py``), puts each into the shared guest's store as an add to all
projects puts it there, with the packages it needs, and into its defaults: a
hosted guest's catalog then lists it added, and a guest's run of its node is
handed its modules. Its libraries are the launcher's to install, with the
examples' (``test_scripts/test_launcher_manifest_deps.py``), so the start runs
no pip. Without the flag the start leaves the account as it was.

Also here: a hosted guest's account-wide changes to the shared account's
packages are refused (``capabilities.catalog_entry_refusal``), as its changes
to the account's Data Catalog are (``test_projects/test_guest_store_leaks.py``):
add to all projects, remove from all projects, remove from the account and a
package's details. Each changed what every guest's account holds, so one guest
could take a guest package away from every other.

The packages are this module's own, in a catalog of its own. The start is the
server module run as the launcher runs it, every other piece of its startup
work replaced by a record of its call, as ``test_backend_startup_once.py``
runs it. New code is reached only inside each test, so a checkout without it
fails each test on its own.
"""

from __future__ import annotations

import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

from utk_curio.backend import config
from utk_curio.backend.app.common.user_storage import GUEST_KEY, users_base
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.packages.repositories import defaults as defaults_io
from utk_curio.backend.app.packages.repositories.store import package_dir, user_packages_dir
from utk_curio.backend.tests.test_scripts import test_backend_startup_once as startup_once

#: The piece of the startup work this module runs for real.
GUEST_PIECE = "utk_curio.backend.app.packages.service.add_guest_packages"

TRACKER_NODE = "ai.test.tracker/track"

REFUSAL = (
    "Guests on this Curio cannot {action}, because every guest shares one account. "
    "Sign in with an account to {action}."
)


def _manifest(package_id: str, version: str, needs: dict, python: dict) -> dict:
    return {
        "id": package_id,
        "version": version,
        "name": package_id,
        "publisher": "Test",
        "description": "Test package",
        "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
        "permissions": [],
        "dependencies": {"packages": dict(needs), "python": dict(python), "js": {}},
        "createdAt": "2026-06-01T12:00:00Z",
        "templates": [{
            "id": "track",
            "label": "Track",
            "category": "computation",
            "engine": "python",
            "editor": "code",
            "hasCode": True,
            "hasWidgets": False,
            "hasGrammar": False,
            "inputPorts": [],
            "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
            "source": "sources/track.py",
        }],
    }


def _publish(
    catalog: Path, package_id: str, *, version: str = "1.0.0",
    needs: dict | None = None, python: dict | None = None, module: str | None = None,
) -> str:
    """Write the package ``<package_id>@1`` into *catalog*: its node, and the
    module *module* beside it in ``sources/``. Answers its dirName."""
    dir_name = f"{package_id}@1"
    root = catalog / dir_name
    (root / "sources").mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps(_manifest(package_id, version, needs or {}, python or {})), encoding="utf-8",
    )
    (root / "sources" / "track.py").write_text("return 1\n", encoding="utf-8")
    if module:
        (root / "sources" / f"{module}.py").write_text(f"def helped():\n    return {module!r}\n", encoding="utf-8")
    return dir_name


@pytest.fixture()
def catalog(tmp_path, monkeypatch) -> Path:
    """A shared catalog holding this module's packages and nothing else."""
    root = tmp_path / "catalog"
    root.mkdir()
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(root))
    return root


@pytest.fixture()
def hosted_guest(db, monkeypatch) -> dict:
    """The shared guest signed in on a Curio started with ``--deploy``: the
    auth headers of its sign-in."""
    from utk_curio.backend.app.users.models import User, UserSession

    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    guest = User(username=config.CURIO_SHARED_GUEST_USERNAME, name="Shared Guest", is_guest=True)
    db.session.add(guest)
    db.session.flush()
    db.session.add(UserSession(user_id=guest.id, token="hosted-guest-token"))
    db.session.commit()
    return {"Authorization": "Bearer hosted-guest-token", "Content-Type": "application/json"}


@pytest.fixture()
def start(app, monkeypatch):
    """Start the backend as the launcher does, ``python -m backend.server`` up
    to where it would serve, with ``--guest-packages`` naming the folders
    given: the home process, no reloader. Every other piece of the startup
    work answers as a record of its call, and the shared guest's store key is
    ``guest``. Each stand-in is taken back once the start is over."""
    from flask_socketio import SocketIO

    def run(*names: str) -> None:
        with monkeypatch.context() as patch:
            for name, answer in startup_once.STARTUP_WORK.items():
                if name != GUEST_PIECE:
                    patch.setattr(name, lambda *args, _answer=answer, **kwargs: _answer)
            patch.setattr("utk_curio.backend.app.projects.services._user_dir_key", lambda user: GUEST_KEY)
            patch.setattr(config, "CURIO_GUEST_PACKAGES", tuple(names), raising=False)
            patch.setattr("utk_curio.backend.thread_stacks.register", lambda: True)
            patch.setattr(
                "utk_curio.sandbox.util.duckdb_threads.release_default_connection", lambda *args, **kwargs: None,
            )
            patch.setattr(SocketIO, "run", lambda *args, **kwargs: None)
            for variable in ("CURIO_BACKEND_PROCESS", "CURIO_BACKEND_PROCESSES", "WERKZEUG_RUN_MAIN"):
                patch.delenv(variable, raising=False)
            patch.setenv("FLASK_USE_RELOADER", "0")
            runpy.run_module("utk_curio.backend.server", run_name="__main__")

    return run


@pytest.fixture()
def pip_runs(monkeypatch) -> list[str]:
    """Every pip run and import probe asked for, by kind."""
    from utk_curio.backend.app.packages.infrastructure import pip_runner
    from utk_curio.backend.app.packages.infrastructure.pip_runner import InstallReport

    runs: list[str] = []

    def recorded(kind: str, answer):
        def record(*args, **kwargs):
            runs.append(kind)
            return answer
        return record

    monkeypatch.setattr(pip_runner, "install_python_deps", recorded("install", InstallReport(installed=[], skipped=[])))
    monkeypatch.setattr(
        pip_runner, "install_python_deps_to_target", recorded("install into a tree", InstallReport(installed=[], skipped=[])),
    )
    monkeypatch.setattr(pip_runner, "import_failures", recorded("import probe", {}))
    monkeypatch.setattr(pip_runner, "import_failures_in", recorded("import probe of a tree", {}))
    return runs


def _store() -> set[str]:
    """The packages the shared guest's store holds."""
    base = user_packages_dir(GUEST_KEY)
    if not base.is_dir():
        return set()
    return {entry.name for entry in base.iterdir() if entry.is_dir() and PACKAGE_DIR_RE.match(entry.name)}


def _guest_files() -> dict[str, bytes]:
    """Every file of the shared guest's account, by its path in it."""
    root = users_base() / GUEST_KEY
    if not root.is_dir():
        return {}
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def _sources(dir_name: str, *names: str) -> dict:
    """What a run of a node of *dir_name* is handed of that package, in the guest's store."""
    return {"root": str(package_dir(GUEST_KEY, dir_name) / "sources"), "names": list(names)}


def _manifest_version(dir_name: str) -> str:
    return json.loads((package_dir(GUEST_KEY, dir_name) / "manifest.json").read_text(encoding="utf-8"))["version"]


class _Reply:
    status_code = 200

    def json(self):
        return {"stdout": [], "stderr": "", "output": {"path": "art-1", "dataType": "int"}}


def _sandbox_bodies(monkeypatch) -> list:
    """What the backend sends the sandbox, by route, for every run asked."""
    sent: list = []

    def fake(method, path, **kwargs):
        sent.append((path, json.loads(kwargs["data"])))
        return _Reply()

    monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", fake)
    return sent


def _play(client, headers: dict, node_type: str):
    """A hosted guest's Play of a node of *node_type* on a canvas of its own."""
    return client.post("/processPythonCode", data=json.dumps({
        "code": "    return 1\n", "nodeType": node_type, "nodeId": "n1",
        "input": {"path": "", "dataType": "str"}, "saveOutputDataset": False,
    }), headers=headers)


def _defaults(client, headers: dict) -> list[str]:
    resp = client.get("/api/packages/defaults", headers=headers)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["packages"]


def _catalog_rows(client, headers: dict) -> dict:
    resp = client.get("/api/packages/catalog", headers=headers)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return {row["dirName"]: row for row in resp.get_json()["packages"]}


def _held(client, headers: dict) -> list[str]:
    resp = client.get("/api/packages", headers=headers)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return [row["dirName"] for row in resp.get_json()["packages"]]


# ---------------------------------------------------------------------------
# With the flag
# ---------------------------------------------------------------------------

def test_after_the_start_a_hosted_guests_catalog_lists_the_package_added(catalog, start, client, hosted_guest):
    tracker = _publish(catalog, "ai.test.tracker", module="tracker_helpers")

    start(tracker)

    assert tracker in _defaults(client, hosted_guest), "the catalog pages read the defaults as added"
    assert _catalog_rows(client, hosted_guest)[tracker]["installed"] is True
    assert tracker in _held(client, hosted_guest)


def test_after_the_start_a_hosted_guests_run_of_its_node_is_handed_the_packages_modules(
    catalog, start, client, hosted_guest, monkeypatch,
):
    tracker = _publish(catalog, "ai.test.tracker", module="tracker_helpers")
    start(tracker)
    sent = _sandbox_bodies(monkeypatch)

    resp = _play(client, hosted_guest, TRACKER_NODE)

    assert resp.status_code == 200, resp.get_data(as_text=True)
    ((path, body),) = sent
    assert path == "/exec"
    assert body.get("package_modules") == _sources(tracker, "tracker_helpers"), (
        "a hosted guest's run of the package's node was not handed its modules, so its import fails "
        "as it fails for a package the account lacks"
    )


def test_the_packages_a_guest_package_needs_come_with_it(catalog, start, client, hosted_guest, monkeypatch):
    base = _publish(catalog, "ai.test.tracking-base", module="tracking_base")
    tracker = _publish(catalog, "ai.test.tracker", needs={base: "*"}, module="tracker_helpers")

    start(tracker)

    assert {base, tracker} <= _store(), _store()
    assert {base, tracker} <= set(_defaults(client, hosted_guest))
    sent = _sandbox_bodies(monkeypatch)
    assert _play(client, hosted_guest, TRACKER_NODE).status_code == 200
    ((_path, body),) = sent
    assert body.get("package_modules") == [
        _sources(tracker, "tracker_helpers"),
        _sources(base, "tracking_base"),
    ]


def test_the_start_installs_no_library_and_runs_no_import_probe(catalog, start, pip_runs):
    """The libraries are the launcher's to install, at launch, into the
    interpreter every account's nodes import from."""
    tracker = _publish(catalog, "ai.test.tracker", python={"inflection": ">=0.5"}, module="tracker_helpers")

    start(tracker)

    assert tracker in _store(), "the start did not add the package"
    assert pip_runs == []


def test_a_name_no_catalog_package_has_is_left_out_and_the_others_are_added(catalog, start):
    """The launcher refuses such a name; the backend's start, handed one all
    the same, still adds the others."""
    tracker = _publish(catalog, "ai.test.tracker", module="tracker_helpers")

    start("ai.test.nowhere@1", tracker)

    assert _store() == {tracker}
    assert defaults_io.load_defaults(GUEST_KEY) == {tracker}


def test_the_guests_copy_is_the_catalogs_which_an_upgrade_of_the_catalog_reaches(catalog, start):
    """As an add's copy is: the seeder replaces a catalog copy nobody changed
    when the catalog moves on (#194), so a release's fix reaches the guests."""
    from utk_curio.backend.app.packages.service import seed_dev_packages

    tracker = _publish(catalog, "ai.test.tracker", version="1.0.0", module="tracker_helpers")
    start(tracker)
    _publish(catalog, "ai.test.tracker", version="1.1.0", module="tracker_helpers")

    seed_dev_packages(user_key=GUEST_KEY)

    assert _manifest_version(tracker) == "1.1.0"


# ---------------------------------------------------------------------------
# Without the flag
# ---------------------------------------------------------------------------

def test_without_the_flag_the_start_leaves_the_guests_account_as_it_was(
    catalog, start, client, hosted_guest, monkeypatch,
):
    tracker = _publish(catalog, "ai.test.tracker", module="tracker_helpers")
    before = _guest_files()

    start()

    assert _guest_files() == before
    assert tracker not in _defaults(client, hosted_guest)
    assert _catalog_rows(client, hosted_guest)[tracker]["installed"] is False
    sent = _sandbox_bodies(monkeypatch)
    assert _play(client, hosted_guest, TRACKER_NODE).status_code == 200
    ((_path, body),) = sent
    assert "package_modules" not in body


# ---------------------------------------------------------------------------
# Also here: a hosted guest changes none of the shared account's packages
# ---------------------------------------------------------------------------

@pytest.fixture()
def shared_account(catalog, client, hosted_guest, monkeypatch):
    """The shared guest's account as a start with the flag leaves it: a guest
    package in its store and its defaults, another package its store holds
    that no default names, and a dataflow of its own, which every hosted guest
    opens. A hosted guest saves no dataflow, so this one is saved as the local
    guest saves one, with sign-in off; the test runs with sign-in on."""
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory

    tracker = _publish(catalog, "ai.test.tracker", module="tracker_helpers")
    other = _publish(catalog, "ai.test.other", module="other_helpers")
    install_package_from_directory(GUEST_KEY, catalog / tracker)
    install_package_from_directory(GUEST_KEY, catalog / other)
    defaults_io.add_to_defaults(GUEST_KEY, tracker)
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
    created = client.post(
        "/api/projects",
        json={"name": "example", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []},
        headers=hosted_guest,
    )
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    assert created.status_code == 201, created.get_data(as_text=True)
    return SimpleNamespace(tracker=tracker, other=other)


ACCOUNT_WIDE_WRITES = [
    pytest.param("POST", "/api/packages/defaults", "other", "add packages to all projects",
                 id="add-to-all-projects"),
    pytest.param("DELETE", "/api/packages/defaults/{tracker}", None, "remove packages from all projects",
                 id="remove-from-all-projects"),
    pytest.param("DELETE", "/api/packages/{tracker}?unusedOnly=true", None, "remove packages from the account",
                 id="remove-from-the-account-when-unused"),
    pytest.param("DELETE", "/api/packages/{tracker}", None, "remove packages from the account",
                 id="remove-from-the-account"),
    pytest.param("PATCH", "/api/packages/{other}", {"description": "Changed by one guest"},
                 "change a package's details", id="change-its-details"),
]


@pytest.mark.parametrize("method, path, body, action", ACCOUNT_WIDE_WRITES)
def test_a_hosted_guest_changes_none_of_the_shared_accounts_packages(
    method, path, body, action, client, hosted_guest, shared_account,
):
    url = path.format(tracker=shared_account.tracker, other=shared_account.other)
    payload = {"dirName": shared_account.other} if body == "other" else body
    before = _guest_files()

    resp = client.open(url, method=method, json=payload, headers=hosted_guest)

    assert resp.status_code == 403, resp.get_data(as_text=True)
    assert resp.get_json()["error"] == REFUSAL.format(action=action)
    assert _guest_files() == before, "a refused change still changed the shared guest's account"


def test_without_deploy_the_shared_guest_still_adds_a_package_to_all_projects(
    client, hosted_guest, shared_account, monkeypatch,
):
    """The control: without ``--deploy`` the shared guest is the one local
    user, whose account is its own."""
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)

    resp = client.post("/api/packages/defaults", json={"dirName": shared_account.other}, headers=hosted_guest)

    assert resp.status_code == 201, resp.get_data(as_text=True)
    assert shared_account.other in defaults_io.load_defaults(GUEST_KEY)
