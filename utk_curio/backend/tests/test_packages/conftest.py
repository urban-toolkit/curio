"""Shared fixtures for package tests.

Reuses the common app/DB/auth fixtures from
``utk_curio.backend.tests._unit_fixtures`` (same as test_projects), plus
helpers for building in-memory ``.curio.zip`` zips, stubbing pip, and
materialising synthetic packages in the user's package store.
"""
from __future__ import annotations

import io
import json
import os
import sys
import zipfile

import pytest

from utk_curio.backend.tests._unit_fixtures import (  # noqa: F401
    app,
    client,
    db,
    tmp_curio,
    user_and_token,
)
# The real installer, taken before the autouse stub below replaces it: the
# tests of a removal without isolation need the pip run it notes
# (``pip_that_installs``).
from utk_curio.backend.app.packages.infrastructure.pip_runner import (
    install_python_deps as _real_install_python_deps,
)


#: The data folder the suite's root conftest names for the whole session.
_THE_SESSIONS_DATA_FOLDER = os.environ.get("CURIO_SHARED_DATA")


def _let_the_store_go() -> None:
    """Close the sandbox store's connection, when this process opened one.

    Only code that uses the store imports the module that holds it, and the
    jobs that run some of these tests outside the CI image (preview-runner's)
    have no duckdb to import it with."""
    store = sys.modules.get("utk_curio.sandbox.util.db")
    if store is not None:
        store.release_connection()


@pytest.fixture(autouse=True)
def _a_data_folder_of_its_own(tmp_path, monkeypatch):
    """Each test's own data folder, ``.curio/data`` in its ``tmp_path``.

    The suite's root conftest names one for the whole session, an absolute
    ``CURIO_SHARED_DATA`` that neither ``tmp_path`` nor ``tmp_curio`` moves,
    and each account's node libraries sit beside it
    (``backend_runtime.user_node_overlay_dir``): every test of a worker shared
    the account trees, and the sandbox's store, the tests before it left. A
    folder a module's fixture names for its tests stays theirs.

    The folder is named, not made: ``tmp_curio`` makes it, as the store does
    when it opens (``sandbox.util.db``), so a test that lists its
    ``tmp_path`` finds only what it made. The store's connection is let go
    before and after, as ``test_datasets``' conftest does, so the store a
    test opens is its own.
    """
    if os.environ.get("CURIO_SHARED_DATA") != _THE_SESSIONS_DATA_FOLDER:
        yield  # a module's own folder, which its fixture named
        return
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path / ".curio" / "data"))
    _let_the_store_go()
    yield
    _let_the_store_go()


@pytest.fixture(autouse=True)
def _stub_pip_runner(monkeypatch):
    """Stub the per-package pip runner so service-level tests never shell
    out to the real pip. The UHVI fixture package's manifest declares real
    ``python_deps`` (geopandas, numpy, rasterio); without this stub the
    catalog install path tries to ``pip install`` them inside the test
    interpreter, which is slow and dependent on test-host network state.

    Individual tests in ``test_pip_runner.py`` patch ``subprocess.run``
    directly and don't hit this fixture's stubs.

    Deliberately NOT stubbed: the ``--target`` installers. Nothing here reaches
    them by accident - ``build_overlay`` is the only caller, and the tests that
    exercise it patch that instead - while
    ``test_backend_runtime.py::test_real_pip_target_overlay_end_to_end`` runs a
    real ``pip --target`` against a local wheelhouse and would be gutted by a
    blanket stub. Tests that turn isolation on, and so route node deps into a
    per-user overlay, stub the installer themselves.
    """
    from utk_curio.backend.app.packages.infrastructure import pip_runner
    from utk_curio.backend.app.packages.infrastructure.pip_runner import (
        InstallReport,
        UninstallReport,
    )

    monkeypatch.setattr(
        pip_runner, "install_python_deps",
        lambda deps: InstallReport(installed=[], skipped=list(deps.keys() if deps else [])),
    )
    monkeypatch.setattr(
        pip_runner, "uninstall_python_deps",
        lambda names: UninstallReport(removed=list(names), kept=[]),
    )


@pytest.fixture
def pip_that_installs(monkeypatch):
    """The real ``install_python_deps``, over a pip that installs nothing for
    real: a library is missing until a ``pip install`` names it, then there.
    Returns the libraries it installed."""
    import re
    import subprocess
    import types
    from importlib.metadata import PackageNotFoundError

    from utk_curio.backend.app.packages.infrastructure import pip_runner

    there: dict[str, str] = {}

    def _version(name):
        if name not in there:
            raise PackageNotFoundError(name)
        return there[name]

    def _run(cmd, *args, **kwargs):
        assert list(cmd[1:4]) == ["-m", "pip", "install"], f"only pip install is faked: {cmd}"
        for requirement in cmd[5:]:
            there[re.split(r"[<>=!~]", requirement, maxsplit=1)[0]] = "1.0"
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(pip_runner, "install_python_deps", _real_install_python_deps)
    monkeypatch.setattr(pip_runner, "installed_version", _version)
    monkeypatch.setattr(
        pip_runner, "subprocess",
        types.SimpleNamespace(run=_run, TimeoutExpired=subprocess.TimeoutExpired),
    )
    monkeypatch.setattr(pip_runner, "import_failures", lambda deps: {})
    return there


