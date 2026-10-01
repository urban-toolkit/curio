"""A GeoTIFF import is a TIFF file.

An upload's format comes from its name, and a download's from its URL and
headers. A file stored as ``geotiff`` must also start the way a TIFF does, so
one that does not is refused, says why, and leaves nothing behind. The Discovery Catalog
download of the same case is in ``test_discovery/test_acquire.py``.
"""

from __future__ import annotations

import io

import numpy as np
import pytest

#: What a portal, or a mistaken rename, hands over under a ``.tif`` name.
NOT_A_TIFF = b"city,value\nChicago,1\n"


def _geotiff(path, **creation_options) -> bytes:
    import rasterio
    from rasterio.transform import from_origin

    with rasterio.open(
        path, "w", driver="GTiff", width=4, height=4, count=1, dtype="uint8",
        crs="EPSG:4326", transform=from_origin(-87.7, 41.9, 0.01, 0.01), **creation_options,
    ) as dst:
        dst.write(np.arange(16, dtype="uint8").reshape(1, 4, 4))
    return path.read_bytes()


def _import(client, token, name: str, body: bytes):
    return client.post(
        "/api/datasets/import",
        headers={"Authorization": f"Bearer {token}"},
        data={"file": (io.BytesIO(body), name)},
        content_type="multipart/form-data",
    )


@pytest.fixture()
def mutations(app, user_and_token):
    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    user, _token = user_and_token
    return DatasetCatalogService(user)._mutations


def _store(mutations) -> list[str]:
    from utk_curio.backend.app.datasets.infrastructure.storage import user_datasets_dir

    root = user_datasets_dir(mutations._paths._user_key())
    return sorted(p.name for p in root.iterdir()) if root.is_dir() else []


class TestAnUpload:
    @pytest.mark.parametrize("name", ["roads.tif", "roads.tiff"])
    def test_one_that_is_not_a_tiff_is_refused(self, client, user_and_token, mutations, name):
        _user, token = user_and_token
        before = _store(mutations)
        resp = _import(client, token, name, NOT_A_TIFF)
        assert resp.status_code == 400, resp.get_data(as_text=True)
        assert resp.get_json()["error"] == (
            f"{name} is not a TIFF file, so it cannot be imported as a GeoTIFF."
        )
        assert _store(mutations) == before

    @pytest.mark.parametrize("options", [{}, {"BIGTIFF": "YES"}], ids=["tiff", "bigtiff"])
    def test_a_geotiff_still_imports(self, client, user_and_token, tmp_path, options):
        _user, token = user_and_token
        resp = _import(client, token, "dem.tif", _geotiff(tmp_path / "dem.tif", **options))
        assert resp.status_code == 201, resp.get_data(as_text=True)
        assert resp.get_json()["format"] == "geotiff"


class TestAFileAlreadyOnDisk:
    def test_one_that_is_not_a_tiff_is_refused(self, mutations, tmp_path):
        from utk_curio.backend.app.datasets.domain.errors import DatasetCatalogError

        src = tmp_path / "dem.tif.part"
        src.write_bytes(NOT_A_TIFF)
        before = _store(mutations)
        with pytest.raises(DatasetCatalogError, match="dem.tif is not a TIFF file"):
            mutations._install_imported_path(src, "dem.tif", "geotiff")
        assert _store(mutations) == before
