"""Where the launcher installs the sandbox's Node.js packages, and where the
sandbox and the backend read them: beside Curio's package.json in a clone, and
in ``.curio/nodejs`` for a pip install, whose site-packages holds none.

npm never runs here (``subprocess.run`` is replaced), Node never starts
(``Popen`` is replaced), and no test opens a socket. Every tree is built under
``tmp_path``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from utk_curio.cli import dependencies
from utk_curio.cli.frontend_build import NODE_MAJOR, NODE_STAMP

REPO = Path(__file__).resolve().parents[4]
AUTK_DB = "@urban-toolkit/autk-db"
OSM = "source.osm.openstreetmap@1"

#: Curio's package.json, as a clone holds it and a pip install ships it.
PACKAGE_JSON = {
    "name": "curio",
    "private": True,
    "engines": {"node": f"^{NODE_MAJOR}"},
    "dependencies": {AUTK_DB: "4.0.0", "web-worker": "^1.5.0"},
}
LOCKFILE = {
    "name": "curio",
    "lockfileVersion": 3,
    "requires": True,
    "packages": {"": {"name": "curio", "dependencies": PACKAGE_JSON["dependencies"]}},
}


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _is_curios(package_json: Path) -> bool:
    """*package_json* is Curio's own: named curio, with autk-db among its dependencies."""
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return data.get("name") == "curio" and AUTK_DB in (data.get("dependencies") or {})


def _project(cmd, cwd) -> Path:
    """The folder an npm call was pointed at: its ``--prefix``, else where it ran."""
    if "--prefix" in cmd:
        return Path(cmd[cmd.index("--prefix") + 1])
    return Path(cwd)


@pytest.fixture
def npm(monkeypatch):
    """npm on PATH and Node at the major Curio targets, every npm call recorded
    instead of run, and what the launcher reports. An install leaves an
    autk-db in the node_modules of the folder npm was pointed at, as npm would."""
    record = SimpleNamespace(calls=[], errors=[], warnings=[])

    def run(cmd, **kwargs):
        cwd = kwargs.get("cwd")
        record.calls.append((list(cmd), cwd))
        package = _project(cmd, cwd) / "node_modules" / "@urban-toolkit" / "autk-db"
        _write_json(package / "package.json", {"name": AUTK_DB, "version": "4.0.0", "main": "index.js"})
        (package / "index.js").write_text("export const installed = true;\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(dependencies.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(dependencies, "_read_node_version", lambda: (f"v{NODE_MAJOR}.0.0", NODE_MAJOR))
    monkeypatch.setattr(dependencies.subprocess, "run", run)
    monkeypatch.setattr(dependencies, "log_error", lambda message, *a, **k: record.errors.append(str(message)))
    monkeypatch.setattr(dependencies, "log_warning", lambda message, *a, **k: record.warnings.append(str(message)))
    return record


@pytest.fixture
def launch(tmp_path, monkeypatch):
    """The folder Curio is started from. Its state directory is ``.curio`` there."""
    folder = tmp_path / "launch"
    folder.mkdir()
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(folder))
    monkeypatch.delenv("CURIO_STATE_DIR", raising=False)
    monkeypatch.delenv("CURIO_SKIP_DEP_INSTALL", raising=False)
    return folder


@pytest.fixture
def pip_install(tmp_path, launch):
    """Curio installed by pip into a conda environment that has conda's
    Node.js: npm in ``<env>/lib/node_modules``, site-packages under
    ``<env>/lib``, and in it ``utk_curio/`` with the package.json and
    package-lock.json the package ships. site-packages holds no package.json."""
    lib = tmp_path / "env" / "lib"
    _write_json(lib / "node_modules" / "npm" / "package.json", {"name": "npm", "version": "11.19.1"})
    site = lib / "python3.12" / "site-packages"
    shipped = site / "utk_curio" / "sandbox" / "nodejs"
    _write_json(shipped / "package.json", PACKAGE_JSON)
    _write_json(shipped / "package-lock.json", LOCKFILE)
    return SimpleNamespace(site=site, lib=lib, shipped=shipped, folder=launch / ".curio" / "nodejs")


@pytest.fixture
def checkout(tmp_path, launch):
    """A clone, laid out as the Docker image has it too: Curio's package.json
    and package-lock.json beside ``utk_curio/``."""
    root = tmp_path / "curio"
    (root / "utk_curio").mkdir(parents=True)
    _write_json(root / "package.json", PACKAGE_JSON)
    _write_json(root / "package-lock.json", LOCKFILE)
    return root


