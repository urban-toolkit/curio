"""Shared fixtures for the Data Lake Catalog tests.

Mirrors ``test_datasets/conftest.py``: the common app/client/db/user fixtures,
plus a temp ``CURIO_DATALAKE_ROOT`` so a test can mint sources without touching
the committed catalog, and a ``shipped_root`` for the tests that must read the
real one.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from utk_curio.backend.app import create_app
from utk_curio.backend.extensions import db as _db
from utk_curio.backend.tests._unit_fixtures import (  # noqa: F401
    TestConfig,
    client,
    db,
    user_and_token,
)
from utk_curio.backend.app.datalakes.infrastructure import storage

#: The committed catalog, found the way the code finds it rather than by
#: walking up from this file, so a move of either breaks loudly here.
SHIPPED_ROOT = Path(__file__).resolve().parents[4] / "datalakes"


@pytest.fixture()
def lake_root(tmp_path, monkeypatch):
    """An empty catalog root this test owns."""
    root = tmp_path / "datalakes"
    root.mkdir()
    monkeypatch.setenv(storage.ENV_ROOT, str(root))
    return root


@pytest.fixture()
def failing_source(lake_root):
    """A direct-URL source whose resource ids are the recorded failure URLs.

    Lets the refusal branches - oversized, archive, unreachable - be exercised
    deterministically. They are the hardest cases to provoke against a live
    portal and the easiest to get wrong.
    """
    write_source(lake_root, "lake.test.fail@1", a_manifest(
        id="lake.test.fail", name="Failure Cases",
        provider={"type": "direct", "baseUrl": ""},
        capabilities={"search": False, "formats": ["csv", "geojson", "json"]}))
    return lake_root


@pytest.fixture()
def shipped_root(monkeypatch):
    """The real committed catalog, pinned explicitly.

    Set rather than relied upon: without it these tests would pass or fail
    depending on how far the repo sits from ``storage.py``, which is exactly
    the kind of thing that works locally and not in a wheel.
    """
    monkeypatch.setenv(storage.ENV_ROOT, str(SHIPPED_ROOT))
    return SHIPPED_ROOT


FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture()
def fixture_corpus(monkeypatch):
    """Point the backend at the recorded corpus, as the e2e harness does.

    Double-gated: CURIO_TESTING must also be set, which conftest already
    exports for the whole suite.
    """
    from utk_curio.backend.app.datalakes.infrastructure import transport

    monkeypatch.setenv(transport.ENV_FIXTURES, str(FIXTURES))
    monkeypatch.setenv("CURIO_TESTING", "1")
    return FIXTURES


@pytest.fixture(autouse=True)
def _reset_lake_process_state():
    """The rate limiter and the WFS capabilities cache are module-level by
    design (both bound a PROCESS), so they leak between tests unless cleared."""
    from utk_curio.backend.app.datalakes.infrastructure import ratelimit
    from utk_curio.backend.app.datalakes.providers import wfs

    ratelimit.limiter.reset()
    ratelimit.download_slots.reset()
    wfs.WfsProvider.clear_cache()
    yield
    ratelimit.limiter.reset()
    ratelimit.download_slots.reset()
    wfs.WfsProvider.clear_cache()


@pytest.fixture()
def app(tmp_path, monkeypatch):
    from utk_curio.sandbox.util.db import release_connection

    release_connection()
    shared_data = tmp_path / ".curio" / "data"
    shared_data.mkdir(parents=True)
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(shared_data))

    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()

    release_connection()


def write_source(root: Path, dir_name: str, manifest: dict, *, icon: bytes | None = None) -> Path:
    """Mint a source directory. Returns its path."""
    path = root / dir_name
    path.mkdir(parents=True, exist_ok=True)
    (path / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if icon is not None:
        (path / "icon.png").write_bytes(icon)
    return path


def a_manifest(**overrides) -> dict:
    """A minimal valid manifest, overridable field by field."""
    base = {
        "id": "lake.example.portal",
        "name": "Example Portal",
        "version": "1.0.0",
        "compatibility": {"major": 1},
        "description": "An example.",
        "publisher": "Example",
        "tags": ["example"],
        "provider": {"type": "ckan", "baseUrl": "https://portal.example", "options": {}},
        "auth": {"mode": "public"},
        "capabilities": {"search": True, "describe": True, "download": True,
                         "formats": ["csv"], "maxDownloadBytes": 1024},
        "limits": {"requestsPerMinute": 10},
    }
    base.update(overrides)
    return base


#: The smallest valid PNG: an 1x1 image. Real magic bytes, so the shipped-icon
#: assertions are testing what they claim to test.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)
