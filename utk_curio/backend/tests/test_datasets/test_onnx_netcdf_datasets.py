"""ONNX models and NetCDF files in the Data Catalog.

Both formats are stored as the file itself, as a GeoTIFF is: ``onnx`` (``.onnx``)
and ``netcdf`` (``.nc``). Each imports and lists with its size and format and no
row preview. A file whose bytes are not what its name says is refused, says
why, and leaves nothing behind: a NetCDF file is known by its first bytes, and
an ONNX model, which has none, by its protobuf fields.

Several NetCDF variables, one file each as WRF writes them, list as one group,
the way a GTFS feed's tables do, whether they were imported or ship in the
catalog.

What ``curio_load_data`` returns for each format is in
``sandbox/tests/test_catalog_helpers.py``.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from utk_curio.backend.tests._support.model_files import (
    NETCDF_SIGNATURES,
    netcdf_file,
    tiny_onnx_model,
)

REPO = Path(__file__).resolve().parents[4]

#: ONNX exports already in the repository, made by real exporters, so the check
#: is not judged only against the model this suite builds by hand.
REAL_MODELS = [
    REPO / "models" / "model.curio.ddrnet23-slim@1" / "files" / "ddrnet23_slim.onnx",
    REPO / "utk_curio" / "backend" / "tests" / "test_discovery" / "fixtures"
    / "huggingface-models" / "synthetic-segmentation.onnx",
]

#: The five variables SCOUT's weather routing reads, one file each.
WRF_VARIABLES = ("RAIN", "RH2", "T2", "WDIR10", "WSPD10")

CSV = b"city,value\nChicago,1\n"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _import(client, token, name: str, body: bytes):
    return client.post(
        "/api/datasets/import",
        headers=_auth(token),
        data={"file": (io.BytesIO(body), name)},
        content_type="multipart/form-data",
    )


def _get(client, token, url: str, **params):
    resp = client.get(url, headers=_auth(token), query_string=params)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _catalog(client, token, **params) -> list[dict]:
    return _get(client, token, "/api/datasets/catalog", **params)["items"]


@pytest.fixture()
def mutations(app, user_and_token):
    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    user, _token = user_and_token
    return DatasetCatalogService(user)._mutations


def _store(mutations) -> list[str]:
    from utk_curio.backend.app.datasets.infrastructure.storage import user_datasets_dir

    root = user_datasets_dir(mutations._paths._user_key())
    return sorted(p.name for p in root.iterdir()) if root.is_dir() else []


def _netcdf_bytes(tmp_path: Path, fmt: str = "NETCDF4", variable: str = "RAIN") -> bytes:
    return netcdf_file(tmp_path / f"{variable}_{fmt}.nc", variable, fmt=fmt).read_bytes()


def _assert_listed_without_rows(client, token, item: dict, fmt: str, size: int) -> None:
    """The import's answer, its catalog row and its details say the same: the
    format, the file's size and no rows; its preview has no rows to show."""
    assert item["format"] == fmt
    assert item["sizeBytes"] == size
    assert item["rowCount"] is None and item["featureCount"] is None

    listed = next(i for i in _catalog(client, token) if i["id"] == item["id"])
    assert (listed["format"], listed["sizeBytes"]) == (fmt, size)
    assert listed["rowCount"] is None and listed["featureCount"] is None

    details = _get(client, token, f"/api/datasets/{item['id']}")
    assert (details["format"], details["sizeBytes"]) == (fmt, size)

    preview = _get(client, token, f"/api/datasets/{item['id']}/preview")
    assert preview["unsupported"] is True
    assert preview["rows"] == []
    assert "no rows to preview" in preview["message"]