def test_a_pip_install_runs_npm_only_in_a_folder_holding_curios_package_json(pip_install, npm):
    """npm runs only in ``.curio/nodejs``, with that folder as ``--prefix``,
    after the launcher writes the package.json and package-lock.json the
    package ships there."""
    dependencies._ensure_root_node_modules(str(pip_install.site))

    assert npm.calls, f"no npm install ran; the launcher said {npm.errors + npm.warnings}"
    for cmd, cwd in npm.calls:
        project = _project(cmd, cwd)
        assert _is_curios(project / "package.json"), (
            f"npm install ran in {project}, which holds no package.json of Curio's (a pip "
            f"install's site-packages). npm then takes the nearest folder above that holds a "
            f"package.json or a node_modules as its project, {pip_install.lib} in a conda "
            f"environment, and empties its node_modules, conda's npm with it. Command: {cmd}"
        )
        assert "--prefix" in cmd and Path(cwd).resolve() == project.resolve(), (
            f"npm ran in {cwd} as {cmd}, without that folder as --prefix"
        )
    assert [_project(cmd, cwd).resolve() for cmd, cwd in npm.calls] == [pip_install.folder.resolve()]
    for name in ("package.json", "package-lock.json"):
        assert (pip_install.folder / name).read_bytes() == (pip_install.shipped / name).read_bytes(), name
    assert (pip_install.lib / "node_modules" / "npm" / "package.json").is_file()
    assert npm.errors == []


@pytest.mark.parametrize("missing", ["package.json", "package-lock.json"])
def test_a_pip_install_that_ships_no_package_json_says_so_and_runs_no_npm(pip_install, npm, missing):
    """Without a shipped file, the launcher names it and what fails, and runs
    no npm."""
    (pip_install.shipped / missing).unlink()

    dependencies._ensure_root_node_modules(str(pip_install.site))

    assert npm.calls == [], f"npm ran with no package.json of Curio's to install from: {npm.calls}"
    said = "\n".join(npm.errors)
    assert str(pip_install.shipped / missing) in said, said
    assert "Autark" in said and "OpenStreetMap" in said, said
    assert not pip_install.folder.exists()


def test_a_clone_installs_beside_its_own_package_json(checkout, launch, npm):
    """A clone, the Docker image and CI install beside Curio's package.json,
    and nothing goes to the state directory."""
    dependencies._ensure_root_node_modules(str(checkout))

    assert [_project(cmd, cwd).resolve() for cmd, cwd in npm.calls] == [checkout.resolve()]
    assert [Path(cwd).resolve() for _cmd, cwd in npm.calls] == [checkout.resolve()]
    assert npm.errors == []
    assert not (launch / ".curio").exists()


def test_a_state_folder_that_links_out_of_curios_own_is_refused(pip_install, launch, npm):
    """``.curio/nodejs`` as a link (here to conda's ``<env>/lib``): the launcher
    writes nothing through it and runs no npm."""
    (launch / ".curio").mkdir()
    (launch / ".curio" / "nodejs").symlink_to(pip_install.lib, target_is_directory=True)

    dependencies._ensure_root_node_modules(str(pip_install.site))

    assert npm.calls == [], (
        f"npm ran ({npm.calls}) where .curio/nodejs leads to {pip_install.lib}, a folder that is "
        f"not Curio's"
    )
    assert not (pip_install.lib / "package.json").exists(), "Curio's package.json was written through the link"
    assert (pip_install.lib / "node_modules" / "npm" / "package.json").is_file()
    assert any(str(launch / ".curio" / "nodejs") in message for message in npm.errors), npm.errors


def test_only_curios_own_node_modules_is_reinstalled_for_another_node_major(pip_install, npm):
    """A tree another Node.js major installed (``NODE_STAMP``) is reinstalled
    only beside Curio's package.json; a node_modules in site-packages is left
    alone."""
    foreign = pip_install.site / "node_modules" / "someones-package" / "index.js"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("module.exports = 1;\n", encoding="utf-8")
    stale = pip_install.folder / "node_modules" / "left-by-an-older-node" / "index.js"
    stale.parent.mkdir(parents=True)
    stale.write_text("module.exports = 2;\n", encoding="utf-8")
    (pip_install.folder / "node_modules" / NODE_STAMP).write_text(str(NODE_MAJOR - 2), encoding="utf-8")

    dependencies._ensure_root_node_modules(str(pip_install.site))

    assert foreign.is_file(), f"the launcher removed {foreign.parent.parent}, which is not Curio's"
    assert not stale.exists(), "Curio's own tree from another Node.js major was kept"
    assert (pip_install.folder / "node_modules" / NODE_STAMP).read_text(encoding="utf-8") == str(NODE_MAJOR)


class _Stdin:
    def __init__(self):
        self.parts = []

    def write(self, text):
        self.parts.append(text)
        return len(text)

    def close(self):
        pass

    @property
    def text(self):
        return "".join(self.parts)


