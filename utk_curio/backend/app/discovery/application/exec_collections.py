"""Where the files of each collection a node's code reads are, for one execution.

Shared by ``/processPythonCode`` and the agent runtime's runs through a node
(``execution/runner.run_through_node``), so a node that calls
``curio_load_collection("<id>")`` reads the same files on Play, on a node run and
under Solve's validation.
"""
from __future__ import annotations

from utk_curio.backend.app.datasets.domain.code_refs import (
    MAX_DATASET_IDS,
    collection_ids_in_code,
)


def resolve_exec_collections(
    code: str, user_key: str | None, *, user=None, dataflow_id: str | None = None,
) -> tuple[dict, str | None]:
    """Where the files of each collection *code* reads are, for this execution.

    Returns ``({datasetId: {root, objects, kind}}, media_dir)``. A folder
    collection's files are read in place under ``root``, and so are those of
    a bucket this deployment mounts (with ``tail``, or ``unavailable`` while
    its mount is down: :func:`resolve_collections`); another bucket
    collection's cached copies sit in ``objects``. ``media_dir`` is where a node may write
    the frames or clips it derives. *user* is the account's ``User`` row, which
    the Data Catalog needs to find the collection. Fail-open like dataset
    paths: the injected ``curio_load_collection`` raises a clear error for anything
    missing.

    *dataflow_id* is the dataflow the run is of. Its owner and an editor the
    owner invited read the collections it lists, from the owner's store, as
    they read its datasets (``DiscoveryService.collection``): such a
    collection's cached copies are the owner's, read where her store keeps
    them (``DiscoveryService.collection_store``). Anyone else reads what a run
    that names no dataflow reads.
    """
    if not user_key:
        return {}, None
    try:
        media_dir = media_dir_for(user_key)
        ids = collection_ids_in_code(code, limit=MAX_DATASET_IDS)
        if not ids:
            return {}, media_dir
        return resolve_collections(ids, user_key, user=user, dataflow_id=dataflow_id), media_dir
    except Exception as e:  # noqa: BLE001 - resolution must never fail the execution
        print(f"[exec] collection resolution failed: {e}", flush=True)
        return {}, None


def media_dir_for(user_key: str | None) -> str | None:
    """Where a node run under *user_key* writes the frames, clips and
    overlays it derives; None with no key. Every node gets it, not only one
    that loads a collection: a node downstream of a Data Loading node writes
    the frames or the mosaic, and never names the collection itself. A
    hosted guest's run writes in the folder of the visitor it serves, in
    their request or on a thread of its own (``visitor_copies.media_visitor``),
    which the media route reads for that visitor alone."""
    if not user_key:
        return None
    from utk_curio.backend.app.discovery.infrastructure import media_dirs
    from utk_curio.backend.app.projects import visitor_copies

    return str(media_dirs.derived_root(user_key, visitor_copies.media_visitor(user_key)))


def resolve_collections(
    ids: list[str], user_key: str, *, user=None, dataflow_id: str | None = None,
) -> dict:
    """``{datasetId: {root, objects, kind}}`` for each of *ids* that is a
    collection, as :func:`resolve_exec_collections` gives it to a run under
    *user_key*. An id that is no collection the account reads is left out.
    One lookup per id, through the Data Catalog, which asks the database.

    A bucket this deployment mounts is read in place: its ``root`` is its
    mount's folder, and ``tail`` what each file's path there starts with
    before its relpath (``domain/bucket_mount.py``). While its mount is down
    it has ``unavailable``, why, which ``curio_load_collection`` raises; its
    copies cached before are not read."""
    from utk_curio.backend.app.discovery.application import bucket_mount_sources, cache_collection
    from utk_curio.backend.app.discovery.infrastructure import storage
    from utk_curio.backend.app.discovery.service import DiscoveryService

    service = DiscoveryService(user_key, user=user, dataflow_id=dataflow_id)
    out = {}
    for dataset_id in ids:
        try:
            item, manifest = service.collection(dataset_id)
        except Exception:  # noqa: BLE001 - one missing collection is its node's error
            continue
        entry = {"kind": (item.get("collection") or {}).get("kind")}
        mount = None if manifest.provider.type == "folder" else bucket_mount_sources.ensure(manifest)
        if manifest.provider.type == "folder":
            entry["root"] = str(storage.storage_root(manifest))
        elif mount is not None and mount.mounted:
            entry["root"] = str(mount.folder)
            entry["tail"] = mount.tail
        elif mount is not None and mount.state == "down":
            entry["unavailable"] = mount.reason or "its mount is down"
        else:
            # The cached copies are where the collection's store keeps
            # them; a store other than the run's is read, never made into.
            store_key = service.collection_store(item)
            entry["objects"] = str(
                cache_collection.objects_dir(store_key, dataset_id, create=store_key == user_key)
            )
        out[dataset_id] = entry
    return out


def resolve_spec_collections(
    spec_dict: dict | None, user_key: str | None, *extra: str | None, user=None,
    dataflow_id: str | None = None,
) -> tuple[dict, str | None]:
    """:func:`resolve_exec_collections` for every node's code in *spec_dict*,
    as a run writes it (``node_run_code``: a dataset widget may hold a
    collection's id), plus *extra* (a candidate not yet in the spec), for a
    run of the dataflow *dataflow_id*.

    *user* is the account's ``User`` row. A caller on a thread of its own
    (Solve's validation, a node run's worker) passes the one it captured in
    the request; without it, the request's user is used when there is one.
    """
    from utk_curio.backend.app.execution.code_references import node_run_code

    codes = [node_run_code(n) for n in ((spec_dict or {}).get("dataflow") or {}).get("nodes") or [] if isinstance(n, dict)]
    codes.extend(str(c or "") for c in extra)
    if user is None:
        try:
            from flask import g, has_request_context

            user = getattr(g, "user", None) if has_request_context() else None
        except Exception:  # noqa: BLE001 - no Flask, no user
            user = None
    return resolve_exec_collections("\n".join(codes), user_key, user=user, dataflow_id=dataflow_id)
