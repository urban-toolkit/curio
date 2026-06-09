"""Install and resolve multi-artifact node outputs (tuple / ``outputs`` kind)."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utk_curio.backend.app.datasets.installer import (
    InstallerError,
    _sanitize_node_id_segment,
    install_computed_file_for_node,
)  # install_computed_file_for_node used in install_node_output
from utk_curio.backend.app.datasets.manifest import (
    DatasetManifest,
    ManifestError,
    load_dataset_manifest,
    write_manifest,
)
from utk_curio.backend.app.datasets.storage import dataset_dir

KIND_TO_FORMAT: dict[str, str] = {
    "raster": "geotiff",
    "geodataframe": "parquet",
    "dataframe": "parquet",
    "dict": "json",
    "list": "json",
    "str": "json",
    "int": "json",
    "float": "json",
    "bool": "json",
    "null": "json",
    "unknown": "json",
}


@dataclass(frozen=True)
class BundlePart:
    index: int
    artifact_id: str
    kind: str
    format: str
    label: str
    source_path: Path | None


def _part_label(index: int, kind: str) -> str:
    names = {
        "raster": "Raster",
        "dataframe": "Table",
        "geodataframe": "Geo table",
        "list": "Array",
        "dict": "Object",
        "str": "Text",
        "int": "Number",
        "float": "Number",
        "bool": "Flag",
        "null": "Empty",
    }
    base = names.get(kind, kind.replace("_", " ").title())
    return f"{base} · part {index + 1}"


def _resolve_artifact_source(art_id: str, kind: str, value_str: str | None) -> Path | None:
    from utk_curio.backend.app.datasets.output_paths import resolve_shared_output_path

    mapped = KIND_TO_FORMAT.get(kind)
    resolved = resolve_shared_output_path(art_id, data_type=kind if mapped else None)
    if resolved is not None and resolved.is_file():
        return resolved

    if value_str:
        from utk_curio.backend.app.projects.storage import _launch_dir
        from utk_curio.backend.app.datasets.output_paths import _shared_data_dir

        shared = _shared_data_dir()
        for candidate in (
            Path(value_str),
            shared / value_str,
            _launch_dir() / value_str,
            shared / "artifacts" / f"{art_id}.parquet",
            shared / "artifacts" / f"{art_id}.json",
            shared / "artifacts" / f"{art_id}.json.zlib",
        ):
            try:
                path = candidate.resolve()
            except OSError:
                continue
            if path.is_file():
                return path
    return None


def _serialize_scalar_part(dest: Path, kind: str, art_id: str) -> None:
    from utk_curio.sandbox.util.db import get_read_connection

    con = get_read_connection()
    try:
        row = con.execute(
            "SELECT value_int, value_float, value_str, value_json FROM artifacts WHERE id = ?",
            [art_id],
        ).fetchone()
    finally:
        con.close()
    if not row:
        dest.write_text(json.dumps({"artifactId": art_id, "kind": kind}), encoding="utf-8")
        return
    v_int, v_float, v_str, v_json = row
    if kind == "bool":
        payload = {"value": bool(v_int)}
    elif kind == "int":
        payload = {"value": v_int}
    elif kind == "float":
        payload = {"value": v_float}
    elif kind == "str":
        payload = {"value": v_str}
    else:
        payload = json.loads(v_json) if v_json else {"value": v_str}
    dest.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def resolve_output_bundle_parts(parent_art_id: str) -> list[BundlePart]:
    """Load child artifacts for an ``outputs`` (tuple) parent id."""
    from utk_curio.sandbox.util.db import get_read_connection

    try:
        con = get_read_connection()
        try:
            row = con.execute(
                "SELECT kind, value_json FROM artifacts WHERE id = ?",
                [parent_art_id],
            ).fetchone()
        finally:
            con.close()
    except Exception:
        return []

    if not row or row[0] != "outputs" or not row[1]:
        return []

    raw_children = row[1]
    if isinstance(raw_children, list):
        child_ids = raw_children
    elif isinstance(raw_children, str) and raw_children:
        try:
            child_ids = json.loads(raw_children)
        except (json.JSONDecodeError, TypeError):
            return []
    else:
        return []
    if not isinstance(child_ids, list):
        return []

    parts: list[BundlePart] = []
    try:
        con = get_read_connection()
        try:
            for index, child_id in enumerate(child_ids):
                if not child_id:
                    continue
                child = con.execute(
                    "SELECT kind, value_str FROM artifacts WHERE id = ?",
                    [str(child_id)],
                ).fetchone()
                if not child:
                    continue
                kind = child[0] or "unknown"
                fmt = KIND_TO_FORMAT.get(kind, "json")
                src = _resolve_artifact_source(str(child_id), kind, child[1])
                parts.append(
                    BundlePart(
                        index=index,
                        artifact_id=str(child_id),
                        kind=kind,
                        format=fmt,
                        label=_part_label(index, kind),
                        source_path=src,
                    )
                )
        finally:
            con.close()
    except Exception:
        return parts
    return parts


def install_computed_bundle_for_node(
    user_key: str,
    parts: list[BundlePart],
    *,
    node_id: str,
    parent_artifact_id: str,
    title: str | None = None,
) -> Any:
    """Materialize a tuple output as ``format: bundle`` in the user dataset store."""
    from utk_curio.backend.app.datasets.installer import InstallResult

    if not parts:
        raise InstallerError("Bundle has no resolvable parts")

    seg = _sanitize_node_id_segment(node_id)
    dataset_id = f"computed.{seg}"
    dir_name = f"{dataset_id}@1"
    dest = dataset_dir(user_key, dir_name)

    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    parts_dir = dest / "data" / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    bundle_spec: dict[str, Any] = {
        "version": 1,
        "parentArtifactId": parent_artifact_id,
        "parts": [],
    }

    for part in parts:
        suffix = {
            "parquet": ".parquet",
            "geotiff": ".tif",
            "csv": ".csv",
            "geojson": ".geojson",
            "json": ".json",
            "shp": ".shp",
        }.get(part.format, ".json")
        safe_kind = part.kind.replace("_", "-")[:24] or "part"
        filename = f"{part.index:02d}_{safe_kind}{suffix}"
        dest_file = parts_dir / filename

        if part.source_path is not None and part.source_path.is_file():
            shutil.copy2(part.source_path, dest_file)
        elif part.kind in {"int", "float", "bool", "str", "null"}:
            _serialize_scalar_part(dest_file, part.kind, part.artifact_id)
        else:
            # Best-effort: write placeholder pointing at artifact id.
            dest_file.write_text(
                json.dumps(
                    {
                        "artifactId": part.artifact_id,
                        "kind": part.kind,
                        "note": "Source file was not available at install time.",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

        rel_file = f"data/parts/{filename}"
        bundle_spec["parts"].append({
            "index": part.index,
            "label": part.label,
            "kind": part.kind,
            "format": part.format,
            "artifactId": part.artifact_id,
            "file": rel_file,
        })

    bundle_path = dest / "data" / "bundle.json"
    bundle_path.write_text(json.dumps(bundle_spec, indent=2), encoding="utf-8")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    part_count = len(bundle_spec["parts"])
    display_title = title or f"Node output ({part_count} parts)"
    manifest_obj = DatasetManifest(
        id=dataset_id,
        name=display_title,
        version="1.0.0",
        format="bundle",
        description=f"Multi-part computed output ({part_count} items).",
        publisher="User",
        license="",
        tags=["bundle", "computed"],
        data_file="data/bundle.json",
        major=1,
        source_label="Computed",
        created_at=now,
        updated_at=now,
        row_count=None,
        feature_count=None,
        schema={
            "fields": [
                {
                    "name": "parts",
                    "type": "integer",
                    "nullable": False,
                    "sample": part_count,
                },
            ],
            "bundleParts": [
                {"label": p["label"], "format": p["format"], "kind": p["kind"]}
                for p in bundle_spec["parts"]
            ],
        },
    )
    write_manifest(manifest_obj, dest)
    try:
        manifest = load_dataset_manifest(dest)
    except ManifestError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise InstallerError(f"Failed to create bundle manifest: {exc}") from exc

    return InstallResult(manifest=manifest, dest=dest, replaced=True)


def install_node_output(
    user_key: str,
    *,
    node_id: str,
    path_ref: str,
    data_type: str | None,
) -> Any:
    """Install a single file or multi-part ``outputs`` bundle from shared storage."""
    from utk_curio.backend.app.datasets.output_paths import resolve_shared_output_path
    from utk_curio.backend.app.datasets.provenance import computed_output_format

    dtype = (data_type or "").strip().lower()
    if dtype == "outputs":
        parts = resolve_output_bundle_parts(path_ref)
        if not parts:
            return None
        return install_computed_bundle_for_node(
            user_key,
            parts,
            node_id=node_id,
            parent_artifact_id=path_ref,
        )

    src = resolve_shared_output_path(path_ref, data_type=data_type)
    if src is None:
        return None
    fmt = computed_output_format(src.name, data_type)
    store_name = src.name if src.suffix else path_ref
    return install_computed_file_for_node(
        user_key,
        src.read_bytes(),
        store_name,
        fmt,
        node_id=node_id,
    )
