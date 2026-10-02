"""Where the files of each collection a node's code reads are, for one execution.

Shared by ``/processPythonCode`` and the agent runtime's runs through a node
(``execution/runner.run_through_node``), so a node that calls
``curio_collection("<id>")`` reads the same files on Play, on a node run and
under Solve's validation.
"""
from __future__ import annotations

from utk_curio.backend.app.datasets.domain.code_refs import (
    MAX_DATASET_IDS,
    collection_ids_in_code,
)


def resolve_exec_collections(code: str, user_key: str | None, *, user=None) -> tuple[dict, str | None]:
    """Where the files of each collection *code* reads are, for this execution.

    Returns ``({datasetId: {root, objects, kind}}, media_dir)``. A folder
    collection's files are read in place under ``root``; a bucket collection's
    cached copies sit in ``objects``. ``media_dir`` is where a node may write
    the frames or clips it derives. *user* is the account's ``User`` row, which
    the Data Catalog needs to find the collection. Fail-open like dataset
    paths: the injected ``curio_collection`` raises a clear error for anything
    missing.
    """
    if not user_key:
        return {}, None
    try:
        from utk_curio.backend.app.discovery.application import cache_collection
        from utk_curio.backend.app.discovery.infrastructure import media_dirs, storage
        from utk_curio.backend.app.discovery.service import DiscoveryService

        # Every node gets the directory, not only one that loads a collection:
        # a node downstream of a Data Loading node writes the frames or the
        # mosaic, and never names the collection itself.
        media_dir = str(media_dirs.media_work_root(user_key))
        ids = collection_ids_in_code(code, limit=MAX_DATASET_IDS)
        if not ids:
            return {}, media_dir

        service = DiscoveryService(user_key, user=user)
        out = {}
        for dataset_id in ids:
            try:
                item, manifest = service.collection(dataset_id)
            except Exception:  # noqa: BLE001 - one missing collection is its node's error
                continue
            entry = {"kind": (item.get("collection") or {}).get("kind")}
            if manifest.provider.type == "folder":
                entry["root"] = str(storage.storage_root(manifest))
            else:
                entry["objects"] = str(cache_collection.objects_dir(user_key, dataset_id))
            out[dataset_id] = entry
        return out, media_dir
    except Exception as e:  # noqa: BLE001 - resolution must never fail the execution
        print(f"[exec] collection resolution failed: {e}", flush=True)
        return {}, None


def resolve_spec_collections(spec_dict: dict | None, user_key: str | None, *extra: str | None) -> tuple[dict, str | None]:
    """:func:`resolve_exec_collections` for every node's code in *spec_dict*
    plus *extra* (a candidate not yet in the spec), with the request's user
    when there is one."""
    codes = [str(n.get("content") or "") for n in ((spec_dict or {}).get("dataflow") or {}).get("nodes") or [] if isinstance(n, dict)]
    codes.extend(str(c or "") for c in extra)
    try:
        from flask import g, has_request_context

        user = getattr(g, "user", None) if has_request_context() else None
    except Exception:  # noqa: BLE001 - no Flask, no user
        user = None
    return resolve_exec_collections("\n".join(codes), user_key, user=user)
