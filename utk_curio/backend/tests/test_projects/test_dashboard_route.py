"""The endpoint that hands a dashboard everything it needs in one response.

Unauthenticated on purpose, like ``/shared``: a dashboard is opened by whoever
holds the link, and this serves what that page would otherwise have fetched a
piece at a time.

The case worth protecting is the refusal. A dashboard whose rows will not fit in
a page must fail loudly and say which tiles are heavy, because the tempting
alternative, embedding what fits and fetching the rest, produces a page that
looks standalone and is not. Nobody finds out until it is opened somewhere the
server cannot be reached, which is the one situation the whole feature exists
for.
"""
import json

import pytest

from utk_curio.backend.app.projects import services


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _spec_with_pinned_chart():
    return {
        "dataflow": {
            "name": "dash-route-test",
            "task": "",
            "timestamp": 1748990000000,
            "provenance_id": "dash-route-test",
            "nodes": [
                {
                    "id": "py",
                    "type": "__curioUniversalNode",
                    "x": 0,
                    "y": 0,
                    "data": {"nodeType": "curio.builtin/computation-analysis"},
                },
                {
                    "id": "chart",
                    "type": "__curioUniversalNode",
                    "x": 300,
                    "y": 0,
                    "dashboardPinned": True,
                    "data": {
                        "nodeType": "curio.builtin/vis-vega",
                        "dashboardPinned": True,
                    },
                },
            ],
            "edges": [{"id": "py-chart", "source": "py", "target": "chart"}],
        }
    }


def _create(client, token, spec=None, outputs=None):
    resp = client.post(
        "/api/projects",
        data=json.dumps(
            {
                "name": "Dashboard",
                "spec": spec or _spec_with_pinned_chart(),
                "outputs": outputs or [],
            }
        ),
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def test_a_missing_project_is_a_404(client, tmp_curio):
    resp = client.get("/api/projects/00000000-0000-0000-0000-000000000000/dashboard")
    assert resp.status_code == 404


def test_it_serves_the_spec_without_a_token(client, user_and_token, tmp_curio):
    _, token = user_and_token
    pid = _create(client, token)

    resp = client.get(f"/api/projects/{pid}/dashboard")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["spec"]["dataflow"]["name"] == "dash-route-test"
    assert body["meta"]["projectId"] == pid
    assert "outputs" in body


def test_the_payload_carries_no_rows_when_nothing_was_saved(client, user_and_token, tmp_curio):
    _, token = user_and_token
    pid = _create(client, token)

    body = client.get(f"/api/projects/{pid}/dashboard").get_json()

    # No manifest outputs, so nothing to embed. The page still builds: the tile
    # shows its own empty state rather than the whole dashboard failing.
    assert body["outputs"] == {}


def test_a_dashboard_too_large_to_embed_is_refused(
    client, user_and_token, tmp_curio, monkeypatch
):
    _, token = user_and_token
    pid = _create(client, token)

    # Shrink the budget rather than manufacture 25 MB of rows: the refusal is
    # what is under test, not the size of the number.
    from utk_curio.backend.app.projects import dashboard_payload

    monkeypatch.setattr(dashboard_payload, "DEFAULT_PAYLOAD_LIMIT_BYTES", 512)

    def fat_reader():
        def read(filename):
            return {"dataType": "dataframe", "data": {"a": list(range(500))}, "schema": {}}

        return read

    monkeypatch.setattr(services, "_dashboard_envelope_reader", fat_reader)
    monkeypatch.setattr(
        services,
        "load_shared_project",
        lambda project_id: {
            "project": type("D", (), {"name": "Dashboard"})(),
            "spec": _spec_with_pinned_chart(),
            "outputs": [
                {"node_id": "py", "filename": "py.parquet", "data_type": "dataframe"}
            ],
        },
    )

    resp = client.get(f"/api/projects/{pid}/dashboard")

    assert resp.status_code == 413
    body = resp.get_json()
    # The owner has to know which node to aggregate, not just that it was big.
    assert "py" in body["error"]
    assert body["heaviest"][0]["nodeId"] == "py"
    assert body["totalBytes"] > body["limitBytes"]


def test_only_what_a_tile_reads_is_embedded(client, user_and_token, tmp_curio, monkeypatch):
    _, token = user_and_token
    pid = _create(client, token)

    def reader():
        return lambda filename: {"dataType": "dataframe", "data": {"a": [1]}, "schema": {}}

    monkeypatch.setattr(services, "_dashboard_envelope_reader", reader)
    monkeypatch.setattr(
        services,
        "load_shared_project",
        lambda project_id: {
            "project": type("D", (), {"name": "Dashboard"})(),
            "spec": _spec_with_pinned_chart(),
            "outputs": [
                {"node_id": "py", "filename": "py.parquet", "data_type": "dataframe"},
                # Saved because the account runs with save-every-output on. No
                # pinned tile descends from it, so it must not ride along in a
                # page that gets handed out by link.
                {"node_id": "secret", "filename": "secret.parquet", "data_type": "dataframe"},
            ],
        },
    )

    body = client.get(f"/api/projects/{pid}/dashboard").get_json()

    assert set(body["outputs"]) == {"py.parquet"}
