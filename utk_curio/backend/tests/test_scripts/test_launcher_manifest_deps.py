"""``install_manifest_dependencies`` routes deps; it does not union them.

``dep_destinations`` (backend_runtime, dev/97) is the one rule deciding where a
package's python deps belong. A backend-bearing package whose handlers read a
private overlay routes to ``"overlay"``: promoting it deliberately leaves the
shared interpreter alone.

The boot walk used to union every manifest it found under ``.curio/users/`` and
host-install the lot, which silently undid that boundary on the next restart —
including an unattended one after a host reboot. Worse, a version pin in one
user's manifest could then move a library every other user's nodes import;
``merge_python_deps`` only logs a conflict warning and pip has the last word.

These tests pin the routing, not the pip call: ``install_python_deps`` is
stubbed so nothing reaches the network.
"""
from __future__ import annotations

import json
import os

import pytest

from utk_curio import main as launcher
from utk_curio.backend.app.common.user_storage import users_base

BASE_TEMPLATE = {
    "id": "demo-node",
    "label": "Demo",
    "category": "computation",
    "editor": "code",
    "engine": "python",
    "hasCode": True,
    "inputPorts": [],
    "outputPorts": [],
}


def _write_package(store: "object", dir_name: str, *, deps: dict,
                   backend: bool, python_template: bool) -> None:
    """A minimal installed package under ``<user>/packages/<dir_name>/``.

    ``templates`` is always non-empty - the loader refuses an empty list, and a
    refused manifest is skipped by the walk, which would make these tests pass
    whatever the routing does. ``python_template=False`` therefore ships a
    *javascript* template: that is what makes ``has_warm_python`` false and
    routes a backend-bearing package to "overlay".
    """
    pkg = store / dir_name
    pkg.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": dir_name.split("@")[0],
        "version": "1.0.0",
        "name": dir_name,
        "publisher": "Test",
        "description": "fixture",
        "license": "MIT",
        # ``compatibility.major`` is required by the loader and is what the
        # ``<id>@<major>`` directory name encodes.
        "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
        "templates": [
            dict(BASE_TEMPLATE) if python_template
            else {**BASE_TEMPLATE, "id": "demo-js", "engine": "javascript"}
        ],
        "dependencies": {"js": {}, "packages": {}, "python": deps},
    }
    if backend:
        # The loader is strict about this shape: entry must be a .py under
        # backend/, and handlers a non-empty list of {"name": ...} objects. A
        # malformed one raises ManifestError and the walk skips the package
        # entirely — which would make these tests pass for the wrong reason.
        manifest["backend"] = {
            "entry": "backend/handler.py",
            "handlers": [{"name": "run"}],
        }
        # A backend-bearing package must declare this, or the loader refuses:
        # the install review surfaces server-side code before Apply.
        manifest["permissions"] = ["server-code"]
        (pkg / "backend").mkdir(parents=True, exist_ok=True)
        (pkg / "backend" / "handler.py").write_text(
            "def run(payload):" + chr(10) + "    return {}" + chr(10),
            encoding="utf-8",
        )
    (pkg / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.fixture
def launch_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    return tmp_path


@pytest.fixture
def installed(monkeypatch):
    """Capture what the launcher would have pip-installed."""
    calls: list[dict] = []
    monkeypatch.setattr(
        launcher, "install_manifest_dependencies",
        launcher.install_manifest_dependencies,
    )
    import utk_curio.backend.app.packages.pip_runner as pip_runner
    monkeypatch.setattr(
        pip_runner, "install_python_deps",
        lambda merged, on_line=None: calls.append(dict(merged)),
    )
    # The post-install importability check spawns a real interpreter, so stub it
    # to "everything imports" here. The tests that care about it override this.
    monkeypatch.setattr(pip_runner, "import_failures", lambda deps: {})
    return calls


def _user_store(launch_cwd, user: str = "1"):
    """The store the boot walk will actually read, created.

    ``users_base()`` rather than a literal: under ``CURIO_TESTING`` — which the
    root conftest sets for this suite — the tree is ``.curio/test/users/``. A
    literal ``.curio/users`` here builds packages the walk never sees, and the
    negative tests in this file then pass against an empty store while proving
    nothing about the routing they claim to pin.
    """
    base = users_base()
    assert base.is_relative_to(launch_cwd.resolve()), (
        f"store root {base} escaped the tmp workspace {launch_cwd}"
    )
    store = base / user / "packages"
    store.mkdir(parents=True, exist_ok=True)
    return store


def test_overlay_routed_package_is_not_host_installed(launch_cwd, installed):
    """A backend-only package keeps its deps out of the shared interpreter."""
    _write_package(
        _user_store(launch_cwd), "acme.handlers@1",
        deps={"tabulate": ">=0.9"}, backend=True, python_template=False,
    )
    launcher.install_manifest_dependencies()
    merged = {k: v for call in installed for k, v in call.items()}
    assert "tabulate" not in merged, (
        "an overlay-routed package's deps were host-installed at boot, undoing "
        "the boundary its promotion established"
    )


def test_host_routed_package_is_still_installed(launch_cwd, installed):
    """A package with no backend surface serves the warm sandbox — still host."""
    _write_package(
        _user_store(launch_cwd), "acme.nodes@1",
        deps={"inflection": ">=0.5"}, backend=False, python_template=True,
    )
    launcher.install_manifest_dependencies()
    merged = {k: v for call in installed for k, v in call.items()}
    assert "inflection" in merged


def test_both_routed_package_is_installed(launch_cwd, installed):
    """Backend handlers plus a python node template: the sandbox needs it too."""
    _write_package(
        _user_store(launch_cwd), "acme.mixed@1",
        deps={"inflection": ">=0.5"}, backend=True, python_template=True,
    )
    launcher.install_manifest_dependencies()
    merged = {k: v for call in installed for k, v in call.items()}
    assert "inflection" in merged


def test_manifests_nested_inside_a_package_payload_are_ignored(
    launch_cwd, installed,
):
    """Only ``<user>/packages/<dir>/manifest.json`` is an installed package.

    The old ``rglob`` also matched manifests shipped *inside* a package's own
    files, which are payload, not installations.
    """
    store = _user_store(launch_cwd)
    _write_package(store, "acme.nodes@1", deps={}, backend=False,
                   python_template=True)
    nested = store / "acme.nodes@1" / "files" / "fixtures" / "acme.vendored@1"
    nested.mkdir(parents=True, exist_ok=True)
    (nested / "manifest.json").write_text(
        json.dumps({
            "id": "acme.vendored", "version": "1.0.0", "name": "vendored",
            "publisher": "Test", "description": "fixture", "license": "MIT",
            "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
            "templates": [dict(BASE_TEMPLATE)],
            "dependencies": {"js": {}, "packages": {},
                             "python": {"cowsay": ">=6"}},
        }),
        encoding="utf-8",
    )
    launcher.install_manifest_dependencies()
    merged = {k: v for call in installed for k, v in call.items()}
    assert "cowsay" not in merged


class TestBrokenInstallIsReported:
    """pip exiting 0 is not the same as the library working.

    A wheel whose native extension cannot load - a rasterio built against a
    different GDAL is the everyday case on Windows - records a perfectly good
    version. pip then reports "already satisfied" on every subsequent start and
    changes nothing, so setup looked clean and the first sign of trouble was a
    raw ImportError from whichever node happened to run first.
    """

    @staticmethod
    def _package(launch_cwd):
        _write_package(
            _user_store(launch_cwd), "acme.geo@1",
            deps={"rasterio": ">=1.3"}, backend=False, python_template=True,
        )

    def test_a_dep_that_installs_but_cannot_import_is_warned_about(
        self, launch_cwd, installed, monkeypatch, capsys
    ):
        import utk_curio.backend.app.packages.pip_runner as pip_runner
        self._package(launch_cwd)
        monkeypatch.setattr(
            pip_runner, "import_failures",
            lambda deps: {"rasterio": "ImportError: DLL load failed"},
        )

        launcher.install_manifest_dependencies(block_on_verify=True)

        err = capsys.readouterr().err
        assert "rasterio" in err
        assert "cannot be imported" in err
        # The reason matters as much as the name: "it is broken" sends the
        # operator to pip, "DLL load failed" sends them to their GDAL.
        assert "DLL load failed" in err

    def test_a_working_dep_says_nothing(
        self, launch_cwd, installed, monkeypatch, capsys
    ):
        self._package(launch_cwd)
        launcher.install_manifest_dependencies(block_on_verify=True)
        assert "cannot be imported" not in capsys.readouterr().err

    def test_a_broken_dep_does_not_stop_the_boot(
        self, launch_cwd, installed, monkeypatch
    ):
        """Warn, do not exit: the nodes that avoid the library still work, and
        the fix is usually outside pip."""
        import utk_curio.backend.app.packages.pip_runner as pip_runner
        self._package(launch_cwd)
        monkeypatch.setattr(
            pip_runner, "import_failures",
            lambda deps: {"rasterio": "ImportError: DLL load failed"},
        )

        launcher.install_manifest_dependencies(block_on_verify=True)  # no SystemExit

    def test_a_probe_that_cannot_run_is_itself_reported(
        self, launch_cwd, installed, monkeypatch, capsys
    ):
        """A failed check must not masquerade as a clean bill of health."""
        import utk_curio.backend.app.packages.pip_runner as pip_runner
        self._package(launch_cwd)

        def _boom(deps):
            raise OSError("no interpreter")

        monkeypatch.setattr(pip_runner, "import_failures", _boom)

        launcher.install_manifest_dependencies(block_on_verify=True)

        assert "Could not verify" in capsys.readouterr().err

    def test_start_does_not_wait_for_the_probe(
        self, launch_cwd, installed, monkeypatch
    ):
        """The default path must not add the probe's cost to every boot.

        Importing the twelve builtin data-ops libraries in one subprocess takes
        about 19 seconds here, so the check runs on a daemon thread and the
        warning lands while the servers come up. A regression to a blocking
        call would be invisible except as a slower start, which is exactly the
        kind of thing nobody attributes to the right commit.
        """
        import threading
        import utk_curio.backend.app.packages.pip_runner as pip_runner

        self._package(launch_cwd)
        entered = threading.Event()
        release = threading.Event()

        def _slow(deps):
            entered.set()
            release.wait(5)
            return {}

        monkeypatch.setattr(pip_runner, "import_failures", _slow)

        launcher.install_manifest_dependencies()  # returns while _slow blocks

        assert entered.wait(5), "the probe never ran"
        release.set()


# ── #332: under isolation the walk installs per user, not once for everyone ──


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setenv("CURIO_ISOLATION", "fork")


@pytest.fixture
def in_process(monkeypatch):
    monkeypatch.setenv("CURIO_ISOLATION", "off")


@pytest.fixture
def installed_per_user(monkeypatch):
    """Capture what the launcher would install, and into whose tree."""
    calls: list[tuple[dict, str]] = []
    import utk_curio.backend.app.packages.pip_runner as pip_runner
    monkeypatch.setattr(
        pip_runner, "install_python_deps_to_target",
        lambda merged, target, on_line=None: calls.append((dict(merged), str(target))),
    )
    return calls


def test_the_existing_routing_is_what_happens_without_isolation(
    launch_cwd, installed, installed_per_user, in_process,
):
    """The three tests above run in this world; this states it outright."""
    _write_package(
        _user_store(launch_cwd), "acme.nodes@1",
        deps={"inflection": ">=0.5"}, backend=False, python_template=True,
    )
    launcher.install_manifest_dependencies()

    merged = {k: v for call in installed for k, v in call.items()}
    assert "inflection" in merged
    assert installed_per_user == [], "nothing should reach a per-user tree"


def test_with_isolation_a_users_deps_go_to_their_own_tree(
    launch_cwd, installed, installed_per_user, isolated,
):
    _write_package(
        _user_store(launch_cwd, "7"), "acme.nodes@1",
        deps={"inflection": ">=0.5"}, backend=False, python_template=True,
    )
    launcher.install_manifest_dependencies()

    assert len(installed_per_user) == 1
    deps, target = installed_per_user[0]
    assert "inflection" in deps
    assert target.endswith(os.path.join("users", "7"))
    host = {k: v for call in installed for k, v in call.items()}
    assert "inflection" not in host


def test_two_users_needing_the_same_library_each_get_it(
    launch_cwd, installed, installed_per_user, isolated,
):
    """The dedupe that made the merged host walk cheap is wrong here: the
    library has to land in both trees, not in whichever the glob reached
    first."""
    for user in ("7", "8"):
        _write_package(
            _user_store(launch_cwd, user), "acme.nodes@1",
            deps={"inflection": ">=0.5"}, backend=False, python_template=True,
        )
    launcher.install_manifest_dependencies()

    targets = sorted(t for _deps, t in installed_per_user)
    assert len(targets) == 2 and targets[0] != targets[1]
    assert all("inflection" in deps for deps, _t in installed_per_user)


def test_one_users_broken_manifest_does_not_stop_the_boot(
    launch_cwd, installed, isolated, monkeypatch,
):
    """Best-effort per user. The failure belongs to whoever installed that
    package; everyone else's instance still comes up."""
    import utk_curio.backend.app.packages.pip_runner as pip_runner

    done: list[str] = []

    def _maybe_fail(merged, target, on_line=None):
        if os.path.basename(target) == "7":
            raise pip_runner.PipInstallError("no such distribution")
        done.append(os.path.basename(target))

    monkeypatch.setattr(pip_runner, "install_python_deps_to_target", _maybe_fail)
    for user in ("7", "8"):
        _write_package(
            _user_store(launch_cwd, user), "acme.nodes@1",
            deps={"inflection": ">=0.5"}, backend=False, python_template=True,
        )
    launcher.install_manifest_dependencies()

    assert done == ["8"]


def test_an_overlay_routed_package_stays_out_of_the_user_tree_too(
    launch_cwd, installed, installed_per_user, isolated,
):
    """Handler deps are per-package state either way. Isolation moved where
    NODE code's environment is; a backend-only package has none."""
    _write_package(
        _user_store(launch_cwd, "7"), "acme.handlers@1",
        deps={"tabulate": ">=0.9"}, backend=True, python_template=False,
    )
    launcher.install_manifest_dependencies()

    assert installed_per_user == []
