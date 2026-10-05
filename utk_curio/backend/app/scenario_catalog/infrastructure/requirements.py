"""What a dropped scenario's levers need in the dataflow they arrive in: their
packages, added the way the Node Catalog adds one to a project, and the
datasets and models they read, which the account must hold (#662)."""
from __future__ import annotations


def package_dirs(user_key: str, source_project_id: str, node_types: list[str]) -> dict[str, str | None]:
    """``{node type: package dirName}``, as the source project resolves each:
    the package its lockfile holds, else the type's own version, else the
    account's newest one. ``None`` when nothing names one."""
    from utk_curio.backend.app.packages import service as packages
    from utk_curio.backend.app.packages.application.store_reads import _installed_majors_by_pkg

    try:
        lockfile = packages.get_project_lockfile(user_key, source_project_id)
    except packages.PackageServiceError:
        lockfile = set()
    by_package = {name.split("@", 1)[0]: name for name in lockfile}
    majors = _installed_majors_by_pkg(user_key)
    out: dict[str, str | None] = {}
    for node_type in node_types:
        versioned = packages.dir_name_from_node_type(node_type)
        if versioned:
            out[node_type] = versioned
            continue
        out[node_type] = by_package.get(node_type.split("/", 1)[0]) or packages.dir_name_from_node_type(node_type, majors)
    return out


def project_packages(user_key: str, project_id: str) -> set[str]:
    from utk_curio.backend.app.packages import service as packages

    try:
        return set(packages.get_project_lockfile(user_key, project_id))
    except packages.PackageServiceError:
        return set()


def is_builtin(dir_name: str) -> bool:
    """The built-in package is part of every project; it is never added."""
    from utk_curio.backend.app.packages.application.seeding import BUILTIN_PACKAGE_ID

    return dir_name.split("@", 1)[0] == BUILTIN_PACKAGE_ID


def package_problem(user, user_key: str, dir_name: str) -> str | None:
    """Why *dir_name* cannot be added to a project of this account, or ``None``.

    The account's own copy is added as it is; one only the shipped Node
    Catalog has is copied in first, which this account must be allowed to do.
    """
    from utk_curio.backend.app.packages import service as packages
    from utk_curio.backend.app.users.capabilities import package_install_refusal

    if not packages.PACKAGE_DIR_RE.match(dir_name):
        return f"the package {dir_name}, which is not in your Node Catalog"
    if (packages.package_dir(user_key, dir_name) / "manifest.json").is_file():
        return None
    if not (packages.catalog_root() / dir_name).is_dir():
        return f"the package {dir_name}, which is not in your Node Catalog"
    refusal = package_install_refusal(user)
    if refusal:
        return f"the package {dir_name}, which this account cannot add: {refusal}"
    return None


def add_package(user_key: str, project_id: str, dir_name: str) -> str | None:
    """Add *dir_name* to the project, as the Node Catalog's Add does. Returns
    why it could not be, or ``None``."""
    from utk_curio.backend.app.packages import service as packages

    try:
        packages.install_to_project(user_key, project_id, dir_name)
    except packages.PackageServiceError as exc:
        return str(exc)
    return None


def dataset_problem(user, dataset_id: str) -> str | None:
    from utk_curio.backend.app.datasets.service import DatasetCatalogError, DatasetCatalogService

    try:
        DatasetCatalogService(user).get_dataset(dataset_id)
    except DatasetCatalogError:
        return f"the dataset {dataset_id}, which is not in your Data Catalog"
    return None


def model_problem(user, model_id: str) -> str | None:
    from utk_curio.backend.app.model_catalog.service import ModelCatalogError, ModelCatalogService

    try:
        ModelCatalogService(user).get_model(model_id)
    except ModelCatalogError:
        return f"the model {model_id}, which is not in your Model Catalog"
    return None
