"""Install and resolve multi-artifact node outputs (tuple / ``outputs`` kind)."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utk_curio.backend.app.datasets.install.installer import (
    InstallerError,
    computed_dataset_id,
    install_computed_file_for_node,
)  # install_computed_file_for_node used in install_node_output
from utk_curio.backend.app.datasets.domain.manifest import (
    DatasetManifest,
    ManifestError,
    load_dataset_manifest,
    write_manifest,
)
from utk_curio.backend.app.datasets.domain.constants import (
    FORMAT_TO_EXTENSION,
    SANDBOX_DATATYPE_TO_FORMAT,
)
from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
# Kinds whose ``value_str`` genuinely holds a path. For ``str`` it is the user's
# own return value, so treating it as one hard-links an unrelated file in as the
# node's dataset (#180). Imported rather than redeclared so this reader and
# ``output_paths._resolve_duckdb_artifact_path`` can never drift apart.
from utk_curio.backend.app.datasets.infrastructure.output_paths import PATH_BEARING_KINDS


@dataclass(frozen=True)
class BundlePart:
    index: int
    artifact_id: str
    kind: str
    format: str
    label: str
    source_path: Path | None


# Sandbox artifact kinds whose ENTIRE value lives in the DuckDB row: there is no
# file under ``artifacts/`` for any of them (see ``sandbox/util/parsers``'s
# ``save_to_duckdb``). int/float/bool keep it in value_int/value_float, ``str``
# keeps the *string value* (not a path) in value_str, and ``null`` carries no
# value column at all. Every one is a declared Python Computation output type
# (``VALUE`` in packages/curio.builtin@1/manifest.json), so "no file on disk"
# must NOT be reported as "output artifact not found at save time" (#180).
ROW_ONLY_KINDS = frozenset({"int", "float", "bool", "str", "null"})

# ``save_to_duckdb``'s fallbacks for a list/dict that CONTAINS DataFrames: each
# element is saved as its own artifact and only the id list/map is stored here
# (value_json). Also file-less, but the real data is the children's, so these
# install as a bundle rather than as a scalar JSON stub (#180).
ID_CONTAINER_KINDS = frozenset({"list_of_ids", "dict_of_ids"})

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
    from utk_curio.backend.app.datasets.infrastructure.output_paths import resolve_shared_output_path

    mapped = SANDBOX_DATATYPE_TO_FORMAT.get(kind)
    resolved = resolve_shared_output_path(art_id, data_type=kind if mapped else None)
    if resolved is not None and resolved.is_file():
        return resolved

    # Only consult ``value_str`` as a path for the kinds that store one there. A
    # ``str`` artifact holds the user's own return value, so ``return "cities.csv"``
    # would otherwise resolve to a real shared-data file and install it as this
    # part's data (#180). Kept in step with ``PATH_BEARING_KINDS``' other reader,
    # ``output_paths._resolve_duckdb_artifact_path``.
    if value_str and kind in PATH_BEARING_KINDS:
        from utk_curio.backend.app.projects.storage import _launch_dir
        from utk_curio.backend.app.datasets.infrastructure.output_paths import _shared_data_dir

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


def _bare_artifact_id(path_ref: str) -> str | None:
    """*path_ref* as a bare DuckDB artifact id, or ``None`` when it isn't one.

    Applies the same gate ``resolve_shared_output_path`` uses before it consults
    DuckDB: a single flat, extensionless segment. Reusing it means the row lookup
    can never be reached by a traversal ref (``../../etc/hosts``) or by a real
    shared-data filename, and the ``<id>.json`` store name it yields is always a
    valid single segment for ``_validate_store_filename``.
    """
    name = str(path_ref or "").strip()
    if not name or "/" in name or "\\" in name or "\x00" in name:
        return None
    return None if "." in name else name


def _artifact_value_row(art_id: str) -> tuple | None:
    """``(kind, value_int, value_float, value_str, value_json)`` for *art_id*, or
    ``None`` when the artifact has no row.

    ``None`` is load-bearing. It is the only signal the single-output install
    path has for "this artifact genuinely does not exist" - pruned, or the
    sandbox restarted and lost the DB - which is the case the save warning exists
    for and the only one where re-running the node helps. A DuckDB open failure
    (the sandbox holds the write handle mid-``/exec``) reports the same way:
    indistinguishable here, and equally "try again".
    """
    try:
        from utk_curio.sandbox.util.db import get_read_connection

        con = get_read_connection()
    except Exception:  # noqa: BLE001 - a locked/absent DB reads as "no artifact"
        return None
    try:
        return con.execute(
            "SELECT kind, value_int, value_float, value_str, value_json "
            "FROM artifacts WHERE id = ?",
            [art_id],
        ).fetchone()
    except Exception:  # noqa: BLE001
        return None
    finally:
        con.close()


def _row_value_bytes(kind: str, row: tuple) -> bytes:
    """JSON bytes for a row-only artifact: the ``{"value": <scalar>}`` envelope.

    Shared by the bundle part writer and the single-output installer so both
    materialize a scalar byte-identically - the same envelope the bundle loader
    already unwraps and the JSON preview renders as a one-row ``value`` column.
    """
    _kind, v_int, v_float, v_str, v_json = row
    if kind == "bool":
        # MUST precede int: value_int stores 0/1, and a bare read would emit
        # ``{"value": 0}`` for a node that returned ``False``.
        payload: Any = {"value": bool(v_int)}
    elif kind == "int":
        payload = {"value": v_int}
    elif kind == "float":
        payload = {"value": v_float}
    elif kind == "str":
        payload = {"value": v_str}
    else:
        # ``null`` (no value column) and any unexpected kind: value_json when the
        # row carries one, else the null-valued envelope.
        payload = json.loads(v_json) if v_json else {"value": v_str}
    return json.dumps(payload, indent=2, default=str).encode("utf-8")


def _serialize_scalar_part(dest: Path, kind: str, art_id: str) -> None:
    row = _artifact_value_row(art_id)
    if row is None:
        dest.write_text(json.dumps({"artifactId": art_id, "kind": kind}), encoding="utf-8")
        return
    dest.write_bytes(_row_value_bytes(kind, row))


def resolve_output_bundle_parts(parent_art_id: str) -> list[BundlePart]:
    """Load child artifacts for a multi-part parent id.

    Covers ``outputs`` (a tuple) and the two ``save_to_duckdb`` fallbacks for a
    list/dict that CONTAINS DataFrames: ``list_of_ids`` stores the identical
    ``[child_id, ...]`` shape, and ``dict_of_ids`` stores ``{key: child_id}``.
    All three are multi-part outputs, so all three install as a bundle rather
    than as a scalar JSON stub of opaque artifact ids (#180).
    """
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

    if not row or row[0] not in ("outputs", *ID_CONTAINER_KINDS) or not row[1]:
        return []

    raw_children = row[1]
    if isinstance(raw_children, (list, dict)):
        decoded = raw_children
    elif isinstance(raw_children, str) and raw_children:
        try:
            decoded = json.loads(raw_children)
        except (json.JSONDecodeError, TypeError):
            return []
    else:
        return []

    # Keep a ``dict_of_ids``' keys as part labels so a dict of DataFrames
    # installs with the names the user gave it, rather than "Table - part 1".
    if isinstance(decoded, dict):
        named_children = [(str(key), value) for key, value in decoded.items()]
    elif isinstance(decoded, list):
        named_children = [(None, child) for child in decoded]
    else:
        return []

    parts: list[BundlePart] = []
    try:
        con = get_read_connection()
        try:
            for index, (child_name, child_id) in enumerate(named_children):
                if not child_id:
                    continue
                child = con.execute(
                    "SELECT kind, value_str FROM artifacts WHERE id = ?",
                    [str(child_id)],
                ).fetchone()
                if not child:
                    continue
                kind = child[0] or "unknown"
                fmt = SANDBOX_DATATYPE_TO_FORMAT.get(kind, "json")
                src = _resolve_artifact_source(str(child_id), kind, child[1])
                parts.append(
                    BundlePart(
                        index=index,
                        artifact_id=str(child_id),
                        kind=kind,
                        format=fmt,
                        label=child_name or _part_label(index, kind),
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
    dataflow_id: str | None = None,
    node_type: str | None = None,
    dataflow_name: str | None = None,
    upstream_inputs: list[dict] | None = None,
    title: str | None = None,
) -> Any:
    """Materialize a tuple output as ``format: bundle`` in the user dataset store.

    A *dataflow_id* is required — see ``install_computed_file_for_node`` (#166).
    """
    from utk_curio.backend.app.datasets.install.installer import InstallResult

    if not dataflow_id:
        raise InstallerError(
            "Computed dataset install requires a dataflow id; "
            "refusing to mint a legacy un-namespaced dataset dir."
        )
    if not parts:
        raise InstallerError("Bundle has no resolvable parts")

    dataset_id = computed_dataset_id(node_id, dataflow_id)
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
        suffix = FORMAT_TO_EXTENSION.get(part.format, ".json")
        safe_kind = part.kind.replace("_", "-")[:24] or "part"
        filename = f"{part.index:02d}_{safe_kind}{suffix}"
        dest_file = parts_dir / filename

        if part.source_path is not None and part.source_path.is_file():
            if part.source_path.name.endswith(".json.zlib"):
                # list/dict artifacts are stored zlib-compressed, but the bundle
                # part is declared as plain .json — decompress into the part file
                # so preview/loader json.load gets real JSON, not compressed bytes.
                import zlib

                dest_file.write_bytes(zlib.decompress(part.source_path.read_bytes()))
            else:
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
        producer_node_id=node_id,
        producer_node_type=node_type,
        producer_dataflow_id=dataflow_id,
        producer_dataflow_name=dataflow_name,
        upstream_inputs=list(upstream_inputs) if upstream_inputs else None,
    )
    write_manifest(manifest_obj, dest)
    try:
        manifest = load_dataset_manifest(dest)
    except ManifestError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise InstallerError(f"Failed to create bundle manifest: {exc}") from exc

    from utk_curio.backend.app.datasets.install.installer import _index

    return _index(user_key, InstallResult(manifest=manifest, dest=dest, replaced=True))


def install_node_output(
    user_key: str,
    *,
    node_id: str,
    path_ref: str,
    data_type: str | None,
    node_name: str | None = None,
    dataflow_id: str | None = None,
    node_type: str | None = None,
    dataflow_name: str | None = None,
    upstream_inputs: list[dict] | None = None,
) -> Any:
    """Install a single file or multi-part ``outputs`` bundle from shared storage.

    *node_name* (the producing node's canvas display name) becomes the dataset
    title when provided; otherwise the installer derives a title from the
    generated filename. *dataflow_id* namespaces the dataset id and, with the
    other lineage arguments, is persisted on the manifest.
    """
    from utk_curio.backend.app.datasets.infrastructure.output_paths import resolve_shared_output_path
    from utk_curio.backend.app.datasets.domain.provenance import computed_output_format

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
            dataflow_id=dataflow_id,
            node_type=node_type,
            dataflow_name=dataflow_name,
            upstream_inputs=upstream_inputs,
            title=node_name,
        )

    src = resolve_shared_output_path(path_ref, data_type=data_type)

    file_bytes: bytes | None = None
    source_path: Path | None = None

    if src is None:
        # No artifact FILE is not the same as no artifact. Only (geo)dataframe,
        # raster and JSON-native dict/list outputs write one; int/float/bool/str/
        # null keep their whole value in the DuckDB row, and list_of_ids/
        # dict_of_ids keep a child-id list there. Reporting those as "output
        # artifact not found at save time" is the spurious
        # ``Dataset for "Python Computation" couldn't be generated`` toast of
        # #180 - re-running never helps, because nothing is missing.
        # ``install_computed_bundle_for_node`` has always materialized exactly
        # these kinds correctly; this restores the same symmetry for a single
        # output. Dispatch on the ROW's kind, never on *data_type*: the sandbox
        # reports ``list``/``dict`` for the ``*_of_ids`` fallbacks (detect_kind
        # has no such kinds) and *data_type* is client-supplied anyway.
        art_id = _bare_artifact_id(path_ref)
        row = _artifact_value_row(art_id) if art_id else None
        if row is None:
            # No row at all: the artifact really is gone (pruned, sandbox
            # restarted, or the ref was never an artifact id). Keep returning
            # None so the save warning fires - here re-running DOES help.
            return None
        kind = str(row[0] or "").strip().lower()
        if kind in ID_CONTAINER_KINDS:
            parts = resolve_output_bundle_parts(art_id)
            if not parts:
                return None  # children pruned - a genuine failure
            return install_computed_bundle_for_node(
                user_key,
                parts,
                node_id=node_id,
                parent_artifact_id=art_id,
                dataflow_id=dataflow_id,
                node_type=node_type,
                dataflow_name=dataflow_name,
                upstream_inputs=upstream_inputs,
                title=node_name,
            )
        if kind not in ROW_ONLY_KINDS:
            # A row declaring a FILE-backed kind (dataframe, geodataframe,
            # raster, dict, list) whose file is missing is a genuine failure,
            # identical to no row. Only file-less kinds are synthesized here.
            return None
        file_bytes = _row_value_bytes(kind, row)
        store_name = f"{art_id}.json"
        fmt = "json"
    elif src.name.endswith(".json.zlib"):
        # dict/list artifacts are written zlib-compressed. Hard-linking those
        # bytes under a ``format: json`` manifest produced a dataset whose data
        # file is compressed garbage to every plain-JSON consumer (Export, and
        # the generated ``json.load`` loader snippet). Decompress once, here -
        # exactly what install_computed_bundle_for_node already does per part.
        import zlib

        file_bytes = zlib.decompress(src.read_bytes())
        store_name = f"{src.name[: -len('.json.zlib')]}.json"
        fmt = "json"
    else:
        # Hard-link the shared artifact into the dataset store instead of reading
        # it into memory and re-writing it on the synchronous
        # /processPythonCode path.
        source_path = src
        fmt = computed_output_format(src.name, data_type)
        store_name = src.name if src.suffix else path_ref

    return install_computed_file_for_node(
        user_key,
        file_bytes,
        store_name,
        fmt,
        node_id=node_id,
        dataflow_id=dataflow_id,
        node_type=node_type,
        dataflow_name=dataflow_name,
        upstream_inputs=upstream_inputs,
        title=node_name,
        source_path=source_path,
    )
