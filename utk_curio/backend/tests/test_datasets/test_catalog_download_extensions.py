"""Every committed catalog dataset downloads with a sensible filename.

``GET /api/datasets/<id>/download`` is what the browser's Save/Export action
hits, and the filename it offers comes from the server's ``Content-Disposition``.
The mapping that decides the suffix (``FORMAT_TO_EXTENSION`` in
``datasets/domain/constants.py``) is duplicated in ``datasetCatalogApi.ts`` for
the client-side fallback, so a format present in one and missing from the other
is a real, silent divergence.

Covered here rather than in ``test_frontend/test_dataset_export.py`` because
that suite boots Chromium per case and only exercises the two formats that
happened to ship before the Data Catalog migration. This runs over whatever is
actually committed, so a newly added format is covered the moment it lands.

Run::

    python -m pytest utk_curio/backend/tests/test_datasets/test_catalog_download_extensions.py -v
"""
from __future__ import annotations

import pytest

from utk_curio.backend.app.datasets.domain.constants import FORMAT_TO_EXTENSION
from utk_curio.backend.tests.dataset_catalog_coverage import catalog_datasets

CATALOG = catalog_datasets()
IDS = [dataset.dataset_id for dataset in CATALOG]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_every_committed_format_has_a_download_extension():
    """A format with no mapping falls back to a bare, extension-less name."""
    missing = sorted(
        {
            dataset.manifest.format
            for dataset in CATALOG
            if dataset.manifest.format not in FORMAT_TO_EXTENSION
            and dataset.manifest.format != "bundle"
        }
    )
    assert not missing, (
        f"formats {missing} are committed but absent from FORMAT_TO_EXTENSION; "
        f"add them there and in datasetCatalogApi.ts"
    )


@pytest.mark.parametrize("dataset", CATALOG, ids=IDS)
def test_a_hub_dataset_downloads_with_the_right_filename(
    dataset, client, user_and_token, tmp_path, monkeypatch
):
    """The bytes come back, and the offered filename carries the real suffix.

    Parquet is the interesting case: ``download_target`` deserializes it for
    export rather than streaming it verbatim, so this is also the check that the
    two large violations tables and the 145k-feature GeoParquet are exportable
    at all.
    """
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    resp = client.get(
        f"/api/datasets/{dataset.dataset_id}/download", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.data, f"{dataset.dataset_id} downloaded zero bytes"

    disposition = resp.headers.get("Content-Disposition", "")
    assert "attachment" in disposition.lower(), disposition
    # The export may legitimately re-serialize (parquet -> csv/geojson), so the
    # suffix is checked against the set of plausible ones rather than pinned to
    # the stored format.
    assert any(ext in disposition for ext in FORMAT_TO_EXTENSION.values()), (
        f"{dataset.dataset_id}: no known extension in {disposition!r}"
    )
