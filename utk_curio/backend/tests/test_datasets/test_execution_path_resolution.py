"""Execution-time dataset path resolution for ``curio_dataset_path("<id>")``.

Generated Data Loading nodes reference datasets by id; ``/processPythonCode``
scans the code for literal id calls, resolves them through the catalog service
(auth-scoped, containment-guarded), and forwards a ``dataset_paths`` mapping to
the sandbox. Resolution is best-effort and fail-open: it must never block an
execution.
"""
from __future__ import annotations

import io
import json
from unittest.mock import MagicMock

from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers


def _import_csv(client, token, filename="cities.csv", content=b"a,b\n1,2\n"):
    resp = client.post(
        "/api/datasets/import",
        headers={"Authorization": f"Bearer {token}"},
        data={"file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


def _capture_sandbox(monkeypatch):
    """Mock the backend→sandbox bridge, capturing the forwarded /exec body."""
    captured = {}
    resp = MagicMock()
    resp.json.return_value = {"stdout": "", "stderr": "", "output": {}}

    def fake_call(method, path, **kwargs):
        captured["body"] = json.loads(kwargs["data"])
        return resp

    monkeypatch.setattr("utk_curio.backend.app.api.routes._sandbox_call", fake_call)
    return captured


def _exec_code(client, token, code):
    return client.post(
        "/processPythonCode",
        data=json.dumps({
            "code": code,
            "nodeType": "PYTHON_COMPUTATION",
            "input": {"path": "", "dataType": "str"},
            "saveOutputDataset": False,
        }),
        headers=auth_headers(token),
    )


def test_execution_forwards_resolved_dataset_paths(
    client, user_and_token, tmp_path, monkeypatch
):
    """Ids referenced by the code arrive at the sandbox resolved to real paths;
    unknown ids are omitted (the sandbox raises the per-id error for those)."""
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    imported = _import_csv(client, token)
    captured = _capture_sandbox(monkeypatch)

    code = (
        f'    df = pd.read_csv(curio_dataset_path("{imported["id"]}"))\n'
        '    other = curio_dataset_path("imported.xdoesnotexist")\n'
        "    return df\n"
    )
    resp = _exec_code(client, token, code)
    assert resp.status_code == 200, resp.get_data(as_text=True)

    dataset_paths = captured["body"]["dataset_paths"]
    assert set(dataset_paths) == {imported["id"]}
    assert dataset_paths[imported["id"]].endswith("cities.csv")


def test_execution_without_id_calls_forwards_empty_mapping(
    client, user_and_token, monkeypatch
):
    _, token = user_and_token
    captured = _capture_sandbox(monkeypatch)

    resp = _exec_code(client, token, "    return 1\n")
    assert resp.status_code == 200
    assert captured["body"]["dataset_paths"] == {}


def test_single_quoted_id_call_is_scanned(client, user_and_token, tmp_path, monkeypatch):
    """Users edit generated code; single-quoted id literals must resolve too."""
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    imported = _import_csv(client, token)
    captured = _capture_sandbox(monkeypatch)

    resp = _exec_code(
        client, token, f"    p = curio_dataset_path('{imported['id']}')\n    return p\n"
    )
    assert resp.status_code == 200
    assert imported["id"] in captured["body"]["dataset_paths"]


def test_scan_caps_distinct_ids(client, user_and_token, monkeypatch):
    """Pathological code cannot trigger unbounded resolution work."""
    from utk_curio.backend.app.api.routes import MAX_EXEC_DATASET_IDS

    _, token = user_and_token
    _capture_sandbox(monkeypatch)

    seen_ids = {}

    class StubService:
        def __init__(self, user):
            pass

        def resolve_execution_paths(self, ids, *, dataflow_id=None):
            seen_ids["ids"] = list(ids)
            return {}

    monkeypatch.setattr(
        "utk_curio.backend.app.datasets.service.DatasetCatalogService", StubService
    )

    lines = [
        f'    p{i} = curio_dataset_path("imported.xid{i:04d}")'
        for i in range(MAX_EXEC_DATASET_IDS + 8)
    ]
    resp = _exec_code(client, token, "\n".join(lines) + "\n    return 1\n")
    assert resp.status_code == 200
    assert len(seen_ids["ids"]) == MAX_EXEC_DATASET_IDS


def test_resolution_failure_is_fail_open(client, user_and_token, monkeypatch):
    """A catalog error must not fail the execution — the code still runs with an
    empty mapping and the sandbox reports the missing dataset per id."""
    _, token = user_and_token
    captured = _capture_sandbox(monkeypatch)

    class ExplodingService:
        def __init__(self, user):
            raise RuntimeError("catalog on fire")

    monkeypatch.setattr(
        "utk_curio.backend.app.datasets.service.DatasetCatalogService", ExplodingService
    )

    resp = _exec_code(
        client, token, '    return curio_dataset_path("imported.xabc")\n'
    )
    assert resp.status_code == 200
    assert captured["body"]["dataset_paths"] == {}


def test_resolve_execution_paths_service(app, client, user_and_token, tmp_path, monkeypatch):
    """Service-level contract: resolvable ids map to on-disk files, unknown ids
    are omitted, and an empty request costs nothing."""
    user, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    imported = _import_csv(client, token, filename="blocks.csv")

    from pathlib import Path

    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    with app.app_context():
        service = DatasetCatalogService(user)
        resolved = service.resolve_execution_paths(
            [imported["id"], "imported.xmissing"]
        )
        assert set(resolved) == {imported["id"]}
        assert Path(resolved[imported["id"]]).is_file()
        assert service.resolve_execution_paths([]) == {}
