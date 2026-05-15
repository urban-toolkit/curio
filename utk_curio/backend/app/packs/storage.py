"""On-disk layout helpers for the per-user pack store.

Layout (anchored on ``CURIO_LAUNCH_CWD``)::

    .curio/
      users/
        <user_key>/
          packs/
            <packId>@<major>/
              manifest.json
              templates/<kindId>/*.py
              grammars/<kindId>/*.json
              widgets/<kindId>/*.json
              icons/<kindId>.svg
              README.md
              LICENSE

The pack directory name is ``<packId>@<major>``. Pack ids follow
reverse-DNS conventions (``ai.urbanlab.uhvi``), so the directory segment
contains characters (``.``, ``@``) that the project-wide
``validate_component`` rejects. Pack ids therefore have their own validator
(:data:`PACK_DIR_RE`) and a small ``safe_join``-style helper that still
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


# A pack directory looks like ``ai.urbanlab.uhvi@2``.
#
#   - <packId>: reverse-DNS, lower-case, dot-separated, segments are
#     ``[a-z][a-z0-9-]{0,62}`` (must start with a letter, allow digits and
#     ``-``). Two or more segments required.
#   - ``@``    : literal separator.
#   - <major>  : non-negative integer.
PACK_DIR_RE = re.compile(
    r"^[a-z][a-z0-9-]{0,62}(?:\.[a-z][a-z0-9-]{0,62}){1,5}@(?:0|[1-9][0-9]{0,3})$"
)

# A kind id (used as a *sub*-directory under ``templates/`` etc.) is more
# restrictive than the pack id segment: lower-case, dash-separated.
KIND_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")


class PackIdError(ValueError):
    """Raised when a pack directory name or canonical id fails validation."""


@dataclass(frozen=True)
class PackId:
    """A parsed pack canonical identifier.

    Canonical form is ``<packId>/<kindId>@<major>`` (e.g.
    ``ai.urbanlab.uhvi/uhvi-load@2``). The on-disk pack directory uses just
    ``<packId>@<major>``.
    """

    pack_id: str
    major: int
    kind_id: str | None = None

    @classmethod
    def parse_dir(cls, dir_name: str) -> "PackId":
        """Parse ``<packId>@<major>`` (the on-disk directory segment)."""
        if not isinstance(dir_name, str) or not PACK_DIR_RE.match(dir_name):
            raise PackIdError(
                f"invalid pack directory name: {dir_name!r}; expected "
                f"'<packId>@<major>' matching {PACK_DIR_RE.pattern}"
            )
        pack_id, major_str = dir_name.rsplit("@", 1)
        return cls(pack_id=pack_id, major=int(major_str))

    @classmethod
    def parse_canonical(cls, canonical: str) -> "PackId":
        """Parse ``<packId>/<kindId>@<major>``."""
        if not isinstance(canonical, str) or "/" not in canonical or "@" not in canonical:
            raise PackIdError(
                f"invalid canonical pack id: {canonical!r}; expected "
                f"'<packId>/<kindId>@<major>'"
            )
        head, major_str = canonical.rsplit("@", 1)
        if "/" not in head:
            raise PackIdError(f"missing '/' in canonical id: {canonical!r}")
        pack_id, kind_id = head.split("/", 1)
        if not PACK_DIR_RE.match(f"{pack_id}@0"):
            raise PackIdError(f"invalid pack id segment: {pack_id!r}")
        if not KIND_ID_RE.match(kind_id):
            raise PackIdError(f"invalid kind id segment: {kind_id!r}")
        try:
            major = int(major_str)
        except ValueError as exc:
            raise PackIdError(f"invalid major version: {major_str!r}") from exc
        return cls(pack_id=pack_id, major=major, kind_id=kind_id)

    @property
    def dir_name(self) -> str:
        return f"{self.pack_id}@{self.major}"

    def canonical(self, kind_id: str | None = None) -> str:
        k = kind_id or self.kind_id
        if not k:
            raise PackIdError("canonical() requires a kind_id")
        return f"{self.pack_id}/{k}@{self.major}"


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


def user_packs_dir(user_key: str) -> Path:
    """Return ``.../users/<user_key>/packs/``.

    Does not require the directory to exist; callers that read are
    expected to handle the missing case (no packs installed yet).
    """
    return _users_base() / _user_key_segment(user_key) / "packs"


def user_pack_staging_dir(user_key: str) -> Path:
    """Return ``.../users/<user_key>/.pack-staging/``.

    Install transactions write into this sibling of ``packs/`` so the
    ``.py`` template files an in-flight install drops on disk never
    live inside the user's installed-pack tree — the dev server's
    watchdog reloader would otherwise fire on those writes and kill
    the install request mid-flight. The staging dir is on the same
    filesystem as ``packs/`` so :func:`os.replace` still works
    atomically when the installer hands the pack over.
    """
    return _users_base() / _user_key_segment(user_key) / ".pack-staging"


def pack_dir(user_key: str, pack_dir_name: str) -> Path:
    """Resolve a single ``<packId>@<major>`` under a user's pack store.

    Validates the directory name against :data:`PACK_DIR_RE` and the
    project-wide containment check (``is_within``) before returning.
    """
    PackId.parse_dir(pack_dir_name)  # raises PackIdError
    base = user_packs_dir(user_key).resolve()
    target = (base / pack_dir_name).resolve()
    if not is_within(target, base):
        raise PathTraversalError(
            f"Path traversal blocked: pack path {target!s} escapes base {base!s}"
        )
    return target


def pack_asset_path(
    user_key: str,
    pack_dir_name: str,
    *subpath: str,
    field: str = "pack asset",
) -> Path:
    """Resolve ``<pack_dir>/<subpath...>``, validating each segment.

    Each segment of ``subpath`` is validated with the project-wide
    :func:`validate_component`, which rejects ``..``, NUL bytes and any
    character outside ``[A-Za-z0-9._-]``. This means **packs can only
    reference assets inside their own directory** — exactly the
    self-containment invariant from the epic.
    """
    pdir = pack_dir(user_key, pack_dir_name).resolve()
    for seg in subpath:
        validate_component(seg, field=field)
    target = pdir.joinpath(*subpath).resolve()
    if not is_within(target, pdir):
        raise PathTraversalError(
            f"Path traversal blocked: {field} {target!s} escapes pack {pdir!s}"
        )
    return target


def list_user_packs(user_key: str) -> list[Path]:
    """Return ``Path`` objects for every well-formed pack dir for ``user_key``.

    Filters out any directory whose name does not match
    :data:`PACK_DIR_RE`. Returns an empty list if the user has no pack
    store yet.
    """
    base = user_packs_dir(user_key)
    if not base.is_dir():
        return []
    out: list[Path] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        if not PACK_DIR_RE.match(entry.name):
            continue
        out.append(entry.resolve())
    return out
