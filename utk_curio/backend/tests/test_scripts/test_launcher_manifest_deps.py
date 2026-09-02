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
