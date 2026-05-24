"""On-disk layout helpers for the per-user package store.

Layout (anchored on ``CURIO_LAUNCH_CWD``)::

    .curio/
      users/
        <user_key>/
          packages/
            <packageId>@<major>/
              manifest.json
              templates/<kindId>/*.py
              grammars/<kindId>/*.json
              widgets/<kindId>/*.json
              icons/<kindId>.svg
              README.md
              LICENSE

The package directory name is ``<packageId>@<major>``. Package ids follow
reverse-DNS conventions (``ai.urbanlab.uhvi``), so the directory segment
contains characters (``.``, ``@``) that the project-wide
``validate_component`` rejects. Package ids therefore have their own validator
(:data:`PACKAGE_DIR_RE`) and a small ``safe_join``-style helper that still
applies the final ``is_within`` containment check from
``utk_curio.backend.app.common.safe_paths``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from utk_curio.backend.app.common.safe_paths import (
    PathTraversalError,
    is_within,
    validate_component,
)


# A package directory looks like ``ai.urbanlab.uhvi@2``.
#
#   - <packageId>: reverse-DNS, lower-case, dot-separated, segments are
#     ``[a-z][a-z0-9-]{0,62}`` (must start with a letter, allow digits and
#     ``-``). Two or more segments required.
#   - ``@``    : literal separator.
#   - <major>  : non-negative integer.
PACKAGE_DIR_RE = re.compile(
    r"^[a-z][a-z0-9-]{0,62}(?:\.[a-z][a-z0-9-]{0,62}){1,5}@(?:0|[1-9][0-9]{0,3})$"
)

# A kind id (used as a *sub*-directory under ``templates/`` etc.) is more
# restrictive than the package id segment: lower-case, dash-separated.
KIND_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")


class PackageIdError(ValueError):
    """Raised when a package directory name or canonical id fails validation."""


@dataclass(frozen=True)
class PackageId:
    """A parsed package canonical identifier.

    Canonical form is ``<packageId>/<kindId>@<major>`` (e.g.
    ``ai.urbanlab.uhvi/uhvi-load@2``). The on-disk package directory uses just
    ``<packageId>@<major>``.
    """

    package_id: str
    major: int
    kind_id: str | None = None

    @classmethod
    def parse_dir(cls, dir_name: str) -> "PackageId":
        """Parse ``<packageId>@<major>`` (the on-disk directory segment)."""
        if not isinstance(dir_name, str) or not PACKAGE_DIR_RE.match(dir_name):
            raise PackageIdError(
                f"invalid package directory name: {dir_name!r}; expected "
                f"'<packageId>@<major>' matching {PACKAGE_DIR_RE.pattern}"
            )
        package_id, major_str = dir_name.rsplit("@", 1)
        return cls(package_id=package_id, major=int(major_str))

    @classmethod
    def parse_canonical(cls, canonical: str) -> "PackageId":
        """Parse ``<packageId>/<kindId>@<major>``."""
        if not isinstance(canonical, str) or "/" not in canonical or "@" not in canonical:
            raise PackageIdError(
                f"invalid canonical package id: {canonical!r}; expected "
                f"'<packageId>/<kindId>@<major>'"
            )
        head, major_str = canonical.rsplit("@", 1)
        if "/" not in head:
            raise PackageIdError(f"missing '/' in canonical id: {canonical!r}")
        package_id, kind_id = head.split("/", 1)
        if not PACKAGE_DIR_RE.match(f"{package_id}@0"):
            raise PackageIdError(f"invalid package id segment: {package_id!r}")
        if not KIND_ID_RE.match(kind_id):
            raise PackageIdError(f"invalid kind id segment: {kind_id!r}")
        try:
            major = int(major_str)
        except ValueError as exc:
            raise PackageIdError(f"invalid major version: {major_str!r}") from exc
        return cls(package_id=package_id, major=major, kind_id=kind_id)

    @property
    def dir_name(self) -> str:
        return f"{self.package_id}@{self.major}"

    def canonical(self, kind_id: str | None = None) -> str:
        k = kind_id or self.kind_id
        if not k:
            raise PackageIdError("canonical() requires a kind_id")
        return f"{self.package_id}/{k}@{self.major}"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _launch_dir() -> Path:
    return Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd()))


def _users_base() -> Path:
    return (_launch_dir() / ".curio" / "users").resolve()


_GUEST_KEY = "guest"


def _user_key_segment(user_key: str) -> str:
    if user_key == _GUEST_KEY or user_key.isdigit():
        return user_key
    raise ValueError(f"Invalid user key for storage: {user_key!r}")


def user_packageages_dir(user_key: str) -> Path:
    """Return ``.../users/<user_key>/packages/``.

    Does not require the directory to exist; callers that read are
    expected to handle the missing case (no packages installed yet).
    """
    return _users_base() / _user_key_segment(user_key) / "packages"


def user_packageage_staging_dir(user_key: str) -> Path:
    """Return ``.../users/<user_key>/.package-staging/``.

    Install transactions write into this sibling of ``packages/`` so the
    ``.py`` template files an in-flight install drops on disk never
    live inside the user's installed-package tree — the dev server's
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
    base = user_packageages_dir(user_key).resolve()
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
    reference assets inside their own directory** — exactly the
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


def list_user_packageages(user_key: str) -> list[Path]:
    """Return ``Path`` objects for every well-formed package dir for ``user_key``.

    Filters out any directory whose name does not match
    :data:`PACKAGE_DIR_RE`. Returns an empty list if the user has no package
    store yet.
    """
    base = user_packageages_dir(user_key)
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
