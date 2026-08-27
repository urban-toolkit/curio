"""Provision the datasets the seeded example dataflows declare they need.

The counterpart to :mod:`utk_curio.backend.app.packages.seed`, and deliberately
shaped the same way. An example dataflow declares its node packages in
``dataflow.packages`` and its datasets in ``dataflow.datasets``; the committed
spec is the source of truth in both cases, and the seeder is purely a
*provisioning* step that makes the declaration real on this machine.

WHY A COPY IS NEEDED AT ALL
---------------------------
A ``dataflow.datasets`` ref on its own is *almost* enough for a dataset that
ships in the committed catalog. ``CatalogListing.list_catalog`` also yields a
hub row for it, that row outranks the ref row in ``domain/dedup.py``, and the
merge lifts ``installed: True`` off the loser - so the drawer, preview, export
and ``curio_dataset_path()`` execution all work with no copy anywhere.

The Data palette is the exception, and it is the reason this module exists. It
queries with ``includeHub: false``, which skips ``registry.list_items()``
entirely, so there is no hub row to merge with and the only row is the
placeholder ``InstalledDatasetRepository.list_items`` builds in its ``except``
branch. That row still passes ``isUserInstalledDataset`` (the placeholder sets
``installed=True``) and therefore renders, but it renders from nothing: the
title falls back to the raw ``dirName``, the format chip says ``csv`` for every
dataset because a lean ref carries no ``format``, and there is no row or feature
count. Copying the dataset into the user's store is what makes the palette show
a real name, a real format and a real size.

WHAT THIS DOES NOT DO
---------------------
It does not write the ``dataflow.datasets`` ref: that is committed in the
example JSON, and ``projects/seed.py`` writes the spec verbatim. Calling the
full ``mutations.install_dataset`` here would need an app plus DB context and a
committed ``Project`` row, and its ref write would be clobbered by
``seed_example_projects``'s unconditional ``write_spec`` on the next boot
anyway.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _examples_dir() -> Path:
    # utk_curio/backend/app/datasets/seed.py  ->  <repo_root>/docs/examples/
    return Path(__file__).resolve().parents[4] / "docs" / "examples"


def example_dep_dataset_dirs() -> tuple[str, ...]:
    """Dataset directory names the seeded example dataflows declare they need.

    Scans ``docs/examples/*.json`` and unions each spec's
    ``dataflow.datasets`` refs, returning their ``dirName``s sorted - so the
    seeder provisions exactly the datasets the examples reference, with no
    hardcoded allowlist to keep in sync. The direct analogue of
    ``packages/seed.py::example_dep_package_ids``.

    A dataset nothing declares stays out of every ``--with-examples`` /
    ``--deploy`` boot simply by not appearing in a lockfile; users add it from
    the Data Catalog drawer when they want it.
    """
    examples_dir = _examples_dir()
    dir_names: set[str] = set()
    if not examples_dir.is_dir():
        return ()
    for json_path in sorted(examples_dir.glob("*.json")):
        try:
            spec = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
        declared = dataflow.get("datasets") if isinstance(dataflow, dict) else None
        if not isinstance(declared, list):
            continue
        for ref in declared:
            if not isinstance(ref, dict):
                continue
            dir_name = ref.get("dirName")
            # Only folder-based refs can be provisioned from the committed
            # catalog. A legacy fat ref (no ``dirName``) describes a computed or
            # loose imported file that has no catalog directory to copy from.
            if isinstance(dir_name, str) and "@" in dir_name:
                dir_names.add(dir_name)
    return tuple(sorted(dir_names))


def seed_example_datasets(user_key: str) -> list[str]:
    """Copy every example-declared catalog dataset into *user_key*'s store.

    Returns the directory names actually copied (an already-complete install is
    skipped, so a steady-state boot returns ``[]``).

    Safe to call repeatedly and outside a request:
    ``install_dataset_from_catalog`` returns early when the destination's data
    file is already present, treats a partial copy as missing and starts fresh,
    and its dataset-index write goes through ``safe_upsert_from_dir``, a pure
    accelerator that never raises and that ``index.reconcile`` repairs anyway.

    One dataset failing must not cost the others: a missing or unreadable
    catalog directory is logged and skipped, exactly as the package seeder
    tolerates a fixture it cannot copy.
    """
    from utk_curio.backend.app.datasets.install.installer import (
        InstallerError,
        install_dataset_from_catalog,
    )

    seeded: list[str] = []
    for dir_name in example_dep_dataset_dirs():
        # Asked before the install so the return value distinguishes real work
        # from a no-op; the install itself is idempotent either way, so this only
        # decides what gets reported and logged.
        already_complete = _is_complete(user_key, dir_name)
        try:
            install_dataset_from_catalog(user_key, dir_name)
        except InstallerError:
            logger.warning(
                "Example dataset %s could not be provisioned for user_key=%s; "
                "it stays browsable from the hub but will not appear in the "
                "Data palette",
                dir_name,
                user_key,
                exc_info=True,
            )
            continue
        except Exception:  # noqa: BLE001 - seeding must never block startup
            logger.warning(
                "Unexpected failure provisioning example dataset %s for "
                "user_key=%s",
                dir_name,
                user_key,
                exc_info=True,
            )
            continue
        if not already_complete:
            seeded.append(dir_name)
    return seeded


def _is_complete(user_key: str, dir_name: str) -> bool:
    """Whether the store already holds a *usable* copy of this dataset.

    Deliberately the same rule ``install_dataset_from_catalog`` applies when it
    decides to skip: the data file must be present, not merely the manifest. A
    previous interrupted copy can leave the manifest behind with no bytes under
    it, and the installer repairs that - so checking only ``manifest.json``
    (as ``installer._is_installed`` does, for its own different purpose) would
    report the repair as a no-op.
    """
    from utk_curio.backend.app.datasets.domain.manifest import load_dataset_manifest
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir

    try:
        store = dataset_dir(user_key, dir_name)
        manifest = load_dataset_manifest(store)
    except Exception:  # noqa: BLE001 - unreadable means "not usable", i.e. redo it
        return False
    return (store / manifest.data_file).is_file()


def ensure_user_datasets_initialized(user_key: str) -> None:
    """Idempotently provision the example datasets for one user's store.

    The startup seeder only runs for the shared ``guest`` user, so the first
    time a real authenticated user opens a seeded example their dataset store is
    empty and the Data palette would show ``dirName``-titled placeholder rows
    with the wrong format chip. Call this at the project-entry boundaries
    (``save_project``, ``load_project``) so the store is populated by the time
    the canvas mounts - the same hook, for the same reason, as
    ``packages/services.py::ensure_user_packages_initialized``.
    """
    try:
        seeded = seed_example_datasets(user_key)
    except Exception:  # noqa: BLE001 - seeding must never block a project request
        logger.warning(
            "Example dataset seed failed for user_key=%s", user_key, exc_info=True
        )
        return
    if seeded:
        logger.info(
            "Provisioned %d example dataset(s) for user_key=%s: %s",
            len(seeded),
            user_key,
            ", ".join(seeded),
        )
