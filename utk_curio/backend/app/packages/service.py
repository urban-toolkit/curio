"""Public facade of the packages application layer (memo dev/143, B2).

The implementation lives in the layered ``application/`` modules; this module is the
single stable entry point for routes, ``projects``, ``testing``, the agents and the app
factory. Nothing is defined here. Mirrors ``datasets/service.py`` and ``agents/service.py``.
"""

from __future__ import annotations

from utk_curio.backend.app.packages.domain.manifest import ManifestError
from utk_curio.backend.app.packages.domain.package_id import PackageIdError
from utk_curio.backend.app.packages.domain.versions import ResolverError
from utk_curio.backend.app.packages.repositories.archive import InstallerError
from utk_curio.backend.app.packages.repositories.catalog_dir import catalog_root
from utk_curio.backend.app.packages.infrastructure.backend_runtime import BackendRuntimeError
from utk_curio.backend.app.packages.infrastructure.pip_runner import (
    PipInstallError,
    PipSpecError,
)
from utk_curio.backend.app.packages.application.agent_reads import (
    agent_catalog_overview,
    agent_resolve_report,
    template_for_writing,
    template_landscape,
)
from utk_curio.backend.app.packages.application.defaults_install import (
    install_to_defaults,
    uninstall_from_defaults,
)
from utk_curio.backend.app.packages.domain.errors import PackageServiceError
from utk_curio.backend.app.packages.application.project_packages import (
    OwnersPackages,
    detach_from_all_projects,
    get_project_lockfile,
    install_to_project,
    uninstall_from_project,
)
from utk_curio.backend.app.packages.application.provisioning import (
    InstallOutcome,
    assert_may_install,
    provision_declared_deps,
    provision_python_deps,
)
from utk_curio.backend.app.packages.application.libraries import (
    install_user_library,
    uninstall_user_library,
    user_library_import_failure,
)
from utk_curio.backend.app.packages.application.prune import prune_unreferenced_packages
from utk_curio.backend.app.packages.application.python_modules import module_index, modules_for_node
from utk_curio.backend.app.packages.application.seeding import (
    seed_dev_packages,
    ensure_user_packages_initialized,
    seed_spec_with_defaults,
)
from utk_curio.backend.app.packages.application.store_install import install_to_store
from utk_curio.backend.app.packages.application.template_packages import template_slug
from utk_curio.backend.app.packages.application.templates import (
    available_templates,
    available_templates_report,
    canonical_template_id,
    catalog_template_flags,
    CONTENT_KIND_CODE,
    CONTENT_KIND_GRAMMAR,
    CONTENT_KIND_NONE,
    CONTENT_KIND_NOTE,
    input_capacity,
    installed_templates_not_in_project,
    is_note_template,
    presentation_templates,
    resolve_template,
    resolve_templates,
    roster_templates,
    TEMPLATE_FLAGS,
    catalog_template_behaviors,
    catalog_template_labels,
    template_content_kind,
    template_flags,
    template_is_executable,
)
from utk_curio.backend.app.packages.application.node_templates import installed_template, template_behavior
from utk_curio.backend.app.packages.application.package_skills import dataflow_skill_folders, package_skill_names
from utk_curio.backend.app.packages.builder.factory import FactoryError

from utk_curio.backend.app.packages.application.store_install import (
    install_package_from_archive,
    install_package_from_directory,
    remove_package,
    uninstall_package,
    export_package_archive,
)
from utk_curio.backend.app.packages.application.starters import (
    content_starters,
    declared_widgets,
    generate_package_starters,
)
from utk_curio.backend.app.packages.application.model_packages import (
    ListedModelPackage,
    held_model_packages,
    list_model_packages,
    model_default_cell,
    resolve_model_dirs,
)
from utk_curio.backend.app.packages.application.model_downloads import (
    downloaded_model_ids,
    downloaded_model_package,
    install_downloaded_model,
    install_downloaded_model_deps,
    model_add_refusal,
    model_library_refusal,
    model_package_row,
)
from utk_curio.backend.app.packages.domain.default_cells import model_loader_line, model_template

