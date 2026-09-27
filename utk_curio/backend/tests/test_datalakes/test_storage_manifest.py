"""A storage manifest declares how its files are organized, and is checked for it."""

from __future__ import annotations

import pytest

from utk_curio.backend.app.datalakes.domain import manifest as M
from utk_curio.backend.tests.test_datalakes.conftest import a_manifest, a_storage_manifest


def parse(raw):
    return M._parse_manifest(raw, where="manifest.json")


def resource(**overrides):
    base = {"id": "files", "name": "Files", "kind": "table", "format": "csv", "path": "{name}.csv"}
    base.update(overrides)
    return base


class TestAStorageSource:
    def test_it_parses_and_derives_its_formats(self):
        m = parse(a_storage_manifest("/srv/x", [
            resource(),
            {"id": "orthos", "name": "O", "kind": "rasters", "path": "{year:int}/{tile}.tif"},
        ]))
        assert m.is_storage
        assert m.capabilities.formats == ("csv", "collection")
        assert [r.id for r in m.resources] == ["files", "orthos"]

    def test_it_must_declare_resources(self):
        with pytest.raises(M.ManifestError, match="how its files are organized"):
            parse(a_storage_manifest("/srv/x", []))

    def test_a_folder_needs_a_root_and_takes_no_base_url(self):
        raw = a_storage_manifest("/srv/x", [resource()])
        raw["provider"] = {"type": "folder"}
        with pytest.raises(M.ManifestError, match="root"):
            parse(raw)
        raw["provider"] = {"type": "folder", "root": "/srv/x", "baseUrl": "https://x"}
        with pytest.raises(M.ManifestError, match="set root"):
            parse(raw)

    def test_a_root_may_not_climb(self):
        with pytest.raises(M.ManifestError, match=r"\.\."):
            parse(a_storage_manifest("/srv/../etc", [resource()]))

    def test_it_may_not_list_formats_itself(self):
        raw = a_storage_manifest("/srv/x", [resource()], capabilities={"formats": ["csv"]})
        with pytest.raises(M.ManifestError, match="derived"):
            parse(raw)

    def test_max_files_is_lowered_never_raised(self):
        low = parse(a_storage_manifest("/srv/x", [resource()], limits={"maxFiles": 10}))
        high = parse(a_storage_manifest("/srv/x", [resource()], limits={"maxFiles": 10**9}))
        assert low.max_files == 10
        assert high.max_files == M.DEFAULT_MAX_FILES


class TestAPortal:
    def test_it_may_not_declare_resources(self):
        with pytest.raises(M.ManifestError, match="discovered live"):
            parse(a_manifest(resources=[resource()]))

    def test_it_takes_no_root(self):
        raw = a_manifest()
        raw["provider"] = {**raw["provider"], "root": "/srv"}
        with pytest.raises(M.ManifestError, match="only applies to a folder"):
            parse(raw)


class TestAResource:
    @pytest.mark.parametrize(
        "overrides, reason",
        [
            ({"id": "Bad Id"}, "lowercase"),
            ({"kind": "spreadsheet"}, "kind"),
            ({"format": None}, "format"),
            ({"format": "xlsx"}, "format"),
            ({"kind": "images", "format": "csv", "path": "{n}.jpg"}, "only applies to a table"),
            ({"kind": "images", "format": None, "path": "{name}.jpg"}, "already adds"),
            ({"path": "../x.csv"}, "path"),
            ({"datasets": "per:missing"}, "does not capture"),
            ({"datasets": "per:"}, "needs a field"),
            ({"datasets": "some"}, "must be"),
            ({"kind": "images", "format": None, "path": "{n}.jpg", "datasets": "per-file"}, "row of a collection"),
            ({"fps": 30}, "frames"),
            ({"time": "name"}, "date or strftime"),
            ({"metadata": {"path": "meta.csv"}}, "collection"),
            ({"extensions": []}, "non-empty"),
            ({"extensions": ["c.sv"]}, "invalid"),
        ],
    )
    def test_a_bad_resource_is_refused(self, overrides, reason):
        spec = resource(**overrides)
        spec = {k: v for k, v in spec.items() if v is not None}
        with pytest.raises(M.ManifestError, match=reason):
            parse(a_storage_manifest("/srv/x", [spec]))

    def test_ids_are_unique(self):
        with pytest.raises(M.ManifestError, match="used twice"):
            parse(a_storage_manifest("/srv/x", [resource(), resource()]))

    def test_extensions_default_to_the_kind(self):
        m = parse(a_storage_manifest("/srv/x", [
            {"id": "a", "name": "A", "kind": "audio", "path": "**/*"},
            resource(id="b", format="geojson", path="{n}.geojson"),
        ]))
        assert "wav" in m.resources[0].extensions
        assert m.resources[1].extensions == ("geojson", "json")

    def test_a_split_names_its_fields(self):
        spec = parse(a_storage_manifest("/srv/x", [
            resource(path="{sensor}/{day:date}.csv", datasets="per:sensor")
        ])).resources[0]
        assert spec.split_by == ("sensor",)

    def test_a_frames_resource_takes_a_frame_rate(self):
        spec = parse(a_storage_manifest("/srv/x", [
            {"id": "f", "name": "F", "kind": "frames", "path": "{sequence}_{frame:int}.jpg", "fps": 30}
        ])).resources[0]
        assert spec.fps == 30.0

    def test_a_timestamp_capture_can_be_the_time(self):
        spec = parse(a_storage_manifest("/srv/x", [
            {"id": "n", "name": "N", "kind": "audio",
             "path": "{recorded:%Y%m%d_%H%M%S}.wav", "time": "recorded"}
        ])).resources[0]
        assert spec.time == "recorded"


class TestTheHuggingFaceSlot:
    def test_it_is_known_and_maps_to_the_existing_column(self):
        from utk_curio.backend.app.datalakes.infrastructure import credentials
        from utk_curio.backend.app.users.models import User

        assert "huggingface.token" in M.KNOWN_SECRET_SLOTS
        assert credentials.SLOT_COLUMNS["huggingface.token"] == "huggingface_token"
        assert hasattr(User, "huggingface_token")

    def test_a_value_prefix_reaches_the_header(self):
        from types import SimpleNamespace

        from utk_curio.backend.app.datalakes.infrastructure import credentials

        m = parse(a_manifest(auth={
            "mode": "optional-token", "secretId": "huggingface.token",
            "headerName": "Authorization", "valuePrefix": "Bearer ",
        }))
        user = SimpleNamespace(huggingface_token="hf_abc")
        assert credentials.credential_header(user, m) == "Authorization:Bearer hf_abc"

    def test_a_value_prefix_is_a_word_and_a_space(self):
        with pytest.raises(M.ManifestError, match="valuePrefix"):
            parse(a_manifest(auth={
                "mode": "optional-token", "secretId": "huggingface.token",
                "headerName": "Authorization", "valuePrefix": "Bearer:x ",
            }))


def test_a_storage_manifest_round_trips():
    m = parse(a_storage_manifest("/srv/x", [
        resource(path="{sensor}/{day:date}.csv", datasets="per:sensor"),
        {"id": "f", "name": "F", "kind": "frames", "path": "{sequence}_{frame:int}.jpg", "fps": 10,
         "metadata": {"path": "telemetry.csv", "on": "file_name"}},
    ]))
    assert parse(M.build_manifest_dict(m)) == m
