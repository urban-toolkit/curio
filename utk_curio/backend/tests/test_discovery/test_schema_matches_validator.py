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


def test_every_auth_key_the_validator_writes_is_declared(schema):
    """A key's declaration included: what API Settings shows for it, and
    whether the operator may set it for everyone."""
    from utk_curio.backend.tests.test_discovery.conftest import a_manifest

    raw = a_manifest(auth={
        "mode": "optional-token", "secretId": "acme.tiles-key", "headerName": "X-Acme-Key",
        "valuePrefix": "Bearer ", "helpUrl": "https://acme.example/keys", "label": "Acme tiles key",
        "placeholder": "acme_...", "note": "Acme bills each request to you.", "operatorDefault": True,
    })
    written = set(M.build_manifest_dict(M._parse_manifest(raw, where="manifest.json"))["auth"])
    declared = schema["properties"]["auth"]["properties"]
    assert {"label", "placeholder", "note", "operatorDefault"} <= written
    assert written <= set(declared)
    assert declared["operatorDefault"]["type"] == "boolean"
    assert declared["label"]["maxLength"] == M.MAX_KEY_LABEL_CHARS
    assert declared["placeholder"]["maxLength"] == M.MAX_KEY_LABEL_CHARS
    assert declared["note"]["maxLength"] == M.MAX_KEY_NOTE_CHARS


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
    """The ceiling is the instance's (``--discovery-max-download-mb``), so the
    schema names no fixed maximum, and the validator reads a larger value as
    the ceiling rather than refusing the manifest."""
    field = schema["properties"]["capabilities"]["properties"]["maxDownloadBytes"]
    assert "maximum" not in field and field["minimum"] == 1
    from utk_curio.backend.tests.test_discovery.conftest import a_manifest

    raw = a_manifest()
    raw["capabilities"] = {**raw.get("capabilities", {}), "maxDownloadBytes": M.DEFAULT_MAX_DOWNLOAD_BYTES * 4}
    parsed = M._parse_manifest(raw, where="manifest.json")
    assert parsed.capabilities.max_download_bytes == M.DEFAULT_MAX_DOWNLOAD_BYTES


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


class TestJsonLinesOptions:
    """A jsonl table's ``options`` as ``domain/json_rows.py`` reads them."""

    DETECTIONS = {
        "id": "detections", "name": "Detections", "kind": "table", "format": "jsonl",
        "path": "{crossing}/data/*_{year:int}_{month:int}.jsonl",
        "options": {
            "parse": ["value"],
            "columns": {"timestamp": {"path": "timestamp", "type": "timestamp"},
                        "image_timestamp_ns": "value.image_timestamp_ns"},
            "unpack": [
                {"path": "value.models_results", "key": "model",
                 "columns": {"inference_time_seconds": "inference_time_seconds"}},
                {"path": "detections",
                 "columns": {"class": "class", "confidence": "confidence",
                             "x0": "bbox.0", "y0": "bbox.1", "x1": "bbox.2", "y1": "bbox.3"}},
            ],
        },
    }

    def _options(self, schema):
        return schema["properties"]["resources"]["items"]["properties"]["options"]["properties"]

    def test_the_option_and_level_keys_are_the_validators(self, schema):
        from utk_curio.backend.app.discovery.domain import json_rows as R

        assert set(R.OPTION_KEYS) <= set(self._options(schema))
        level = self._options(schema)["unpack"]["items"]
        assert sorted(level["properties"]) == sorted(R.LEVEL_KEYS) and level["additionalProperties"] is False

    def test_a_columns_type_and_keys_are_the_validators(self, schema):
        from utk_curio.backend.app.discovery.domain import json_rows as R

        column = schema["$defs"]["jsonlColumn"]
        assert column["properties"]["type"]["enum"] == list(R.COLUMN_TYPES)
        assert sorted(column["properties"]) == sorted(R.COLUMN_KEYS) and column["additionalProperties"] is False
        assert schema["$defs"]["jsonlColumns"]["additionalProperties"] == {
            "anyOf": [{"$ref": "#/$defs/jsonlPath"}, {"$ref": "#/$defs/jsonlColumn"}],
        }

    def test_the_bounds_are_the_validators(self, schema):
        from utk_curio.backend.app.discovery.domain import json_rows as R

        options = self._options(schema)
        assert options["parse"]["maxItems"] == R.MAX_PARSE
        assert options["unpack"]["maxItems"] == R.MAX_LEVELS
        assert schema["$defs"]["jsonlColumns"]["maxProperties"] == R.MAX_COLUMNS
        assert schema["$defs"]["jsonlPath"]["maxLength"] == R.MAX_PATH_CHARS
        assert schema["$defs"]["jsonlColumnName"]["maxLength"] == R.MAX_NAME_CHARS

    def test_a_table_of_detections_is_read_by_both(self, schema):
        jsonschema = pytest.importorskip("jsonschema")
        from utk_curio.backend.tests.test_discovery.conftest import a_storage_manifest

        raw = a_storage_manifest("/srv/idot", [self.DETECTIONS])
        assert not list(jsonschema.Draft202012Validator(schema).iter_errors(raw))
        parsed = M._parse_manifest(raw, where="manifest.json")
        assert parsed.resources[0].format == "jsonl"
        assert parsed.resources[0].extensions == ("jsonl", "ndjson")

    @pytest.mark.parametrize("options", [
        {"unpack": [{"path": "value.models_results", "keys": "model"}]},
        {"columns": {"__curio_row": "a"}},
        {"columns": {"a": "b..c"}},
        {"parse": [""]},
        {"unpack": []},
        {"columns": {}},
        {"columns": {"t": {"path": "t", "type": "date"}}},
        {"columns": {"t": {"type": "int"}}},
        {"unpack": [{"path": "a", "columns": {"c": {"path": "c", "unit": "s"}}}]},
    ], ids=[
        "unknown-level-key", "reserved-prefix", "empty-name-in-path", "parse-empty-path", "unpack-empty",
        "no-columns", "unknown-type", "typed-column-without-path", "unknown-column-key-in-a-level",
    ])
    def test_options_both_refuse(self, schema, options):
        jsonschema = pytest.importorskip("jsonschema")
        from utk_curio.backend.tests.test_discovery.conftest import a_storage_manifest

        raw = a_storage_manifest("/srv/idot", [{**self.DETECTIONS, "options": options}])
        assert list(jsonschema.Draft202012Validator(schema).iter_errors(raw))
        with pytest.raises(M.ManifestError, match=r"manifest\.resources\[0\]\.options: "):
            M._parse_manifest(raw, where="manifest.json")

    def test_a_csv_table_with_them_is_refused(self):
        from utk_curio.backend.tests.test_discovery.conftest import a_storage_manifest

        raw = a_storage_manifest("/srv/idot", [{**self.DETECTIONS, "format": "csv", "path": "a.csv"}])
        with pytest.raises(M.ManifestError, match="a csv table reads no parse, columns, unpack"):
            M._parse_manifest(raw, where="manifest.json")


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