# The names other features take from the package (memo dev/143 B5: the agents, the
# projects service, the launcher and the testing routes import THESE from here, never
# from a layer module). Domain readers, store paths and the two runtime seams.
from utk_curio.backend.app.packages.domain.package_id import (
    PACKAGE_DIR_RE,
    PackageId,
)
from utk_curio.backend.app.packages.domain.manifest import PackageManifest
from utk_curio.backend.app.packages.domain.dataflow_categories import declared_dataflow_categories
from utk_curio.backend.app.packages.domain.spec_packages import (
    dir_name_from_model_ref,
    dir_name_from_node_type,
    is_package_node_type,
    preserve_project_packages,
    project_packages,
    set_project_packages,
    unversioned_node_type,
)
from utk_curio.backend.app.packages.domain.versions import merge_python_deps
from utk_curio.backend.app.packages.repositories.archive import (
    refresh_package_integrity,
)
from utk_curio.backend.app.packages.repositories.manifests import (
    load_package_manifest,
)
from utk_curio.backend.app.packages.repositories.store import (
    package_dir,
    user_packages_dir,
)
from utk_curio.backend.app.packages.infrastructure.backend_runtime import (
    dep_destinations,
    dep_destinations_raw,
    per_user_node_envs,
    user_node_overlay_dir,
)
from utk_curio.backend.app.packages.infrastructure.pip_runner import install_python_deps
from utk_curio.backend.app.packages.application.seeding import example_dep_package_ids

__all__ = [
    "PACKAGE_DIR_RE",
    "PackageId",
    "PackageManifest",
    "declared_dataflow_categories",
    "dir_name_from_model_ref",
    "dir_name_from_node_type",
    "is_package_node_type",
    "preserve_project_packages",
    "project_packages",
    "set_project_packages",
    "unversioned_node_type",
    "merge_python_deps",
    "refresh_package_integrity",
    "load_package_manifest",
    "package_dir",
    "user_packages_dir",
    "dep_destinations",
    "dep_destinations_raw",
    "install_python_deps",
    "example_dep_package_ids",
    "content_starters",
    "declared_widgets",
    "generate_package_starters",
    "seed_dev_packages",
    "install_package_from_archive",
    "install_package_from_directory",
    "remove_package",
    "uninstall_package",
    "export_package_archive",
    "agent_catalog_overview",
    "agent_resolve_report",
    "template_for_writing",
    "template_landscape",
    "install_to_defaults",
    "uninstall_from_defaults",
    "PackageServiceError",
    "InstallerError",
    "get_project_lockfile",
    "install_to_project",
    "uninstall_from_project",
    "OwnersPackages",
    "InstallOutcome",
    "provision_declared_deps",
    "provision_python_deps",
    "prune_unreferenced_packages",
    "module_index",
    "modules_for_node",
    "ResolverError",
    "ensure_user_packages_initialized",
    "seed_spec_with_defaults",
    "install_to_store",
    "template_slug",
    "CONTENT_KIND_CODE",
    "CONTENT_KIND_GRAMMAR",
    "CONTENT_KIND_NONE",
    "CONTENT_KIND_NOTE",
    "available_templates",
    "available_templates_report",
    "canonical_template_id",
    "catalog_template_flags",
    "installed_templates_not_in_project",
    "is_note_template",
    "presentation_templates",
    "resolve_template",
    "resolve_templates",
    "roster_templates",
    "TEMPLATE_FLAGS",
    "catalog_template_behaviors",
    "installed_template",
    "template_behavior",
    "dataflow_skill_folders",
    "package_skill_names",
    "template_content_kind",
    "template_flags",
    "template_is_executable",
    "FactoryError",
    "ManifestError",
    "BackendRuntimeError",
    "PipInstallError",
    "PipSpecError",
    "catalog_root",
    "PackageIdError",
    "assert_may_install",
    "install_user_library",
    "uninstall_user_library",
    "user_library_import_failure",
    "detach_from_all_projects",
    "input_capacity",
    "per_user_node_envs",
    "user_node_overlay_dir",
    "ListedModelPackage",
    "held_model_packages",
    "list_model_packages",
    "model_default_cell",
    "resolve_model_dirs",
    "install_downloaded_model",
    "install_downloaded_model_deps",
    "downloaded_model_ids",
    "downloaded_model_package",
    "model_add_refusal",
    "model_library_refusal",
    "model_package_row",
    "model_loader_line",
    "model_template",
]
