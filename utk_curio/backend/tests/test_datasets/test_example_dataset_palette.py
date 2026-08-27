"""A seeded example's datasets must render as real palette rows, not placeholders.

This is the test that justifies the store copy in
``utk_curio/backend/app/datasets/seed.py``, and the one thing a
committed-ref-only shortcut would fail.

Two different listings are involved, and only one of them is forgiving:

* The **drawer** queries with ``includeHub=true``. ``list_catalog`` then also
  yields the hub row for a committed-catalog dataset, that row outranks the ref
  row in ``domain/dedup.py`` (real absolute path: +4), and the merge lifts
  ``installed: True`` off the loser. A ref with no copy is indistinguishable
  from a real install here.
* The **Data palette** queries with ``includeHub=false`` (see
  ``DatasetsPaletteDropdown.tsx``). ``registry.list_items()`` is skipped, so
  there is no hub row to merge with, and the only row is the placeholder
  ``InstalledDatasetRepository.list_items`` builds in its ``except`` branch.
  That row still passes ``isUserInstalledDataset`` - the placeholder sets
  ``installed=True`` - so it renders, but with ``title`` falling back to the raw
  ``dirName``, ``format`` defaulting to ``csv``, and no counts.

So the failure this guards against is not an error anywhere. It is a palette
full of rows reading ``data.urbanlab.chicago-boundary@1 / csv / (nothing)``.

Run::

    python -m pytest utk_curio/backend/tests/test_datasets/test_example_dataset_palette.py -v
"""
from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.datasets.seed import example_dep_dataset_dirs
from utk_curio.backend.tests.dataset_catalog_coverage import catalog_datasets
from utk_curio.backend.tests.test_datasets.computed_test_helpers import create_project

