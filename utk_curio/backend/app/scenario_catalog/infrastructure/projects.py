"""Where the Scenario Catalog reads from: the account's projects, and the
outputs they saved to its Data Catalog. Nothing of its own is stored."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


class ProjectNotFound(Exception):
    pass


class OutputGone(Exception):
    """The saved output of *node_id* that a drop copies is no longer there."""

    def __init__(self, node_id: str) -> None:
        super().__init__(node_id)
        self.node_id = node_id


class CopyFailed(Exception):
    """The saved output of *node_id* could not be copied: its folder could
    not be read, or the copy could not be written. Trying again may work."""

    def __init__(self, node_id: str) -> None:
        super().__init__(node_id)
        self.node_id = node_id


@dataclass(frozen=True)
class CopiedOutputs:
    """What :func:`copy_outputs` did: ``{node: datasetId}``, the dataset each
    copy's node reads, and the output refs restored for the canvas."""

    dataset_ids: dict[str, str]
    restored: list


def project_summaries(user) -> list:
    """The account's project summaries, as the Projects page lists them: each
    carries its scenarios and its graph preview."""
    from utk_curio.backend.app.projects import services

    return services.list_projects(user)


def owned_project(user, project_id: str) -> tuple[Any, dict, bool]:
    """``(row, spec, is_example)`` for one of the account's projects. Another
    account's project, or one whose spec is gone, is not found."""
    from utk_curio.backend.app.projects import repositories, storage
    from utk_curio.backend.app.projects.seed import is_example_project
    from utk_curio.backend.app.projects.services import _user_dir_key

    try:
        row = repositories.get_for_user(project_id, user.id)
    except repositories.NotFoundError as exc:
        raise ProjectNotFound(project_id) from exc
    spec = storage.read_spec(_user_dir_key(user), project_id)
    if spec is None:
        raise ProjectNotFound(project_id)
    return row, spec, is_example_project(user, project_id)


def updated_at(row) -> str:
    """When the project *row* last changed, as the Projects page says it."""
    from utk_curio.backend.app.projects.services import updated_at_of

    return updated_at_of(row)


def graph_preview(user, spec: dict) -> dict | None:
    """The plain-box graph a project card draws, each node with the category
    its template declares in the account's manifests or the catalog's."""
    from utk_curio.backend.app.projects.categories import ManifestLookup
    from utk_curio.backend.app.projects.services import _extract_graph_preview

    return _extract_graph_preview(spec, ManifestLookup(user_key(user)))


def saved_outputs(user, project_id: str) -> dict[str, dict]:
    """``{datasetId: item}`` for the outputs *project_id* saved."""
    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    return {item["id"]: item for item in DatasetCatalogService(user).list_dataflow_outputs(project_id)}


def computed_dataset_id(node_id: str, project_id: str) -> str:
    """The id a node's saved output has in the Data Catalog."""
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id as _id

    return _id(node_id, project_id)


def user_key(user) -> str:
    from utk_curio.backend.app.projects.services import _user_dir_key

    return _user_dir_key(user)


def saved_output(user, project_id: str, spec: dict, node_id: str) -> dict | None:
    """The dataset that holds *node_id*'s saved output in *project_id*, looked
    for in the order a reload restores from (``storage._durable_source_for``):
    the node's computed dataset in the account, else a dataset the project
    installed for it, such as the output once published. ``{"datasetId",
    "dirName", "computed"}``, or ``None``."""
    from utk_curio.backend.app.datasets.domain.manifest import ManifestError, load_dataset_manifest
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir

    ukey = user_key(user)
    dataset_id = computed_dataset_id(node_id, project_id)
    try:
        load_dataset_manifest(dataset_dir(ukey, f"{dataset_id}@1"))
        return {"datasetId": dataset_id, "dirName": f"{dataset_id}@1", "computed": True}
    except (ManifestError, OSError, ValueError):
        pass
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    for ref in (dataflow or {}).get("datasets") or []:
        if isinstance(ref, dict) and ref.get("producerNodeId") == node_id and ref.get("dirName") and ref.get("id"):
            return {"datasetId": ref["id"], "dirName": ref["dirName"], "computed": False}
    return None


def saved_outputs_of(user, project_id: str, spec: dict, node_ids: list[str]) -> dict[str, dict | None]:
    """``{nodeId: saved_output(...)}`` for *node_ids*, read under *project_id*'s
    spec lock, so a save of it installing an output again is waited for rather
    than met halfway (#941). The caller holds no spec lock and no uncommitted
    database write (#909)."""
    from utk_curio.backend.app.projects import storage

    with storage.spec_write_lock(user_key(user), project_id):
        return {node_id: saved_output(user, project_id, spec, node_id) for node_id in node_ids}