class TestAnOnnxModel:
    def test_it_imports_lists_and_loads_by_its_id(self, client, user_and_token):
        _user, token = user_and_token
        body = tiny_onnx_model()
        resp = _import(client, token, "tiny.onnx", body)
        assert resp.status_code == 201, resp.get_data(as_text=True)
        item = resp.get_json()
        _assert_listed_without_rows(client, token, item, "onnx", len(body))
        # A node runs the model in its own code: the sandbox carries no model
        # from one node to the next, so the loader returns nothing.
        assert item["loaderSnippet"]["code"] == f'session = curio_load_data("{item["id"]}")'
        assert item["loaderSnippet"]["returnVariable"] is None

    @pytest.mark.parametrize("model", REAL_MODELS, ids=lambda p: p.name)
    def test_a_real_export_imports(self, client, user_and_token, model):
        _user, token = user_and_token
        resp = _import(client, token, model.name, model.read_bytes())
        assert resp.status_code == 201, resp.get_data(as_text=True)
        assert resp.get_json()["format"] == "onnx"

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(CSV, id="csv"),
            pytest.param(b"\x89PNG\r\n\x1a\n" + b"\x00" * 24, id="png"),
            pytest.param(b"PK\x03\x04" + b"\x00" * 26, id="zip"),
            pytest.param(b"", id="empty"),
            pytest.param(tiny_onnx_model()[:-1], id="truncated"),
            pytest.param(tiny_onnx_model() + b"\x00", id="trailing-byte"),
            pytest.param(tiny_onnx_model()[:2], id="no-graph"),
            # A graph field whose length runs past any file: refused, not a 500.
            pytest.param(b"\x3a" + b"\xff" * 9 + b"\x01", id="huge-length"),
        ],
    )
    def test_a_file_that_is_not_a_model_is_refused(self, client, user_and_token, mutations, body):
        _user, token = user_and_token
        before = _store(mutations)
        resp = _import(client, token, "model.onnx", body)
        assert resp.status_code == 400, resp.get_data(as_text=True)
        assert resp.get_json()["error"] == (
            "model.onnx is not an ONNX model, so it cannot be imported as ONNX."
        )
        assert _store(mutations) == before

    def test_a_netcdf_file_named_onnx_is_refused(self, client, user_and_token, mutations, tmp_path):
        _user, token = user_and_token
        before = _store(mutations)
        resp = _import(client, token, "model.onnx", _netcdf_bytes(tmp_path))
        assert resp.status_code == 400, resp.get_data(as_text=True)
        assert "is not an ONNX model" in resp.get_json()["error"]
        assert _store(mutations) == before


class TestANetcdfFile:
    @pytest.mark.parametrize("fmt", list(NETCDF_SIGNATURES))
    def test_each_kind_imports_and_lists(self, client, user_and_token, tmp_path, fmt):
        """Classic, 64-bit offset and 64-bit data files start with ``CDF`` and
        their version; a NetCDF-4 file is an HDF5 file."""
        _user, token = user_and_token
        body = _netcdf_bytes(tmp_path, fmt)
        assert body.startswith(NETCDF_SIGNATURES[fmt])
        resp = _import(client, token, "rain.nc", body)
        assert resp.status_code == 201, resp.get_data(as_text=True)
        item = resp.get_json()
        _assert_listed_without_rows(client, token, item, "netcdf", len(body))
        assert item["loaderSnippet"]["code"] == f'ds = curio_load_data("{item["id"]}")'
        assert item["loaderSnippet"]["returnVariable"] is None

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(CSV, id="csv"),
            pytest.param(b"II*\x00" + b"\x00" * 16, id="tiff"),
            pytest.param(b"CDF\x03" + b"\x00" * 16, id="unknown-version"),
            pytest.param(b"", id="empty"),
            pytest.param(tiny_onnx_model(), id="onnx"),
        ],
    )
    def test_a_file_that_is_not_netcdf_is_refused(self, client, user_and_token, mutations, body):
        _user, token = user_and_token
        before = _store(mutations)
        resp = _import(client, token, "rain.nc", body)
        assert resp.status_code == 400, resp.get_data(as_text=True)
        assert resp.get_json()["error"] == (
            "rain.nc is not a NetCDF file, so it cannot be imported as NetCDF."
        )
        assert _store(mutations) == before


class TestAFileAlreadyOnDisk:
    """A download lands through this path, as the GeoTIFF check's does."""

    @pytest.mark.parametrize(
        "name, fmt, message",
        [
            ("model.onnx", "onnx", "model.onnx is not an ONNX model"),
            ("rain.nc", "netcdf", "rain.nc is not a NetCDF file"),
        ],
    )
    def test_one_whose_bytes_are_not_its_format_is_refused(self, mutations, tmp_path, name, fmt, message):
        from utk_curio.backend.app.datasets.domain.errors import DatasetCatalogError

        src = tmp_path / f"{name}.part"
        src.write_bytes(CSV)
        before = _store(mutations)
        with pytest.raises(DatasetCatalogError, match=message):
            mutations._install_imported_path(src, name, fmt)
        assert _store(mutations) == before


def _group_item(client, token, group_id: str, **params) -> dict:
    grouped = [i for i in _catalog(client, token, groupOsm="true", **params) if i["id"] == group_id]
    assert len(grouped) == 1, grouped
    return grouped[0]


def _install(client, token, project_id: str, dataset_id: str) -> dict:
    resp = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps({"datasetId": dataset_id}),
        headers={**_auth(token), "Content-Type": "application/json"},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


