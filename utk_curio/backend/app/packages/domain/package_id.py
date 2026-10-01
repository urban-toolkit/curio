"""Package identity: the ``<packageId>@<major>`` directory grammar, the template-id grammar, and the parsed canonical id. Pure.

Domain layer of the packages package (memo dev/143, B2): cut from ``storage.py``
by responsibility; every function keeps its name and body.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# A package directory looks like ``ai.utk.uhvi@2``.
#
#   - <packageId>: reverse-DNS, lower-case, dot-separated, segments are
#     ``[a-z][a-z0-9-]{0,62}`` (must start with a letter, allow digits and
#     ``-``). Two or more segments required.
#   - ``@``    : literal separator.
#   - <major>  : non-negative integer.
PACKAGE_DIR_RE = re.compile(
    r"^[a-z][a-z0-9-]{0,62}(?:\.[a-z][a-z0-9-]{0,62}){1,5}@(?:0|[1-9][0-9]{0,3})$"
)


# A template id (used as a *sub*-directory under ``starters/`` etc.) is more
# restrictive than the package id segment: lower-case, dash-separated.
TEMPLATE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")

#: The package every store is seeded with and no route may uninstall (memo dev/143 B4:
#: moved here from the seeder so the store install use cases can name it without a cycle).
BUILTIN_PACKAGE_ID = "curio.builtin"


class PackageIdError(ValueError):
    """Raised when a package directory name or canonical id fails validation."""


@dataclass(frozen=True)
class PackageId:
    """A parsed package canonical identifier.

    Canonical form is ``<packageId>/<templateId>@<major>`` (e.g.
    ``ai.utk.uhvi/uhvi-load@2``). The on-disk package directory uses just
    ``<packageId>@<major>``.
    """

    package_id: str
    major: int
    template_id: str | None = None

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
        """Parse ``<packageId>/<templateId>@<major>``."""
        if not isinstance(canonical, str) or "/" not in canonical or "@" not in canonical:
            raise PackageIdError(
                f"invalid canonical package id: {canonical!r}; expected "
                f"'<packageId>/<templateId>@<major>'"
            )
        head, major_str = canonical.rsplit("@", 1)
        if "/" not in head:
            raise PackageIdError(f"missing '/' in canonical id: {canonical!r}")
        package_id, template_id = head.split("/", 1)
        if not PACKAGE_DIR_RE.match(f"{package_id}@0"):
            raise PackageIdError(f"invalid package id segment: {package_id!r}")
        if not TEMPLATE_ID_RE.match(template_id):
            raise PackageIdError(f"invalid template id segment: {template_id!r}")
        try:
            major = int(major_str)
        except ValueError as exc:
            raise PackageIdError(f"invalid major version: {major_str!r}") from exc
        return cls(package_id=package_id, major=major, template_id=template_id)

    @property
    def dir_name(self) -> str:
        return f"{self.package_id}@{self.major}"

    def canonical(self, template_id: str | None = None) -> str:
        k = template_id or self.template_id
        if not k:
            raise PackageIdError("canonical() requires a template_id")
        return f"{self.package_id}/{k}@{self.major}"
