"""Who published each package in the shared catalog.

The shared catalog under ``<repo_root>/packages/`` is a global tree, and until
now nothing recorded who put anything in it. Two consequences:

* ``DELETE /api/packages/catalog/<dir>`` was gated only by the deployment's
  ``CURIO_ALLOW_FACTORY_CATALOG_PUBLISH`` flag, so any authenticated user could
  unpublish any package, including the ones shipped with the deployment.
* The frontend had no way to tell a package the user authored from one that came
  with Curio, so "Unpublish" appeared on shipped packages. ``readOnly`` was the
  closest available signal and it does not mean this: it is an author's opt-in
  in the manifest, absent from almost every package, so ``readOnly !== true``
  matched nearly everything.

Datasets already solved this - ``CatalogMutations._assert_is_publisher`` reads
the publisher recorded in the published manifest - and agents carry a
``publishable`` flag the backend computes from provenance trust. This gives
packages the same thing.

Stored beside the published package as ``.curio-publisher.json``:
``{"version": 1, "userKey": "<user_key>"}``. A sidecar rather than a manifest
field because the manifest is the author's document, rebuilt verbatim from the
draft on every republish, and would drop anything written into it here.

Fail closed: a package with NO record is treated as not-yours. Everything
already in the catalog when this shipped is therefore unpublishable through the
API by a regular user, which is the correct answer for the packages that came
with the deployment.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

#: Catalog-side bookkeeping, not package content. Exported here because
#: ``installer.zip_package_tree`` has to leave it out of every archive it
#: builds, and a second spelling of the name would be a second thing to keep
#: in step.
RECORD_FILENAME = ".curio-publisher.json"
_FILENAME = RECORD_FILENAME
_SCHEMA_VERSION = 1


def _record_path(catalog_root: Path, dir_name: str) -> Path:
    return catalog_root / dir_name / _FILENAME


def record_publisher(catalog_root: Path, dir_name: str, user_key: str) -> None:
    """Note that *user_key* published *dir_name*. Best-effort.

    A failure here must not fail the publish: the package IS in the catalog at
    that point, and the worst case is that its author cannot unpublish it
    through the UI, which is the same position every pre-existing package is in.
    """
    try:
        path = _record_path(catalog_root, dir_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"version": _SCHEMA_VERSION, "userKey": str(user_key)}, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except OSError:
        log.warning("Could not record publisher for %s", dir_name, exc_info=True)


def publisher_of(catalog_root: Path, dir_name: str) -> str | None:
    """The user key that published *dir_name*, or ``None`` when unrecorded."""
    try:
        path = _record_path(catalog_root, dir_name)
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    user_key = raw.get("userKey")
    return user_key if isinstance(user_key, str) and user_key else None


def is_publisher(catalog_root: Path, dir_name: str, user_key: str) -> bool:
    """Whether *user_key* is the recorded publisher of *dir_name*.

    Fails closed on an unrecorded package - see the module docstring.
    """
    recorded = publisher_of(catalog_root, dir_name)
    return recorded is not None and recorded == str(user_key)


def forget_publisher(catalog_root: Path, dir_name: str) -> None:
    """Drop the record, for when the package leaves the catalog."""
    try:
        _record_path(catalog_root, dir_name).unlink(missing_ok=True)
    except OSError:
        pass