class TestAGroupOfNetcdfVariables:
    def test_imported_variables_list_as_one_group(self, client, user_and_token, mutations, tmp_path):
        """The variables are stored as they are, a dataset each, and share a
        ``netcdf.`` group id, as a GTFS feed's tables share a ``gtfs.`` one."""
        from utk_curio.backend.tests.test_datasets.computed_test_helpers import create_project

        _user, token = user_and_token
        group_id = "netcdf.xa1b2c3d4"
        sizes = {}
        for offset, variable in enumerate(WRF_VARIABLES):
            src = netcdf_file(tmp_path / f"{variable}.nc", variable, offset=offset)
            sizes[variable] = src.stat().st_size
            mutations._install_imported_path(
                src, f"{variable}.nc", "netcdf",
                title=f"WRF sample ({variable})", group_id=group_id, layer_name=variable,
            )

        members = {i["layerName"]: i for i in _catalog(client, token) if i.get("groupId") == group_id}
        assert sorted(members) == sorted(WRF_VARIABLES)
        assert {m["format"] for m in members.values()} == {"netcdf"}
        assert {name: m["sizeBytes"] for name, m in members.items()} == sizes

        group = _group_item(client, token, group_id)
        assert group["format"] == "netcdf"
        assert group["title"] == "WRF sample"
        assert group["sourceLabel"] == "NetCDF Import"
        assert group["uri"] == f"curio://netcdf/{group_id}"
        assert group["groupLayerIds"] == [members[name]["id"] for name in sorted(WRF_VARIABLES)]
        assert group["sizeBytes"] == sum(sizes.values())
        assert "5 variable(s)" in group["description"]
        # The group's own loader never reads the group id as one dataset.
        assert f'curio_load_data("{group_id}")' not in group["loaderSnippet"]["code"]

        details = _get(client, token, f"/api/datasets/{group_id}")
        assert (details["id"], details["format"]) == (group_id, "netcdf")

        preview = _get(client, token, f"/api/datasets/{group_id}/preview")
        assert preview["bundle"] is True
        assert [p["label"] for p in preview["parts"]] == sorted(WRF_VARIABLES)
        for part in preview["parts"]:
            assert part["format"] == "netcdf"
            assert part["unsupported"] is True and part["rows"] == []

        # Adding the group to a project adds every variable.
        project_id = create_project(client, token, name="Weather routing")
        _install(client, token, project_id, group_id)
        assert _group_item(client, token, group_id, dataflowId=project_id)["installed"] is True
        installed = [
            i for i in _catalog(client, token, dataflowId=project_id) if i.get("groupId") == group_id
        ]
        assert len(installed) == len(WRF_VARIABLES) and all(i["installed"] for i in installed)

    def test_shipped_variables_list_as_one_group_that_says_what_they_say(
        self, client, user_and_token, tmp_path, monkeypatch
    ):
        """Variables that ship in the catalog every account shares form a group
        from their manifests alone (``groupId`` and ``layerName``). The group
        says what its variables say, as a Discovery download's group does, and
        any group id with the prefix works, not only the minted ``x<hex>`` kind."""
        from utk_curio.backend.tests.test_datasets.computed_test_helpers import create_project

        _user, token = user_and_token
        group_id = "netcdf.wrf-sample"
        root = tmp_path / "catalog"
        ids = []
        for variable in WRF_VARIABLES:
            dataset_id = f"data.test.wrf-{variable.lower()}"
            folder = root / f"{dataset_id}@1"
            (folder / "data").mkdir(parents=True)
            netcdf_file(folder / "data" / f"{variable}.nc", variable)
            (folder / "manifest.json").write_text(json.dumps({
                "id": dataset_id,
                "name": f"WRF sample ({variable})",
                "version": "1.0.0",
                "format": "netcdf",
                "description": f"{variable} over the example area.",
                "publisher": "Curio",
                "sourceLabel": "SCOUT",
                "license": "MIT",
                "tags": ["netcdf", "weather"],
                "dataFile": f"data/{variable}.nc",
                "compatibility": {"major": 1},
                "groupId": group_id,
                "layerName": variable,
            }), encoding="utf-8")
            ids.append(dataset_id)
        monkeypatch.setenv("CURIO_CATALOG_ROOT", str(root))

        members = [i for i in _catalog(client, token) if i.get("groupId") == group_id]
        assert sorted(m["id"] for m in members) == sorted(ids)
        assert {m["format"] for m in members} == {"netcdf"}

        group = _group_item(client, token, group_id)
        assert group["format"] == "netcdf"
        assert group["origin"] == "hub"
        assert group["sourceLabel"] == "SCOUT"
        assert group["tags"] == ["netcdf", "weather"]
        assert group["groupLayerIds"] == ids

        # It still says so once the project it is added to is open.
        project_id = create_project(client, token, name="Weather routing")
        _install(client, token, project_id, group_id)
        installed = _group_item(client, token, group_id, dataflowId=project_id)
        assert installed["installed"] is True
        assert (installed["origin"], installed["sourceLabel"]) == ("hub", "SCOUT")