class _Process:
    """What ``Popen`` returns: a Node run that prints *result* and exits 0."""

    def __init__(self, args, kwargs, result):
        self.args, self.kwargs = args, kwargs
        self.stdin = _Stdin()
        self.stdout = iter([result + "\n"])
        self.stderr = iter([])
        self.returncode = 0
        self.pid = 0

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class FakeNode:
    """Stands in for ``subprocess.Popen`` where Curio starts Node: keeps the
    script or request each run was given, and its environment."""

    def __init__(self, result):
        self.result, self.runs = result, []

    def __call__(self, args, **kwargs):
        run = _Process(args, kwargs, self.result)
        self.runs.append(run)
        return run


def _first_on_node_path(env) -> Path:
    return Path(env["NODE_PATH"].split(os.pathsep)[0]).resolve()


def test_the_sandbox_and_the_backend_read_the_node_modules_the_launcher_installed(
    pip_install, npm, monkeypatch, tmp_path,
):
    """One folder for the three processes of a pip install: the launcher
    installs into it, the sandbox's JS nodes import autk-db from it, and the
    backend's OpenStreetMap downloads run autk-db from it."""
    from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
    from utk_curio.backend.app.discovery.providers import autark_osm
    from utk_curio.sandbox.app import worker
    from utk_curio.sandbox.util import node_runtime

    dependencies._ensure_root_node_modules(str(pip_install.site))
    (installed,) = {_project(cmd, cwd).resolve() / "node_modules" for cmd, cwd in npm.calls}
    entry = (installed / "@urban-toolkit" / "autk-db" / "index.js").resolve().as_uri()
    # The sandbox and the backend find Curio's folders from where utk_curio/ is.
    monkeypatch.setattr(node_runtime, "REPO_ROOT", pip_install.site)

    node = FakeNode('__CURIO_JSON_RESULT__{"success": true}')
    with monkeypatch.context() as patched:
        patched.setattr(subprocess, "Popen", node)
        worker.run_js_script(
            f"import {{ AutkDb }} from '{AUTK_DB}';\nreturn 1;", None,
            cwd=str(tmp_path), node_type="AUTK_GRAMMAR",
        )
    (run,) = node.runs
    imported = [line.strip() for line in run.stdin.text.splitlines() if "await import(" in line]
    assert entry in run.stdin.text, (
        f"the sandbox's JS node imports autk-db as {imported}, not from {installed}, where the "
        f"launcher installed it"
    )
    assert _first_on_node_path(run.kwargs["env"]) == installed

    osm = FakeNode('__CURIO_OSM_RESULT__ {"ok": true, "layers": []}')
    monkeypatch.setattr(autark_osm, "subprocess", SimpleNamespace(Popen=osm, PIPE=subprocess.PIPE))
    manifest = load_source_manifest(REPO / "discovery" / OSM)
    out_dir = tmp_path / "download"
    out_dir.mkdir()
    layers = autark_osm.AutarkOsmService(manifest).load(
        manifest.resource("parks"), {"area": {"box": [-87.8, 42.05, -87.78, 42.06]}}, out_dir,
    )
    assert layers == []
    (download,) = osm.runs
    assert json.loads(download.stdin.text)["autkDbUrl"] == entry, (
        f"an OpenStreetMap download runs autk-db from elsewhere than {installed}"
    )
    assert _first_on_node_path(download.kwargs["env"]) == installed


def test_the_pip_package_ships_curios_package_json_and_lockfile(tmp_path, monkeypatch):
    """``setup.py``'s ``build_py`` copies the repository's package.json and
    package-lock.json into the package, where the launcher reads them.
    ``MANIFEST.in`` puts both in the sdist (``test_left_out_files.py``)."""
    setup_py = REPO / "setup.py"
    if not setup_py.is_file():
        pytest.fail(
            f"nothing in the build ships Curio's package.json into the pip package: there is no "
            f"{setup_py}, and a wheel holds only package folders"
        )
    from setuptools.command.build_py import build_py
    from setuptools.dist import Distribution

    from utk_curio.sandbox.util import node_runtime

    spec = importlib.util.spec_from_file_location("_curio_setup", setup_py)
    module = importlib.util.module_from_spec(spec)
    # Not as __main__, so setup() itself does not run; a build runs it as __main__.
    spec.loader.exec_module(module)

    command = module.cmdclass["build_py"](Distribution())
    command.build_lib = str(tmp_path)
    # The packages themselves are not built here, only what the build adds.
    monkeypatch.setattr(build_py, "run", lambda self: None)
    command.run()

    shipped = tmp_path / node_runtime.SHIPPED_PACKAGE_FILES
    for name in node_runtime.PACKAGE_FILES:
        assert (shipped / name).read_bytes() == (REPO / name).read_bytes(), name
