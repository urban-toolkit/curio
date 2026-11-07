"""The scripts that ask a Discovery source with a key of their own bind it as
the service does: ``scripts/build_example_mapillary.py`` (example 10's photos)
and ``scripts/record_discovery_fixtures.py`` (the Mapillary fixtures).

Each script runs here up to its source's service, which is stubbed: the
transport the script hands it sends the key to Mapillary's own origin and to
nothing else, such as the CDN its photos come from. Both scripts stopped with
a TypeError before their first request once the transport's ``hosts=`` became
``origins=``.
"""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace

from utk_curio.backend.app.discovery import providers
from utk_curio.backend.app.discovery.infrastructure import transport as transport_module

REPO_ROOT = Path(__file__).resolve().parents[4]
TOKEN = "MLY|a-test-token"
SENT_KEY = f"Authorization:OAuth {TOKEN}"
MAPILLARY_URL = "https://graph.mapillary.com/images"
PHOTO_URL = "https://scontent.xx.fbcdn.net/photo.jpg"


def _script(name: str):
    spec = importlib.util.spec_from_file_location(f"_scripts_{name}", REPO_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Recording:
    """An inner transport that keeps the key each request carried."""

    def __init__(self, *_args):
        self.calls: list[tuple[str, str | None]] = []

    def json_get(self, url, *, credential=None, headers=None):
        self.calls.append((url, credential))
        return {}


def _services(monkeypatch) -> list:
    """Stub the source's service; the list fills with the transports handed to it."""
    handed: list = []

    def build_service(manifest, transport=None):
        handed.append(transport)
        return SimpleNamespace(load=lambda spec, values, folder: SimpleNamespace(images=[]))

    monkeypatch.setattr(providers, "build_service", build_service)
    return handed


def _sends_the_key_only_to_mapillary(transport) -> None:
    transport.json_get(MAPILLARY_URL)
    transport.json_get(PHOTO_URL)
    assert transport.calls == [(MAPILLARY_URL, SENT_KEY), (PHOTO_URL, None)]


def test_the_example_photo_builder_sends_its_key_only_to_mapillary(monkeypatch, tmp_path):
    handed = _services(monkeypatch)
    monkeypatch.setattr(transport_module, "HttpDiscoveryTransport", _Recording)
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **_kwargs: str(tmp_path))

    assert _script("build_example_mapillary").fetch(TOKEN) == []

    assert len(handed) == 1
    _sends_the_key_only_to_mapillary(handed[0])


def test_the_fixture_recorder_sends_its_key_only_to_mapillary(monkeypatch):
    handed = _services(monkeypatch)
    recorder = _script("record_discovery_fixtures")
    monkeypatch.setattr(recorder, "ServiceRecordingTransport", _Recording)
    monkeypatch.setenv("CURIO_MAPILLARY_TOKEN", TOKEN)

    recorder.record_services("mapillary", {})

    assert len(handed) == 1
    _sends_the_key_only_to_mapillary(handed[0])
