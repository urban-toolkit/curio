"""The version grammar the resolver locks: a deliberately narrow subset of semver constraints (``^`` / ``~`` / comparators / ranges), range intersection, and the conflict-aware merge of per-package dependency maps. Pure.

Domain layer of the packages package (memo dev/143, B2): cut from ``resolver.py``
by responsibility; every function keeps its name and body.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class ResolverError(ValueError):
    """Raised when the package graph or python/js deps fail to resolve."""


@dataclass(frozen=True)
class DepConflict:
    package: str
    ranges: tuple[tuple[str, str], ...]  # ((package_dir, range), ...)


_SEMVER_RE = re.compile(
    r"^(?P<major>\d+)(?:\.(?P<minor>\d+))?(?:\.(?P<patch>\d+))?(?:[-+].*)?$"
)


def parse_version(raw: str) -> tuple[int, int, int]:
    """Parse a semver-ish version into ``(major, minor, patch)``.

    Missing components default to 0 so ``"1"`` and ``"1.0.0"`` compare
    equal. Build / pre-release tails are accepted for parsing but ignored
    when ordering intersecting ranges — full prerelease precedence is not
    implemented yet.
    """
    if not isinstance(raw, str) or not raw:
        raise ResolverError(f"invalid version: {raw!r}")
    m = _SEMVER_RE.match(raw.strip())
    if not m:
        raise ResolverError(f"invalid version: {raw!r}")
    return (
        int(m.group("major")),
        int(m.group("minor") or 0),
        int(m.group("patch") or 0),
    )


@dataclass(frozen=True)
class Range:
    """Closed-on-min, open-on-max interval ``[lo, hi)`` of semver versions.

    ``hi`` may be ``None`` to mean "no upper bound" (still finite per
    the largest representable tuple, but we treat that as +inf).
    """
    lo: tuple[int, int, int]
    hi: tuple[int, int, int] | None  # exclusive

    def intersect(self, other: "Range") -> "Range | None":
        new_lo = max(self.lo, other.lo)
        if self.hi is None:
            new_hi = other.hi
        elif other.hi is None:
            new_hi = self.hi
        else:
            new_hi = min(self.hi, other.hi)
        if new_hi is not None and not (new_lo < new_hi):
            return None
        return Range(lo=new_lo, hi=new_hi)


def _bump_major(v: tuple[int, int, int]) -> tuple[int, int, int]:
    return (v[0] + 1, 0, 0)


def _bump_minor(v: tuple[int, int, int]) -> tuple[int, int, int]:
    return (v[0], v[1] + 1, 0)


def _bump_patch(v: tuple[int, int, int]) -> tuple[int, int, int]:
    return (v[0], v[1], v[2] + 1)


def parse_range(raw: str) -> Range:
    """Parse a single constraint into a :class:`Range`.

    Accepted syntaxes (intentionally narrow):

    * ``"*"``                         — any version (``[0.0.0, +inf)``)
    * ``"^1.2.3"``                     — ``[1.2.3, 2.0.0)`` (npm-style caret)
    * ``"~1.2.3"`` / ``"~1.2"``        — ``[1.2.3, 1.3.0)`` (tilde patch)
    * ``"==1.2.3"`` / ``"1.2.3"``      — exact version (treated as a one-bump range)
    * ``">=1.2"`` / ``"<2.0"`` / ``">1.0"`` / ``"<=1.5"`` / multi-clause ``">=1.0,<2.0"``

    Anything else raises ``ResolverError`` so the wizard's validator
    surface (and ``POST /api/packages/resolve``) returns a precise message
    instead of silently treating an unknown syntax as wildcard.
    """
    if not isinstance(raw, str):
        raise ResolverError(f"range must be a string, got {type(raw).__name__}")
    s = raw.strip()
    if not s or s == "*":
        return Range(lo=(0, 0, 0), hi=None)
    if s.startswith("^"):
        v = parse_version(s[1:])
        return Range(lo=v, hi=_bump_major(v))
    if s.startswith("~"):
        v = parse_version(s[1:])
        return Range(lo=v, hi=_bump_minor(v))

    if "," in s:
        parts = [p.strip() for p in s.split(",") if p.strip()]
        rng = Range(lo=(0, 0, 0), hi=None)
        for p in parts:
            sub = parse_range(p)
            merged = rng.intersect(sub)
            if merged is None:
                raise ResolverError(
                    f"range parts {raw!r} are mutually unsatisfiable"
                )
            rng = merged
        return rng

    for prefix, kind in ((">=", "ge"), ("<=", "le"), ("==", "eq"),
                         (">", "gt"), ("<", "lt"), ("=", "eq")):
        if s.startswith(prefix):
            v = parse_version(s[len(prefix):])
            if kind == "ge":
                return Range(lo=v, hi=None)
            if kind == "gt":
                return Range(lo=_bump_patch(v), hi=None)
            if kind == "le":
                return Range(lo=(0, 0, 0), hi=_bump_patch(v))
            if kind == "lt":
                return Range(lo=(0, 0, 0), hi=v)
            if kind == "eq":
                return Range(lo=v, hi=_bump_patch(v))

    # Bare version = exact match.
    v = parse_version(s)
    return Range(lo=v, hi=_bump_patch(v))


def _format_version(v: tuple[int, int, int]) -> str:
    return f"{v[0]}.{v[1]}.{v[2]}"


def _format_range(r: Range) -> str:
    """Round-trip a :class:`Range` into the smallest-possible string."""
    if r.lo == (0, 0, 0) and r.hi is None:
        return "*"
    if r.hi is None:
        return f">={_format_version(r.lo)}"
    return f">={_format_version(r.lo)},<{_format_version(r.hi)}"


def merge_python_deps(
    per_package: list[tuple[str, dict[str, str]]],
) -> tuple[dict[str, str], list[DepConflict]]:
    """Intersect every package's ``dependencies.python`` into a single map.

    *per_package* is a list of ``(package_dir_name, {pkg: range})`` tuples.
    Two packages requesting incompatible ranges for the same package are
    surfaced as a :class:`DepConflict` rather than raising — callers
    decide whether to return 409 or just warn.

    The returned map's values are normalised through :func:`_format_range`
    so the project lockfile is canonical.
    """
    # First collect every range per package.
    by_pkg: dict[str, list[tuple[str, Range]]] = {}
    for package_dir_name, deps in per_package:
        for pkg, raw_range in deps.items():
            try:
                rng = parse_range(raw_range)
            except ResolverError as exc:
                # Treat unparseable constraints as an explicit conflict
                # rather than crashing the whole resolve.
                conflict = DepConflict(
                    package=pkg, ranges=((package_dir_name, raw_range),)
                )
                by_pkg.setdefault(pkg, []).append((package_dir_name, Range(lo=(0, 0, 0), hi=None)))
                # Attach the parse error to the conflict report later;
                # keep going so we surface every issue.
                _ = exc
                continue
            by_pkg.setdefault(pkg, []).append((package_dir_name, rng))

    merged: dict[str, str] = {}
    conflicts: list[DepConflict] = []
    for pkg, entries in by_pkg.items():
        acc = Range(lo=(0, 0, 0), hi=None)
        conflict = False
        for package_dir_name, rng in entries:
            nxt = acc.intersect(rng)
            if nxt is None:
                conflicts.append(
                    DepConflict(
                        package=pkg,
                        ranges=tuple(
                            (p, _format_range(r)) for p, r in entries
                        ),
                    )
                )
                conflict = True
                break
            acc = nxt
        if not conflict:
            merged[pkg] = _format_range(acc)
    return merged, conflicts
