"""Shared helpers for computed dataset tests."""
from __future__ import annotations

import json


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def create_project(client, token, name="Computed test project"):
    resp = client.post(
        "/api/projects",
        data=json.dumps({
            "name": name,
            "spec": {"dataflow": {"name": name, "nodes": [], "edges": []}},
            "outputs": [],
        }),
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def save_project_with_output(client, token, project_id, output_filename, node_id="node-1"):
    """Update a project so it records an output ref in its manifest."""
    resp = client.put(
        f"/api/projects/{project_id}",
        data=json.dumps({
            "outputs": [{"node_id": node_id, "filename": output_filename}],
        }),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()
