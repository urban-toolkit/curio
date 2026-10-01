"""The per-user package store on disk: ``.curio/users/<user_key>/packages/<packageId>@<major>/``. Path resolution with the project-wide containment check, and the raw store enumeration.

Repositories layer of the packages package (memo dev/143, B2): cut from ``storage.py``
by responsibility; every function keeps its name and body.
"""

from __future__ import annotations

from pathlib import Path

from utk_curio.backend.app.common.safe_paths import (
    is_within,
    PathTraversalError,
    validate_component,
)
from utk_curio.backend.app.common.user_storage import (
    user_key_segment as _user_key_segment,
    users_base as _users_base,
)
from utk_curio.backend.app.packages.domain.package_id import (
    PACKAGE_DIR_RE,
    PackageId,
)


def user_packages_dir(user_key: str) -> Path:
    """Return ``.../users/<user_key>/packages/``.

    Does not require the directory to exist; callers that read are
    expected to handle the missing case (no packages installed yet).
    """
    return _users_base() / _user_key_segment(user_key) / "packages"


def user_package_staging_dir(user_key: str) -> Path:
    """Return ``.../users/<user_key>/.package-staging/``.

    Install transactions write into this sibling of ``packages/`` so the
    ``.py`` template files an in-flight install drops on disk never
    live inside the user's installed-package tree - the dev server's
    watchdog reloader would otherwise fire on those writes and kill
    the install request mid-flight. The staging dir is on the same
    filesystem as ``packages/`` so :func:`os.replace` still works
    atomically when the installer hands the package over.
    """
    return _users_base() / _user_key_segment(user_key) / ".package-staging"


def package_dir(user_key: str, package_dir_name: str) -> Path:
    """Resolve a single ``<packageId>@<major>`` under a user's package store.

    Validates the directory name against :data:`PACKAGE_DIR_RE` and the
    project-wide containment check (``is_within``) before returning.
    """
    PackageId.parse_dir(package_dir_name)  # raises PackageIdError
    base = user_packages_dir(user_key).resolve()
    target = (base / package_dir_name).resolve()
    if not is_within(target, base):
        raise PathTraversalError(
            f"Path traversal blocked: package path {target!s} escapes base {base!s}"
        )
    return target


def package_asset_path(
    user_key: str,
    package_dir_name: str,
    *subpath: str,
    field: str = "package asset",
) -> Path:
    """Resolve ``<package_dir>/<subpath...>``, validating each segment.

    Each segment of ``subpath`` is validated with the project-wide
    :func:`validate_component`, which rejects ``..``, NUL bytes and any
    character outside ``[A-Za-z0-9._-]``. This means **packages can only
    reference assets inside their own directory** - exactly the
    self-containment invariant from the epic.
    """
    pdir = package_dir(user_key, package_dir_name).resolve()
    for seg in subpath:
        validate_component(seg, field=field)
    target = pdir.joinpath(*subpath).resolve()
    if not is_within(target, pdir):
        raise PathTraversalError(
            f"Path traversal blocked: {field} {target!s} escapes package {pdir!s}"
        )
    return target


def list_user_packages(user_key: str) -> list[Path]:
    """Return ``Path`` objects for every well-formed package dir for ``user_key``.

    Filters out any directory whose name does not match
    :data:`PACKAGE_DIR_RE`. Returns an empty list if the user has no package
    store yet.
    """
    base = user_packages_dir(user_key)
    if not base.is_dir():
        return []
    out: list[Path] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        if not PACKAGE_DIR_RE.match(entry.name):
            continue
        out.append(entry.resolve())
    return out
