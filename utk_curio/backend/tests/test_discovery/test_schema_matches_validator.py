"""``docs/schemas/discovery-source.v1.json`` and the validator agree.

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

from utk_curio.backend.app.discovery.domain import manifest as M
from utk_curio.backend.app.discovery.domain.source_id import SOURCE_ID_RE

SCHEMA_PATH = Path(__file__).resolve().parents[4] / "docs" / "schemas" / "discovery-source.v1.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_the_schema_file_exists_and_is_2020_12(schema):
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith("docs/schemas/discovery-source.v1.json")


def test_the_id_pattern_is_the_validators(schema):
    assert schema["properties"]["id"]["pattern"] == SOURCE_ID_RE.pattern


def test_the_provider_enum_is_the_registry(schema):
    """The assertion that stops a new provider landing in one place only."""
    assert schema["properties"]["provider"]["properties"]["type"]["enum"] == sorted(M.PROVIDER_TYPES)


def test_the_auth_mode_enum_matches(schema):
    assert schema["properties"]["auth"]["properties"]["mode"]["enum"] == sorted(M.AUTH_MODES)


def test_the_auth_scheme_enum_matches(schema):
    enum = schema["properties"]["auth"]["properties"]["scheme"]["enum"]
    assert enum == sorted(M.AUTH_SCHEMES) == ["header", "query"]


def test_the_query_parameter_name_pattern_matches(schema):
    assert schema["properties"]["auth"]["properties"]["paramName"]["pattern"] == M._PARAM_NAME_RE.pattern


def test_the_secret_id_pattern_matches(schema):
    assert schema["properties"]["auth"]["properties"]["secretId"]["pattern"] == M._SECRET_ID_RE.pattern


def test_the_icon_pattern_matches(schema):
    assert schema["properties"]["icon"]["pattern"] == M._ICON_RE.pattern


def test_the_format_enum_is_the_acquirable_set(schema):
    formats = schema["properties"]["capabilities"]["properties"]["formats"]["items"]["enum"]
    assert formats == sorted(M.DISCOVERY_ACQUIRABLE_FORMATS)


def test_the_acquirable_set_is_a_subset_of_what_the_data_catalog_stores(schema):
    """The two catalogs meet here: a source can only deliver a format the Data
    Catalog can hold. Narrower by design - shp needs sibling files and bundle
    is a node output, so neither is remotely acquirable."""
    from utk_curio.backend.app.datasets.domain.manifest import SUPPORTED_FORMATS

    assert set(M.DISCOVERY_ACQUIRABLE_FORMATS) < set(SUPPORTED_FORMATS)


def test_the_download_ceiling_matches(schema):
    ceiling = schema["properties"]["capabilities"]["properties"]["maxDownloadBytes"]["maximum"]
    assert ceiling == M.DEFAULT_MAX_DOWNLOAD_BYTES


def test_required_fields_match_the_validator(schema):
    """Refusing each one in turn proves the schema's `required` is the truth,
    rather than a list someone kept up to date by hand."""
    from utk_curio.backend.tests.test_discovery.conftest import a_manifest

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
    from utk_curio.backend.tests.test_discovery.conftest import SHIPPED_ROOT

    shipped = sorted(p for p in SHIPPED_ROOT.iterdir() if p.is_dir())
    assert shipped, f"no source directories under {SHIPPED_ROOT}"
    validator = jsonschema.Draft202012Validator(schema)
    for path in shipped:
        raw = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(raw), key=lambda e: e.path)
        assert not errors, f"{path.name}: " + "; ".join(
            f"{'.'.join(str(p) for p in e.path)}: {e.message}" for e in errors
        )


def test_the_resource_kinds_match(schema):
    kinds = schema["properties"]["resources"]["items"]["properties"]["kind"]["enum"]
    assert kinds == sorted(M.RESOURCE_KINDS)


def test_the_table_formats_match(schema):
    formats = schema["properties"]["resources"]["items"]["properties"]["format"]["enum"]
    assert formats == sorted(M.TABLE_FORMATS)


def test_the_resource_id_pattern_matches(schema):
    pattern = schema["properties"]["resources"]["items"]["properties"]["id"]["pattern"]
    assert pattern == M._RESOURCE_ID_RE.pattern


def test_the_file_ceiling_matches(schema):
    assert schema["properties"]["limits"]["properties"]["maxFiles"]["maximum"] == M.DEFAULT_MAX_FILES


def test_a_storage_source_is_required_to_declare_resources(schema):
    jsonschema = pytest.importorskip("jsonschema")
    from utk_curio.backend.tests.test_discovery.conftest import a_storage_manifest

    validator = jsonschema.Draft202012Validator(schema)
    raw = a_storage_manifest("/srv/x", [
        {"id": "a", "name": "A", "kind": "table", "format": "csv", "path": "a.csv"}
    ])
    assert not list(validator.iter_errors(raw))
    raw.pop("resources")
    assert list(validator.iter_errors(raw))
    with pytest.raises(M.ManifestError):
        M._parse_manifest(raw, where="manifest.json")


class TestParameters:
    """``parameters``, at the source and on a resource, as the validator reads it."""

    def _parameter(self, schema):
        return schema["$defs"]["parameter"]

    def test_both_places_refer_to_the_one_declaration(self, schema):
        source = schema["properties"]["parameters"]["items"]
        resource = schema["properties"]["resources"]["items"]["properties"]["parameters"]["items"]
        assert source == resource == {"$ref": "#/$defs/parameter"}

    def test_the_type_enum_is_the_validators(self, schema):
        from utk_curio.backend.app.discovery.domain import parameters as P

        assert self._parameter(schema)["properties"]["type"]["enum"] == list(P.PARAMETER_TYPES)

    def test_the_area_forms_are_the_validators(self, schema):
        from utk_curio.backend.app.discovery.domain import parameters as P

        assert self._parameter(schema)["properties"]["accepts"]["items"]["enum"] == list(P.AREA_FORMS)

    def test_the_id_pattern_and_the_list_bound_are_the_validators(self, schema):
        from utk_curio.backend.app.discovery.domain import parameters as P

        assert self._parameter(schema)["properties"]["id"]["pattern"] == P._ID_RE.pattern
        assert schema["properties"]["parameters"]["maxItems"] == P.MAX_PARAMETERS
        assert self._parameter(schema)["properties"]["options"]["maxItems"] == P.MAX_OPTIONS

    def test_the_tag_keys_are_the_validators(self, schema):
        from utk_curio.backend.app.discovery.domain import parameters as P

        suggestions = self._parameter(schema)["properties"]["suggestions"]
        assert suggestions["items"]["pattern"] == P.TAG_KEY_RE.pattern
        assert suggestions["maxItems"] == P.MAX_OPTIONS

    def test_every_key_the_validator_writes_is_declared(self, schema):
        """Derived, not restated: one maximal declaration of each type, read
        and written back by the validator, names every key it knows."""
        from utk_curio.backend.app.discovery.domain import parameters as P

        maximal = [
            {"id": "a", "type": "area", "label": "A", "description": "d", "required": True,
             "accepts": ["box", "names"], "maxAreaKm2": 4},
            {"id": "b", "type": "dateRange", "label": "B", "minDate": "2020-01-01", "maxDate": "2030-01-01"},
            {"id": "c", "type": "choice", "label": "C", "options": [{"value": "x", "label": "X"}],
             "multiple": True, "default": ["x"]},
            {"id": "d", "type": "number", "label": "D", "min": 0, "max": 9, "step": 1, "unit": "m"},
            {"id": "e", "type": "text", "label": "E", "pattern": "[a-z]+"},
            {"id": "f", "type": "tags", "label": "F", "suggestions": ["amenity"], "default": ["amenity=*"]},
        ]
        written: set[str] = set()
        for spec in P.parse_parameters(maximal, where="parameters"):
            written |= set(P.declaration_dict(spec))
        assert set(self._parameter(schema)["properties"]) == written
