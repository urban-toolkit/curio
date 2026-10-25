"""Shared helpers for computed dataset tests."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def bundle_parts_size(bundle: Path) -> int:
    """The bytes of the files the ``bundle.json`` at *bundle* lists, read from
    the files themselves. Each part's ``file`` is relative to the dataset's
    folder, two levels above ``bundle.json``. A bundle that lists no part, or a
    part that is not there, fails the test that asked."""
    bundle = Path(bundle)
    folder = bundle.parent.parent
    spec = json.loads(bundle.read_text(encoding="utf-8"))
    files = [folder / part["file"] for part in spec["parts"]]
    assert files, f"{bundle} lists no parts"
    missing = [str(file) for file in files if not file.is_file()]
    assert not missing, f"{bundle} lists parts that are not there: {missing}"
    return sum(file.stat().st_size for file in files)


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


def store_sandbox_artifact_at(value, ms: int, node_id: str = "test-node") -> str:
    """:func:`store_sandbox_artifact`, with the id stamped *ms*.

    The store's id begins with the sandbox's clock in milliseconds
    (``<ms>_<8 hex>``, ``parsers._make_id``), and a dataflow orders a node's
    outputs by it (``projects/services._produced_at``). The writer is the real
    one; only the clock its id reads is fixed, so a test can say which output
    is the older one and what time it was made.
    """
    import uuid
    from unittest import mock

    from utk_curio.sandbox.util import parsers

    with mock.patch.object(parsers, "_make_id", lambda: f"{ms}_{uuid.uuid4().hex[:8]}"):
        return store_sandbox_artifact(value, node_id=node_id)


def stored_artifact_file(art_id: str) -> Path:
    """The file the store wrote for the artifact *art_id*, where the writer
    puts it: ``artifacts/<id>.parquet`` for a table, ``artifacts/<id>.json.zlib``
    for a JSON value. Fails the test unless there is exactly one."""
    from utk_curio.sandbox.util import parsers

    shared = parsers._shared_data_dir()
    files = [
        shared / rel
        for rel in (parsers._stored_artifact_rel_path(art_id), parsers._json_artifact_rel_path(art_id))
        if (shared / rel).is_file()
    ]
    assert len(files) == 1, f"the store holds {files} for the artifact {art_id}"
    return files[0]
