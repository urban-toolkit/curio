"""The changes to a dataflow's datasets that a request made for an account
writes: each made by the backend process that owns the dataflow
(``collaboration/owner_calls.py``).

A dataset added to or removed from all projects, a dataset deleted from the
account, a dataset's id migrated, and publishing or unpublishing a dataset
from a page that names its dataflow in the request's body: the request names
no dataflow in its path, so it may reach any process, and it writes dataflows
any process may own. Each is an operation on one dataflow, made through the
dataset service as it is made for one dataflow's own request, for the account
whose id it is sent with.
"""

from __future__ import annotations

from typing import Any, Optional

from utk_curio.backend.app.collaboration import owner_calls
from utk_curio.backend.app.datasets.domain.errors import DatasetCatalogError


def _service(user_id: Optional[int]):
    """The dataset service of the account *user_id*, as its own request has it."""
    from utk_curio.backend.app.datasets.application.catalog_service import DatasetCatalogService
    from utk_curio.backend.app.users.models import User
    from utk_curio.backend.extensions import db

    user = db.session.get(User, user_id) if user_id is not None else None
    if user is None:
        raise DatasetCatalogError("Authorization required", 401)
    return DatasetCatalogService(user)


@owner_calls.operation("datasets.install", error=DatasetCatalogError)
def install(user_key: str, dataflow_id: str, *, user_id: int, dataset_id: str) -> Any:
    """Install *dataset_id* into the dataflow: the item installed."""
    return _service(user_id).install_dataset(dataflow_id, dataset_id)


@owner_calls.operation("datasets.uninstall", error=DatasetCatalogError)
def uninstall(user_key: str, dataflow_id: str, *, user_id: int, dataset_id: str,
              delete_orphaned_import: bool) -> Any:
    """Take *dataset_id* out of the dataflow."""
    return _service(user_id).uninstall_dataset(
        dataflow_id, dataset_id, delete_orphaned_import=delete_orphaned_import,
    )


@owner_calls.operation("datasets.remove-references", error=DatasetCatalogError)
def remove_references(user_key: str, dataflow_id: str, *, user_id: int, dataset_id: str) -> bool:
    """Strip every reference to *dataset_id*, deleted from the account, from
    the dataflow: whether it held one."""
    return _service(user_id).installed.remove_dataset_references(dataflow_id, dataset_id)


@owner_calls.operation("datasets.rewrite-ref", error=DatasetCatalogError)
def rewrite_ref(user_key: str, dataflow_id: str, *, old_id: str, new_id: str, new_dir_name: str) -> None:
    """Point the dataflow's ref of the computed dataset *old_id* at its
    migrated id (``migrations.migrate_computed_dataset_ids``)."""
    from utk_curio.backend.app.datasets.application import migrations

    migrations._rewrite_spec_ref(user_key, dataflow_id, old_id, new_id, new_dir_name)


@owner_calls.operation("datasets.stamp-published", error=DatasetCatalogError)
def stamp_published(user_key: str, dataflow_id: str, *, user_id: Optional[int], dataset_id: str, catalog_id: str,
                    dir_name: str, publish_is_computed: bool, prior_producer_node_id) -> None:
    """Stamp the dataflow's refs of *dataset_id* published as *catalog_id*
    (``mutations.stamping_published``)."""
    from utk_curio.backend.app.datasets.application.mutations import stamping_published

    _service(user_id).installed.mutate_refs(dataflow_id, stamping_published(
        dataset_id, catalog_id, dir_name, publish_is_computed, prior_producer_node_id,
    ))


@owner_calls.operation("datasets.clear-published", error=DatasetCatalogError)
def clear_published(user_key: str, dataflow_id: str, *, user_id: Optional[int], dataset_id: str) -> None:
    """Clear the published flag of the dataflow's refs of *dataset_id*
    (``mutations.clearing_published``)."""
    from utk_curio.backend.app.datasets.application.mutations import clearing_published

    _service(user_id).installed.mutate_refs(dataflow_id, clearing_published(dataset_id))
