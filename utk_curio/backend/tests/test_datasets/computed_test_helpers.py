"""Shared helpers for computed dataset tests."""
from __future__ import annotations

import json
from datetime import datetime, timezone


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def write_legacy_computed_dir(
    user_key: str,
    node_id: str,
    *,
    file_bytes: bytes = b'{"v": 1}',
    filename: str = "out.json",
    fmt: str = "json",
    major: int = 1,
) -> str:
    """Fabricate a pre-namespacing ``computed.<node>@<major>`` store dir.

    The installer now refuses to mint the legacy un-namespaced form, so tests
    that need one (migration, stale-dir handling) must write it by hand. Returns
    the legacy dataset id.
    """
    from utk_curio.backend.app.datasets.domain.manifest import (
        DatasetManifest,
        write_manifest,
    )
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
    from utk_curio.backend.app.datasets.install.installer import (
        sanitize_node_id_segment,
    )

    dataset_id = f"computed.{sanitize_node_id_segment(node_id)}"
    dest = dataset_dir(user_key, f"{dataset_id}@{major}")
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "data").mkdir(exist_ok=True)
    (dest / "data" / filename).write_bytes(file_bytes)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_manifest(
        DatasetManifest(
            id=dataset_id,
            name=filename,
            version="1.0.0",
            format=fmt,
            description=f"{fmt.upper()} dataset computed by a dataflow node.",
            publisher="User",
            license="",
            tags=[fmt, "computed"],
            data_file=f"data/{filename}",
            major=major,
            source_label="Computed",
            created_at=now,
            updated_at=now,
            producer_node_id=node_id,
        ),
        dest,
    )
    return dataset_id


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


def store_sandbox_artifact(value, node_id: str = "test-node") -> str:
    """Persist *value* through the REAL sandbox writer; return its artifact id.

    Uses ``save_to_duckdb`` rather than a hand-written INSERT so the row/file
    layout under test can never drift from what node execution actually writes -
    that drift between writer and resolver IS #180. Requires the ``app`` fixture,
    which wires ``CURIO_SHARED_DATA`` / ``CURIO_LAUNCH_CWD``.
    """
    from utk_curio.sandbox.util.parsers import save_to_duckdb

    return save_to_duckdb(value, node_id=node_id)
