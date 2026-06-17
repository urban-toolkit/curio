"""Per-user node-package store.

Packages live on disk at::

    <CURIO_LAUNCH_CWD>/.curio/users/<user_key>/packages/<packageId>@<major>/

Each package is fully self-contained: every Python template preset, grammar spec,
widget spec, and icon a package uses lives **inside** the package archive root. Package
code MUST NOT reference ``<CURIO_LAUNCH_CWD>/templates/`` or any other path
outside its own package directory; that built-in folder is reserved for built-in
``NodeType`` presets.

See ``docs/schemas/node-package.v4.json`` for the package manifest schema and
``docs/CATALOG.md`` for the user-facing overview.
"""

from utk_curio.backend.app.packages.storage import (
    PackageId,
    package_dir,
    list_user_packageages,
    PACKAGE_DIR_RE,
    PackageIdError,
)
from utk_curio.backend.app.packages.manifest import (
    PackageManifest,
    TemplateManifest,
    PackageLineage,
    PackageLineageCoord,
    load_packageage_manifest,
    ManifestError,
)
from utk_curio.backend.app.packages.installer import (
    InstallerError,
    InstallResult,
    export_packageage_archive,
    install_packageage_from_archive,
    install_packageage_from_directory,
    uninstall_packageage,
)
from utk_curio.backend.app.packages.factory import (
    BuildResult,
    FactoryError,
    build_packageage_archive,
)
from utk_curio.backend.app.packages.resolver import (
    DepConflict,
    ResolveResult,
    ResolverError,
    lockfile_for_user,
    merge_python_deps,
    parse_range,
    parse_version,
    resolve_for_project,
)
from utk_curio.backend.app.packages.routes import packages_bp
from utk_curio.backend.app.packages.seed import seed_dev_packageages
from utk_curio.backend.app.packages.starters import generate_packageage_starters

__all__ = [
    # storage
    "PackageId",
    "PackageIdError",
    "PACKAGE_DIR_RE",
    "package_dir",
    "list_user_packageages",
    # manifest
    "PackageManifest",
    "TemplateManifest",
    "PackageLineage",
    "PackageLineageCoord",
    "ManifestError",
    "load_packageage_manifest",
    # installer
    "InstallerError",
    "InstallResult",
    "install_packageage_from_archive",
    "install_packageage_from_directory",
    "uninstall_packageage",
    "export_packageage_archive",
    # factory
    "BuildResult",
    "FactoryError",
    "build_packageage_archive",
    # resolver
    "DepConflict",
    "ResolveResult",
    "ResolverError",
    "lockfile_for_user",
    "merge_python_deps",
    "parse_range",
    "parse_version",
    "resolve_for_project",
    # routes + starters + seed
    "packages_bp",
    "generate_packageage_starters",
    "seed_dev_packageages",
]
