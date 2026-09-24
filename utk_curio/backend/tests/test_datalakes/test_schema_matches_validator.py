"""``docs/schemas/data-lake-source.v1.json`` and the validator agree.

Modelled on ``test_agents/test_schema_matches_validator.py``, and it exists for
the same reason: a source manifest is hand-authored, so the schema is the
artifact an author writes against. Drift between what the schema promises and
what the validator accepts is invisible until someone's manifest is rejected
by a rule no document mentions.

Every assertion here is derived from the validator, never restated. A test
that hard-codes ``["arcgis", "ckan", ...]`` would have to be edited in lockstep
too, and would then be a third thing to keep in sync.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.datalakes.domain import manifest as M
from utk_curio.backend.app.datalakes.domain.source_id import SOURCE_ID_RE

SCHEMA_PATH = Path(__file__).resolve().parents[4] / "docs" / "schemas" / "data-lake-source.v1.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_the_schema_file_exists_and_is_2020_12(schema):
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith("docs/schemas/data-lake-source.v1.json")


def test_the_id_pattern_is_the_validators(schema):
    assert schema["properties"]["id"]["pattern"] == SOURCE_ID_RE.pattern


def test_the_provider_enum_is_the_registry(schema):
    """The assertion that stops a new provider landing in one place only."""
    assert schema["properties"]["provider"]["properties"]["type"]["enum"] == sorted(M.PROVIDER_TYPES)


def test_the_auth_mode_enum_matches(schema):
    assert schema["properties"]["auth"]["properties"]["mode"]["enum"] == sorted(M.AUTH_MODES)


def test_the_auth_scheme_enum_matches_and_is_header_only(schema):
    enum = schema["properties"]["auth"]["properties"]["scheme"]["enum"]
    assert enum == sorted(M.AUTH_SCHEMES)
    assert enum == ["header"], "v1 is header-only; a query scheme would put secrets in URLs"


def test_the_secret_id_pattern_matches(schema):
    assert schema["properties"]["auth"]["properties"]["secretId"]["pattern"] == M._SECRET_ID_RE.pattern


def test_the_icon_pattern_matches(schema):
    assert schema["properties"]["icon"]["pattern"] == M._ICON_RE.pattern


def test_the_format_enum_is_the_acquirable_set(schema):
    formats = schema["properties"]["capabilities"]["properties"]["formats"]["items"]["enum"]
    assert formats == sorted(M.LAKE_ACQUIRABLE_FORMATS)


def test_the_acquirable_set_is_a_subset_of_what_the_data_catalog_stores(schema):
    """The two catalogs meet here: a lake can only deliver a format the Data
    Catalog can hold. Narrower by design - shp needs sibling files and bundle
    is a node output, so neither is remotely acquirable."""
    from utk_curio.backend.app.datasets.domain.manifest import SUPPORTED_FORMATS

    assert set(M.LAKE_ACQUIRABLE_FORMATS) < set(SUPPORTED_FORMATS)


def test_the_download_ceiling_matches(schema):
    ceiling = schema["properties"]["capabilities"]["properties"]["maxDownloadBytes"]["maximum"]
    assert ceiling == M.DEFAULT_MAX_DOWNLOAD_BYTES


def test_required_fields_match_the_validator(schema):
    """Refusing each one in turn proves the schema's `required` is the truth,
    rather than a list someone kept up to date by hand."""
    from utk_curio.backend.tests.test_datalakes.conftest import a_manifest

    for field in schema["required"]:
        raw = a_manifest()
        raw.pop(field, None)
        with pytest.raises(M.ManifestError):
            M._parse_manifest(raw, where="manifest.json")


def test_every_shipped_manifest_validates_against_the_schema(schema):
    """The real check, if jsonschema is installed. Skipped rather than faked
    when it is not: an assertion that silently checks nothing is worse than an
    honest skip."""
    jsonschema = pytest.importorskip("jsonschema")
    from utk_curio.backend.tests.test_datalakes.conftest import SHIPPED_ROOT

    shipped = sorted(p for p in SHIPPED_ROOT.iterdir() if p.is_dir())
    assert shipped, f"no source directories under {SHIPPED_ROOT}"
    validator = jsonschema.Draft202012Validator(schema)
    for path in shipped:
        raw = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(raw), key=lambda e: e.path)
        assert not errors, f"{path.name}: " + "; ".join(
            f"{'.'.join(str(p) for p in e.path)}: {e.message}" for e in errors
        )
