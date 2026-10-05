"""Where the Scenario Catalog reads from: the account's projects, and the
outputs they saved to its Data Catalog. Nothing of its own is stored."""
from __future__ import annotations

from typing import Any


class ProjectNotFound(Exception):
    pass


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


def graph_preview(spec: dict) -> dict | None:
    """The plain-box graph a project card draws."""
    from utk_curio.backend.app.projects.services import _extract_graph_preview

    return _extract_graph_preview(spec)


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


def output_refs(user, project_id: str) -> dict[str, Any]:
    """``{nodeId: OutputRef}``: the outputs *project_id*'s manifest restores."""
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.services import _output_refs_from_manifest

    manifest = storage.read_manifest(user_key(user), project_id)
    return {ref.node_id: ref for ref in _output_refs_from_manifest(manifest)}


def copy_output(user, dir_name: str, *, node_id: str, project_id: str, project_name: str) -> str:
    """Copy a saved output to *node_id* of *project_id*; returns the copy's id."""
    from utk_curio.backend.app.datasets.install.copy import copy_computed_dataset

    result = copy_computed_dataset(
        user_key(user), dir_name, node_id=node_id, dataflow_id=project_id, dataflow_name=project_name,
    )
    return result.manifest.id


def restore_outputs(user, project_id: str, refs: list) -> list:
    """Put *refs*, whose datasets *project_id* now holds, where a canvas reads
    outputs from, as opening the project does. Returns the refs restored."""
    from utk_curio.backend.app.projects import storage

    return storage.hydrate_outputs(user_key(user), project_id, refs)


def output_ref(node_id: str, filename: str, data_type: str | None):
    from utk_curio.backend.app.projects.schemas import OutputRef

    return OutputRef(node_id=node_id, filename=filename, data_type=data_type)


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