#: The placeholder's tell-tale description, from ``repositories/installed.py``.
NOT_INSTALLED = "Dataset is not installed on this machine."


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _example_refs():
    """The ``dataflow.datasets`` refs of the first example that declares any."""
    from pathlib import Path

    examples = Path(__file__).resolve().parents[4] / "docs" / "examples"
    for path in sorted(examples.glob("[0-9][0-9]-*.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        refs = spec.get("dataflow", {}).get("datasets") or []
        if len(refs) >= 2:
            return path.name, refs
    pytest.skip("no example declares two or more datasets")


def _project_with_refs(client, token, refs):
    """A project whose spec carries *refs*, as a seeded example's would."""
    project_id = create_project(client, token, name="Example dataset palette")
    resp = client.put(
        f"/api/projects/{project_id}",
        data=json.dumps({
            "spec": {
                "dataflow": {
                    "name": "Example dataset palette",
                    "nodes": [],
                    "edges": [],
                    "datasets": refs,
                }
            }
        }),
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return project_id


def _palette_rows(client, token, project_id):
    """What the Data palette sees: the dataflow's rows, hub excluded."""
    resp = client.get(
        f"/api/datasets/catalog?dataflowId={project_id}&includeHub=false",
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    items = resp.get_json()["items"]
    # Mirrors DatasetsPaletteDropdown: origin filter, then installed === true.
    return [
        item
        for item in items
        if item.get("origin") in {"imported", "hub", "computed"}
        and item.get("installed") is True
    ]


def test_the_committed_refs_are_declared_against_real_catalog_datasets():
    """Guards the premise: the refs name datasets that actually ship."""
    catalog_ids = {dataset.dataset_id for dataset in catalog_datasets()}
    _, refs = _example_refs()
    for ref in refs:
        assert ref["datasetId"] in catalog_ids, ref["datasetId"]
        assert ref["dirName"] in example_dep_dataset_dirs(), ref["dirName"]


def test_without_seeding_the_palette_rows_are_degraded_placeholders(
    client, user_and_token, tmp_path, monkeypatch
):
    """Documents the failure mode the seeder exists to prevent.

    Asserted rather than merely described, so that if the placeholder path ever
    changes, whoever changes it learns that the seeder's rationale moved with
    it. Note every row still claims ``installed: True`` - which is exactly why
    this is invisible without looking at the rendered fields.
    """
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    _, refs = _example_refs()

    project_id = _project_with_refs(client, token, refs)
    rows = _palette_rows(client, token, project_id)

    assert len(rows) == len(refs), "the refs should still produce palette rows"
    for row in rows:
        assert row["title"] == row["dirName"], (
            "expected the placeholder's dirName-as-title; if this now shows a "
            "real title, the un-seeded path improved and this test should be "
            "updated rather than deleted"
        )
        assert row["description"] == NOT_INSTALLED
        assert row["rowCount"] is None and row["featureCount"] is None


def test_after_seeding_the_palette_rows_carry_real_metadata(
    client, user_and_token, tmp_path, monkeypatch
):
    """The payoff: real titles, real formats, real counts, no placeholder text.

    Seeded for *this* user's key, not ``guest``: the dataset store is per user
    (``.curio/users/<key>/datasets/``), and the startup seeder only ever covers
    the shared guest. Provisioning a real signed-in user is precisely the job of
    ``ensure_user_datasets_initialized``, which ``load_project`` calls.
    """
    from utk_curio.backend.app.datasets.seed import ensure_user_datasets_initialized
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    _, refs = _example_refs()

    project_id = _project_with_refs(client, token, refs)
    ensure_user_datasets_initialized(_user_dir_key(user))
    rows = _palette_rows(client, token, project_id)

    assert len(rows) == len(refs)
    by_id = {row["id"]: row for row in rows}
    expected = {dataset.dataset_id: dataset for dataset in catalog_datasets()}

    for ref in refs:
        row = by_id[ref["datasetId"]]
        dataset = expected[ref["datasetId"]]

        assert row["description"] != NOT_INSTALLED, row["description"]
        assert row["title"] != row.get("dirName"), (
            f"{row['id']}: palette would show the directory name as the title"
        )
        assert row["title"] == dataset.manifest.name, row["title"]
        # The format chip: a lean ref carries none, so a placeholder always says
        # "csv". Getting the real one is only possible from the store manifest.
        assert row["format"] == dataset.manifest.format, (
            f"{row['id']}: format chip would read {row['format']!r}, not "
            f"{dataset.manifest.format!r}"
        )
        assert row["sizeBytes"], f"{row['id']}: no size, so no size on the card"
        if dataset.manifest.format != "geotiff":
            assert row["rowCount"] or row["featureCount"], (
                f"{row['id']}: neither a row nor a feature count, so the card "
                f"renders no count"
            )


def test_the_drawer_works_either_way(
    client, user_and_token, tmp_path, monkeypatch
):
    """The forgiving listing, pinned so the asymmetry stays documented.

    With ``includeHub=true`` the hub row wins the dedupe and supplies real
    metadata even with nothing in the store. This is why the degraded palette
    was easy to miss: the surface most people look at was always fine.
    """
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    _, refs = _example_refs()

    project_id = _project_with_refs(client, token, refs)
    resp = client.get(
        f"/api/datasets/catalog?dataflowId={project_id}&includeHub=true",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    rows = {item["id"]: item for item in resp.get_json()["items"]}

    expected = {dataset.dataset_id: dataset for dataset in catalog_datasets()}
    for ref in refs:
        row = rows[ref["datasetId"]]
        assert row["installed"] is True, "the ref should mark it in-dataflow"
        assert row["title"] == expected[ref["datasetId"]].manifest.name
        assert row["description"] != NOT_INSTALLED


def test_execution_paths_resolve_for_every_example_dataset(
    client, user_and_token, tmp_path, monkeypatch
):
    """``curio_dataset_path`` must resolve with no ref and no dataflow id.

    The path a seeded example takes on its first run: the dataset is not in the
    account-level index (that only covers ``imported.``/``computed.`` prefixes),
    so resolution falls through to ``list_catalog(include_hub=True)`` and then
    has to survive the ``_contained_path`` guard - which it does only because
    ``catalog_root()`` is one of ``paths._allowed_read_roots``. Nothing else
    covers that route: every case in ``test_execution_path_resolution`` imports a
    CSV first and lands on the index fast path.
    """
    from pathlib import Path

    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    user, _token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    datasets = catalog_datasets()
    assert datasets, "no committed datasets; this test would be vacuous"
    ids = [dataset.dataset_id for dataset in datasets]

    resolved = DatasetCatalogService(user).resolve_execution_paths(ids)

    assert set(resolved) == set(ids), (
        f"unresolved: {sorted(set(ids) - set(resolved))}"
    )
    for dataset in datasets:
        assert Path(resolved[dataset.dataset_id]).samefile(dataset.data_file)


def test_an_id_carrying_its_major_does_not_resolve(client, user_and_token, tmp_path, monkeypatch):
    """``curio_dataset_path`` takes the bare id, and the failure is silent.

    ``SAFE_DATASET_ID_RE`` permits ``@``, so ``"<id>@1"`` passes validation but
    misses the by-id lookup, and ``routes.py`` swallows the miss and returns
    ``{}`` - leaving the node to fail at run time with the sandbox's generic
    "not available in this environment". Pinned here so the distinction between
    ``id`` and ``dirName`` stays a documented, tested fact.
    """
    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    user, _token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    dataset = catalog_datasets()[0]
    service = DatasetCatalogService(user)

    assert service.resolve_execution_paths([dataset.dataset_id])
    assert service.resolve_execution_paths([dataset.manifest.dir_name]) == {}
