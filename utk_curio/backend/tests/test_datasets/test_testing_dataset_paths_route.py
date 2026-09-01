"""``/api/testing/dataset-paths`` — the mapping the e2e ground truth runs on.

The e2e harness computes each workflow's expected output by POSTing node code
straight to the sandbox's ``/exec``, bypassing the backend on purpose so the
comparison stays independent. That means it also has to supply the
``dataset_paths`` mapping ``/processPythonCode`` would normally attach, and for
a while it built that mapping itself by scanning ``datasets/`` in the pytest
process.

That is only correct while the sandbox shares a filesystem with the test
runner. Against a compose stack under ``CURIO_E2E_USE_EXISTING`` it does not:
the harness handed the sandbox host paths like
``/home/runner/work/curio/curio/datasets/...`` for files the sandbox sees at
``/app/datasets/...``, and all six curated examples whose loaders resolve a
dataset by id died on ``FileNotFoundError``. It cost a full 24-minute e2e job
to learn that, which is why the property is pinned here instead.

The claim these tests make is the one that was violated: **the server resolves
the path, in the server's own filesystem, through the real catalog service**.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.testing import routes as testing_routes
from utk_curio.backend.tests.dataset_catalog_coverage import catalog_datasets


def _post(client, body):
    return client.post(
        "/api/testing/dataset-paths",
        data=json.dumps(body),
        content_type="application/json",
    )


def _loader_code(*dataset_ids: str) -> str:
    """Node code shaped like the generated loaders the examples actually use."""
    return "\n".join(
        f'path_{i} = curio_dataset_path("{dataset_id}")'
        for i, dataset_id in enumerate(dataset_ids)
    )


class TestResolvesTheCommittedCatalog:
    def test_every_committed_dataset_resolves_to_a_real_file(self, client):
        """No install, no dataflow id — the path a seeded example takes.

        Parametrizing would hide the interesting case: the harness sends ONE
        request per node, and a loader may name several datasets, so they have
        to resolve together in a single pass.
        """
        datasets = catalog_datasets()
        assert datasets, "no committed datasets; this test would be vacuous"

        resp = _post(client, {"code": _loader_code(*(d.dataset_id for d in datasets))})
        assert resp.status_code == 200
        paths = resp.get_json()["paths"]

        assert set(paths) == {d.dataset_id for d in datasets}, (
            f"unresolved: {sorted({d.dataset_id for d in datasets} - set(paths))}"
        )
        for dataset in datasets:
            assert Path(paths[dataset.dataset_id]).samefile(dataset.data_file)

    def test_the_path_is_absolute_and_the_servers_own(self, client):
        """The whole point: the caller must not have to know where the files are.

        A relative path would resolve against whatever cwd the sandbox happens
        to have, and a path built by the caller would be in the caller's
        filesystem — which is exactly the bug this route exists to remove.
        """
        dataset = catalog_datasets()[0]
        paths = _post(client, {"code": _loader_code(dataset.dataset_id)}).get_json()[
            "paths"
        ]
        resolved = Path(paths[dataset.dataset_id])
        assert resolved.is_absolute()
        assert resolved.is_file()

    def test_code_without_a_call_costs_nothing(self, client):
        resp = _post(client, {"code": "return 1 + 1"})
        assert resp.status_code == 200
        assert resp.get_json()["paths"] == {}

    def test_an_unknown_id_is_omitted_rather_than_an_error(self, client):
        """Fail-open, matching production: the sandbox raises the per-id error.

        The harness turns the omission into a named assertion of its own, so
        nothing is swallowed — but this route must not 500 on a typo.
        """
        dataset = catalog_datasets()[0]
        resp = _post(
            client, {"code": _loader_code(dataset.dataset_id, "no.such.dataset")}
        )
        assert resp.status_code == 200
        assert set(resp.get_json()["paths"]) == {dataset.dataset_id}

    def test_an_id_carrying_its_major_does_not_resolve(self, client):
        """``curio_dataset_path`` takes the bare id; ``<id>@1`` is a miss.

        Same distinction ``test_example_dataset_palette`` pins for the service.
        Asserted here too because the harness's own error message tells authors
        about it, and that message is only right while this stays true.
        """
        dataset = catalog_datasets()[0]
        paths = _post(
            client, {"code": _loader_code(dataset.manifest.dir_name)}
        ).get_json()["paths"]
        assert paths == {}


class TestTheRouteIsGatedLikeItsSiblings:
    def test_refused_when_curio_testing_is_unset(self, client, monkeypatch):
        monkeypatch.setattr(testing_routes, "_is_testing", lambda: False)
        assert _post(client, {"code": "x"}).status_code == 404

    def test_refused_in_production(self, client, monkeypatch):
        monkeypatch.setattr(testing_routes, "_is_dev", lambda: False)
        assert _post(client, {"code": "x"}).status_code == 404

    @pytest.mark.parametrize("code", [5, None, ["x"], {"a": 1}])
    def test_code_must_be_a_string(self, client, code):
        resp = _post(client, {"code": code})
        if code is None:
            # Absent is legitimate and means "nothing to scan".
            assert resp.status_code == 200
        else:
            assert resp.status_code == 400