def output_refs(user, project_id: str) -> dict[str, Any]:
    """``{nodeId: OutputRef}``: the outputs *project_id*'s manifest restores."""
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.services import _output_refs_from_manifest

    manifest = storage.read_manifest(user_key(user), project_id)
    return {ref.node_id: ref for ref in _output_refs_from_manifest(manifest)}


def copy_outputs(
    user, source_id: str, spec: dict, pairs: list[tuple[str, str]], *, target_id: str, target_name: str,
) -> CopiedOutputs:
    """Copy the saved output of each ``(source, node)`` pair's *source* in
    *source_id*, whose spec is *spec*, to *node* in *target_id*, and record
    each copy as its node's saved output in *target_id*, so the target's
    canvas reads it in place before any save (``storage.saved_output_file``).

    A save writes the outputs it sends under its project's spec lock. So each
    project is read or written under its own lock, one lock at a time (#941):

    1. Under the source's lock: the refs its manifest restores, each pair's
       saved output, and a whole copy of each computed one in a staging folder
       (``copy.stage_computed_copy``). Nothing is written to the database.
    2. Under the target's lock: each staged copy takes its place and is indexed
       (``copy.place_staged_copy``), then the target's manifest records the
       copies that are readable (``storage.record_outputs``).

    The source may be the target, and two drops each way between two projects
    never wait for each other. The caller holds no spec lock and no uncommitted
    database write (#909). A saved output that is gone raises
    :class:`OutputGone`, one that cannot be copied :class:`CopyFailed`, and a
    staged copy that never took its place is removed.
    """
    from utk_curio.backend.app.datasets.install import copy as dataset_copy
    from utk_curio.backend.app.datasets.install.installer import InstallerError
    from utk_curio.backend.app.projects import storage

    ukey = user_key(user)
    staged: list[tuple[str, str, Any]] = []
    dataset_ids: dict[str, str] = {}
    refs: list = []
    source = ""
    try:
        with storage.spec_write_lock(ukey, source_id):
            restorable = output_refs(user, source_id)
            for source, node in pairs:
                saved = saved_output(user, source_id, spec, source)
                if saved is None:
                    raise OutputGone(source)
                if not saved["computed"]:
                    dataset_ids[node] = saved["datasetId"]
                    continue
                staged.append((source, node, dataset_copy.stage_computed_copy(
                    ukey, saved["dirName"], target_key=ukey,
                    node_id=node, dataflow_id=target_id, dataflow_name=target_name,
                )))
                ref = restorable.get(source)
                if ref is not None:
                    refs.append(output_ref(node, ref.filename, ref.data_type))
        with storage.spec_write_lock(ukey, target_id):
            while staged:
                source, node, copy = staged.pop(0)
                dataset_ids[node] = dataset_copy.place_staged_copy(ukey, copy).manifest.id
            restored = storage.readable_saved_outputs(ukey, target_id, refs)
            storage.record_outputs(ukey, target_id, [_manifest_entry(ref) for ref in restored])
    except InstallerError as exc:
        logger.warning(
            "Could not copy the saved output of %s in %s into %s: %s", source, source_id, target_id, exc,
        )
        raise CopyFailed(source) from exc
    finally:
        for _source, _node, copy in staged:
            dataset_copy.discard_staged_copy(copy)
    return CopiedOutputs(dataset_ids=dataset_ids, restored=restored)


def output_ref(node_id: str, filename: str, data_type: str | None):
    from utk_curio.backend.app.projects.schemas import OutputRef

    return OutputRef(node_id=node_id, filename=filename, data_type=data_type)


def _manifest_entry(ref) -> dict:
    """The manifest's record of a copied output, stamped as a save stamps the
    output it sends (``services._produced_at``)."""
    from utk_curio.backend.app.projects.services import _produced_at

    entry = {"node_id": ref.node_id, "filename": ref.filename, "produced_at": _produced_at(ref.filename)}
    if ref.data_type:
        entry["data_type"] = ref.data_type
    return entry


def dataset_items(user, project_id: str, ids: set[str]) -> dict[str, dict]:
    """``{datasetId: item}`` for *ids*, as the Data Catalog lists them: the
    project's own saved outputs, else the account's datasets."""
    from utk_curio.backend.app.datasets.service import DatasetCatalogError, DatasetCatalogService

    service = DatasetCatalogService(user)
    items = {item["id"]: item for item in service.list_dataflow_outputs(project_id) if item["id"] in ids}
    for dataset_id in ids - set(items):
        try:
            items[dataset_id] = service.get_dataset(dataset_id)
        except DatasetCatalogError:
            continue
    return items
