"""Per-user node-package store.

Packages live on disk at::

    <CURIO_LAUNCH_CWD>/.curio/users/<user_key>/packages/<packageId>@<major>/

Each package is fully self-contained: every Python template preset, grammar spec,
widget spec, and icon a package uses lives **inside** the package archive root. Package
code MUST NOT reference ``<CURIO_LAUNCH_CWD>/templates/`` or any other path
outside its own package directory; that built-in folder is reserved for built-in
``NodeType`` presets.

See ``docs/schemas/node-package.v4.json`` for the package manifest schema and
``docs/NODE-CATALOG.md`` for the user-facing overview.

Layout (memo dev/143): ``domain/`` (pure rules), ``schemas/`` (wire shapes),
``repositories/`` (the stores), ``infrastructure/`` (processes, subprocesses,
locks), ``application/`` (the use cases), ``builder/`` (the Package Builder
pipeline, a subsystem beside the layers), ``routes/`` (presentation), behind the
one facade ``service.py``. This root exports only what the app factory boots.
"""

from utk_curio.backend.app.packages.application.seeding import (
    seed_dev_packages,
)
from utk_curio.backend.app.packages.routes import packages_bp

__all__ = ["packages_bp", "seed_dev_packages"]
