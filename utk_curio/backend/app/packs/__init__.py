"""Per-user node-pack store.

Packs live on disk at::

    <CURIO_LAUNCH_CWD>/.curio/users/<user_key>/packs/<packId>@<major>/

Each pack is fully self-contained: every Python template preset, grammar spec,
widget spec, and icon a pack uses lives **inside** the pack archive root. Pack
code MUST NOT reference ``<CURIO_LAUNCH_CWD>/templates/`` or any other path
outside its own pack directory; that built-in folder is reserved for built-in
``NodeType`` presets.

See ``docs/schemas/node-pack.v2.json`` for the pack manifest schema and
``docs/WAREHOUSE.md`` for the user-facing overview.
"""

from utk_curio.backend.app.packs.storage import (
    PackId,
    pack_dir,
    list_user_packs,
    PACK_DIR_RE,
    PackIdError,
)
from utk_curio.backend.app.packs.manifest import (
    PackManifest,
    NodeKindManifest,
    PackLineage,
    PackLineageCoord,
    load_pack_manifest,
    ManifestError,
)
from utk_curio.backend.app.packs.installer import (
    InstallerError,
    InstallResult,
    export_pack_archive,
    install_pack_from_archive,
    install_pack_from_directory,
    uninstall_pack,
)
from utk_curio.backend.app.packs.factory import (
    BuildResult,
    FactoryError,
    build_pack_archive,
)
from utk_curio.backend.app.packs.resolver import (
    DepConflict,
    ResolveResult,
    ResolverError,
    lockfile_for_user,
    merge_python_deps,
    parse_range,
    parse_version,
    resolve_for_project,
)
from utk_curio.backend.app.packs.routes import packs_bp
from utk_curio.backend.app.packs.seed import seed_dev_packs
from utk_curio.backend.app.packs.templates import generate_pack_templates

__all__ = [
    # storage
    "PackId",
    "PackIdError",
    "PACK_DIR_RE",
    "pack_dir",
    "list_user_packs",
    # manifest
    "PackManifest",
    "NodeKindManifest",
    "PackLineage",
    "PackLineageCoord",
    "ManifestError",
    "load_pack_manifest",
    # installer
    "InstallerError",
    "InstallResult",
    "install_pack_from_archive",
    "install_pack_from_directory",
    "uninstall_pack",
    "export_pack_archive",
    # factory
    "BuildResult",
    "FactoryError",
    "build_pack_archive",
    # resolver
    "DepConflict",
    "ResolveResult",
    "ResolverError",
    "lockfile_for_user",
    "merge_python_deps",
    "parse_range",
    "parse_version",
    "resolve_for_project",
    # routes + templates + seed
    "packs_bp",
    "generate_pack_templates",
    "seed_dev_packs",
]
