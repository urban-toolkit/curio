"""Shared fixtures for package tests.

Mirrors ``test_projects/conftest.py`` so the same auth/DB fixtures work
here, plus helpers for building in-memory ``.curio.zip`` zips and
for materialising synthetic packages in the user's package store.
"""
from __future__ import annotations

import io
import json
import os
import zipfile

import pytest

from utk_curio.backend.app import create_app
from utk_curio.backend.app.packages.storage import user_packageages_dir
from utk_curio.backend.extensions import db as _db


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False


@pytest.fixture()
def tmp_curio(tmp_path, monkeypatch):
    data_dir = tmp_path / ".curio" / "data"
    data_dir.mkdir(parents=True)
    # Use monkeypatch so the session-level CURIO_LAUNCH_CWD (set in the root
    # conftest) is *restored* on teardown rather than deleted — a bare
    # ``os.environ.pop`` here clobbers it for every later test that reads it
    # (e.g. test_routes::test_file_route_serves_relative_to_launch_cwd).
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    yield tmp_path


@pytest.fixture(autouse=True)
def _stub_pip_runner(monkeypatch):
    """Stub the per-package pip runner so service-level tests never shell
    out to the real pip. The UHVI fixture package's manifest declares real
    ``python_deps`` (geopandas, numpy, rasterio); without this stub the
    catalog install path tries to ``pip install`` them inside the test
    interpreter, which is slow and dependent on test-host network state.

    Individual tests in ``test_pip_runner.py`` patch ``subprocess.run``
    directly and don't hit this fixture's stubs.
    """
    from utk_curio.backend.app.packages import pip_runner
    from utk_curio.backend.app.packages.pip_runner import InstallReport, UninstallReport

    monkeypatch.setattr(
        pip_runner, "install_python_deps",
        lambda deps: InstallReport(installed=[], skipped=list(deps.keys() if deps else [])),
    )
    monkeypatch.setattr(
        pip_runner, "uninstall_python_deps",
        lambda names: UninstallReport(removed=list(names), kept=[]),
    )


@pytest.fixture()
def app(tmp_curio):
    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    return _db


@pytest.fixture()
def user_and_token(app, db):
    from utk_curio.backend.app.users.models import User, UserSession
    u = User(username="alice", name="Alice", email="alice@test.com")
    db.session.add(u)
    db.session.flush()
    s = UserSession(user_id=u.id, token="alice-token-123")
    db.session.add(s)
    db.session.commit()
    return u, "alice-token-123"


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
def install_packageage(tmp_curio, make_archive):
    """Install a synthetic package for the given user_key and return the manifest."""
    from utk_curio.backend.app.packages.installer import install_packageage_from_archive

    def _install(
        user_key: str,
        manifest: dict | None = None,
        sources: dict[str, dict[str, str]] | None = None,
    ):
        archive = make_archive(manifest=manifest, sources=sources)
        return install_packageage_from_archive(user_key, archive)
    return _install


@pytest.fixture()
def packages_base(tmp_curio):
    """Path to ``.curio/users/`` for the current test workspace."""
    return user_packageages_dir("guest").parent.parent
