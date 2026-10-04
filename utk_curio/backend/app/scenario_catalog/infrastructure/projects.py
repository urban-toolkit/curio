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