# ---------------------------------------------------------------------------
# Package archive helpers
# ---------------------------------------------------------------------------

def _manifest_dict(
    package_id: str = "ai.test.demo",
    major: int = 1,
    version: str = "1.0.0",
    *,
    kinds: list[dict] | None = None,
    python_deps: dict[str, str] | None = None,
    package_deps: dict[str, str] | None = None,
    lineage: dict | None = None,
    distribution: dict | None = None,
    created_at: str | None = "2026-06-01T12:00:00Z",
) -> dict:
    d = {
        "id": package_id,
        "version": version,
        "name": package_id,
        "publisher": "Test",
        "description": "Test package",
        "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": major},
        "permissions": [],
        "dependencies": {
            "packages": package_deps or {},
            "python": python_deps or {},
            "js": {},
        },
        "templates": kinds or [
            {
                "id": "demo-kind",
                "label": "Demo",
                "category": "computation",
                "engine": "python",
                "editor": "code",
                "hasCode": True,
                "hasWidgets": False,
                "hasGrammar": False,
                "inputPorts": [],
                "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
                "templateDir": "starters/demo-kind",
                "defaultTemplate": "starters/demo-kind/Default.py",
            }
        ],
    }
    if lineage is not None:
        d["lineage"] = lineage
    if distribution is not None:
        d["distribution"] = distribution
    if created_at:
        d["createdAt"] = created_at
    return d


@pytest.fixture()
def make_archive():
    """Factory: build a ``.curio.zip`` zip from a manifest + sources map."""
    def _build(
        manifest: dict | None = None,
        sources: dict[str, dict[str, str]] | None = None,
        *,
        extra_files: dict[str, bytes] | None = None,
    ) -> bytes:
        manifest = manifest or _manifest_dict()
        sources = sources or {"demo-kind": {"Default.py": "def run():\n    return {}\n"}}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))
            for template_id, files in sources.items():
                for name, body in files.items():
                    zf.writestr(f"starters/{template_id}/{name}", body)
            for path, body in (extra_files or {}).items():
                zf.writestr(path, body)
        return buf.getvalue()
    return _build


@pytest.fixture()
def manifest_dict():
    """Expose the helper so individual tests can tweak fields."""
    return _manifest_dict


@pytest.fixture()
def install_package(tmp_curio, make_archive):
    """Install a synthetic package for the given user_key and return the manifest."""
    from utk_curio.backend.app.packages.application.store_install import install_package_from_archive

    def _install(
        user_key: str,
        manifest: dict | None = None,
        sources: dict[str, dict[str, str]] | None = None,
    ):
        archive = make_archive(manifest=manifest, sources=sources)
        return install_package_from_archive(user_key, archive)
    return _install


def write_fake_tool(directory, name: str, source: str):
    """Write an executable stand-in for a pinned build tool, cross-platform.

    The build tests fake ``esbuild`` and the preview runner with a Python
    script carrying a ``#!/usr/bin/env python3`` shebang plus ``chmod 0o755``.
    That only runs where the OS honours ``#!``. On Windows the exec fails with
    ``[WinError 193] %1 is not a valid Win32 application``, which took out 21
    of these tests at fixture setup and made another 14 fail downstream.

    On POSIX this keeps the shebang script. On Windows it writes the script as
    ``<name>.py`` next to a ``<name>.cmd`` shim that hands it to *this*
    interpreter by absolute path - the build code runs its tools under a
    deliberately minimal environment, so nothing may depend on ``python``
    being discoverable on PATH.

    Returns the path to hand to ``CURIO_BUILD_ESBUILD`` /
    ``CURIO_BUILD_PREVIEW_RUNNER``.
    """
    import os
    import sys
    from pathlib import Path

    directory = Path(directory)
    if os.name != "nt":
        tool = directory / name
        tool.write_text(source, encoding="utf-8")
        tool.chmod(0o755)
        return tool

    script = directory / f"{name}.py"
    script.write_text(source, encoding="utf-8")
    shim = directory / f"{name}.cmd"
    # `%*` forwards argv with its original quoting; cmd.exe propagates the
    # child's exit code, which the version probe and the failure cases rely on.
    shim.write_text(
        "@echo off\r\n"
        f'"{sys.executable}" "{script}" %*\r\n',
        encoding="utf-8",
    )
    return shim

@pytest.fixture()
def default_llm_provider(monkeypatch):
    """Stand in for an operator who configured a default LLM provider.

    The DoD scenarios in ``test_custom_look_dod.py`` drive real agent runs, and
    an agent route resolves a provider before it validates anything else - so
    with none configured they fail at that first step with
    ``400 No AI provider is configured`` instead of exercising the package
    build they are about.

    Curio ships no built-in endpoint (``config.DEFAULT_LLM_ENDPOINTS`` is
    empty), which is deliberate: an instance whose operator configured nothing
    must not send prompts to a third party. So the test supplies one rather
    than leaning on a shipped default, exactly as ``test_agents/conftest.py``
    does. The URL is unroutable on purpose - every provider call in these tests
    is stubbed, and one that forgot should fail loudly rather than reach the
    network.
    """
    from utk_curio.backend.tests._support import llm_deployment

    llm_deployment.offer(monkeypatch, llm_deployment.TEST_ENDPOINT)
