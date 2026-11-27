"""A package manifest has the fields its schema requires (#482), and its schema
takes the package ids its parser takes.

``node-package.v4.json`` requires ``name`` (``minLength`` 1) and ``publisher``,
and gives ``version`` a semver pattern. The parser filled ``name`` in from the
id, ``publisher`` with ``""``, and took any non-empty version string, so a
manifest the schema rejects loaded anyway.

The parser reads an id by the loader's grammar (``PACKAGE_DIR_RE``): two to six
parts, each a lowercase letter, then lowercase letters, digits or '-', 63
characters at most. The schema's ``id`` pattern took ``_``, one part, seven
parts and a part of any length, so an editor checking a manifest against it
passed an id the parser refuses.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from utk_curio.backend.app.packages.domain.manifest import (
    VERSION_RE,
    ManifestError,
    package_manifest_from_dict,
)
from utk_curio.backend.tests.test_packages.conftest import _manifest_dict

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[4] / "docs/schemas/node-package.v4.json")
    .read_text(encoding="utf-8")
)


def _parse(raw: dict):
    return package_manifest_from_dict(raw, manifest_path=Path("manifest.json"), dir_name="ai.test.demo@1")


def test_the_validator_checks_what_the_schema_requires():
    assert {"name", "publisher", "version"} <= set(SCHEMA["required"])
    assert SCHEMA["properties"]["version"]["pattern"] == VERSION_RE.pattern


def test_a_complete_manifest_loads():
    m = _parse(_manifest_dict())
    assert (m.name, m.publisher, m.version) == ("ai.test.demo", "Test", "1.0.0")


@pytest.mark.parametrize("missing", ["name", "publisher"])
def test_a_manifest_without_a_required_field_is_refused(missing):
    raw = _manifest_dict()
    del raw[missing]
    with pytest.raises(ManifestError, match=missing):
        _parse(raw)


def test_an_empty_name_is_refused():
    raw = _manifest_dict()
    raw["name"] = "  "
    with pytest.raises(ManifestError, match="name"):
        _parse(raw)


def test_an_empty_publisher_is_allowed():
    # The schema sets no minimum, and the Node Factory sends "" for a draft
    # nobody named a publisher for.
    raw = _manifest_dict()
    raw["publisher"] = ""
    assert _parse(raw).publisher == ""


@pytest.mark.parametrize("version", ["1", "1.0", "v1.0.0", "latest"])
def test_a_version_that_is_not_semver_is_refused(version):
    with pytest.raises(ManifestError, match="version"):
        _parse(_manifest_dict(version=version))


@pytest.mark.parametrize("version", ["1.0.0", "2.10.3", "1.0.0-rc.1", "1.0.0+build.7"])
def test_a_semver_version_loads(version):
    assert _parse(_manifest_dict(version=version)).version == version


def _parse_id(package_id: str):
    return package_manifest_from_dict(
        _manifest_dict(package_id), manifest_path=Path("manifest.json"), dir_name=f"{package_id}@1"
    )


@pytest.mark.parametrize("package_id", [
    "rolling-stats", "me.my_node", "me..x", "me.a.b.c.d.e.f", "me.9lives", "me." + "a" * 64,
])
def test_an_id_the_parser_refuses_the_schema_refuses(package_id):
    with pytest.raises(ManifestError, match="id is missing or malformed"):
        _parse_id(package_id)
    assert not re.match(SCHEMA["properties"]["id"]["pattern"], package_id)


@pytest.mark.parametrize("package_id", [
    "me.rolling-stats", "edu.uic.cs529.alice", "me.my-node", "me.a.b.c.d.e", "a.b", "me." + "a" * 63,
])
def test_an_id_the_parser_takes_the_schema_takes(package_id):
    assert _parse_id(package_id).package_id == package_id
    assert re.match(SCHEMA["properties"]["id"]["pattern"], package_id)
