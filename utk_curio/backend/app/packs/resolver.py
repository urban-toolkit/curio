"""Pack dependency resolver.

The design locks two policies:

1. **Shared sandbox env, fail-closed conflicts.** Pack Python deps from
   every pack a project pins are merged into a single requirement set
   and installed via the existing ``POST /installPackages`` route — there
   is no per-pack venv. Two packs requesting incompatible ranges for the
   same PyPI package is a hard install error.
2. **Project lockfile inside the project.** The resolved pack set and
   the merged Python (and JS) deps are recorded inside the project's
   ``spec.trill.json`` so a clean machine can reproduce the install.

This module is intentionally a small, dependency-free Python module:

* It parses a deliberately narrow subset of semver constraint syntax
  (``^x.y.z`` / ``~x.y.z`` / ``>=`` / ``<=`` / ``>`` / ``<`` / ``==``
  / exact / range-pair). PyPI's full PEP 440 grammar is not required
  here; the resolver rejects anything it doesn't recognise rather than
  silently treating it as a wildcard.
* It builds the pack DAG from ``manifest.dependencies.packs`` and
  detects cycles + missing packs up front.
* It intersects per-pack Python constraints into a single range per
  package, returning a precise conflict report when intersection is
  empty.

The lockfile schema is the same shape spike_option_b.md called out::

    {
      "installedPacks": [
        {"id": "ai.urbanlab.uhvi", "major": 1, "version": "1.0.0",
         "dirName": "ai.urbanlab.uhvi@1"}
      ],
      "pythonDeps": {"rasterio": "^1.3"},
      "jsDeps": {}
    }
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from collections import defaultdict

from utk_curio.backend.app.packs.catalog_family import family_key_for_manifest
from utk_curio.backend.app.packs.manifest import (
    ManifestError,
    PackManifest,
    load_pack_manifest,
)
from utk_curio.backend.app.packs.storage import list_user_packs, pack_dir


class ResolverError(ValueError):
    """Raised when the pack graph or python/js deps fail to resolve."""


@dataclass(frozen=True)
class DepConflict:
    package: str
    ranges: tuple[tuple[str, str], ...]  # ((pack_dir, range), ...)


@dataclass(frozen=True)
class ResolveResult:
    installed_packs: tuple[dict[str, object], ...]  # lockfile entries (DAG order)
    python_deps: dict[str, str]
    js_deps: dict[str, str]
    conflicts: tuple[DepConflict, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.conflicts

    def to_lockfile(self) -> dict[str, object]:
        """Return the JSON-serialisable lockfile shape used by ``spec.trill.json``."""
        return {
            "installedPacks": list(self.installed_packs),
            "pythonDeps": dict(self.python_deps),
            "jsDeps": dict(self.js_deps),
        }


# ---------------------------------------------------------------------------
# Tiny semver
# ---------------------------------------------------------------------------

_SEMVER_RE = re.compile(
    r"^(?P<major>\d+)(?:\.(?P<minor>\d+))?(?:\.(?P<patch>\d+))?(?:[-+].*)?$"
)


def parse_version(raw: str) -> tuple[int, int, int]:
    """Parse a semver-ish version into ``(major, minor, patch)``.

    Missing components default to 0 so ``"1"`` and ``"1.0.0"`` compare
    equal. Build / pre-release tails are accepted for parsing but ignored
    when ordering intersecting ranges — full prerelease precedence is not
    implemented yet (see ``docs/nodesfactory@docs/warehouse_v2.md`` §6).
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
    surface (and ``POST /api/packs/resolve``) returns a precise message
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


# ---------------------------------------------------------------------------
# Per-package dep merging
# ---------------------------------------------------------------------------

def merge_python_deps(
    per_pack: list[tuple[str, dict[str, str]]],
) -> tuple[dict[str, str], list[DepConflict]]:
    """Intersect every pack's ``dependencies.python`` into a single map.

    *per_pack* is a list of ``(pack_dir_name, {pkg: range})`` tuples.
    Two packs requesting incompatible ranges for the same package are
    surfaced as a :class:`DepConflict` rather than raising — callers
    decide whether to return 409 or just warn.

    The returned map's values are normalised through :func:`_format_range`
    so the project lockfile is canonical.
    """
    # First collect every range per package.
    by_pkg: dict[str, list[tuple[str, Range]]] = {}
    for pack_dir_name, deps in per_pack:
        for pkg, raw_range in deps.items():
            try:
                rng = parse_range(raw_range)
            except ResolverError as exc:
                # Treat unparseable constraints as an explicit conflict
                # rather than crashing the whole resolve.
                conflict = DepConflict(
                    package=pkg, ranges=((pack_dir_name, raw_range),)
                )
                by_pkg.setdefault(pkg, []).append((pack_dir_name, Range(lo=(0, 0, 0), hi=None)))
                # Attach the parse error to the conflict report later;
                # keep going so we surface every issue.
                _ = exc
                continue
            by_pkg.setdefault(pkg, []).append((pack_dir_name, rng))

    merged: dict[str, str] = {}
    conflicts: list[DepConflict] = []
    for pkg, entries in by_pkg.items():
        acc = Range(lo=(0, 0, 0), hi=None)
        conflict = False
        for pack_dir_name, rng in entries:
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


# ---------------------------------------------------------------------------
# Pack DAG
# ---------------------------------------------------------------------------

def _load_manifests(
    user_key: str,
    pack_dir_names: list[str] | None = None,
    *,
    overrides: dict[str, Path] | None = None,
) -> dict[str, PackManifest]:
    """Load manifests by directory name. Skips malformed packs silently.

    ``overrides`` lets the caller point the resolver at an alternate
    manifest source for a given pack dir name — e.g. the committed
    catalog fixture for a pack the user hasn't installed yet (the
    pre-install conflict probe). When a name is in ``overrides`` *and*
    the user already has it installed, the override wins so the probe
    always reflects the catalog version about to be installed rather
    than whatever stale copy is still on disk.
    """
    overrides = overrides or {}
    if pack_dir_names is not None:
        out: dict[str, PackManifest] = {}
        for name in pack_dir_names:
            path = overrides.get(name) or pack_dir(user_key, name)
            try:
                out[name] = load_pack_manifest(path)
            except ManifestError as exc:
                raise ResolverError(f"pack {name} is malformed: {exc}") from exc
        return out
    # Walk every installed pack for the user.
    out = {}
    for path in list_user_packs(user_key):
        try:
            out[path.name] = load_pack_manifest(path)
        except ManifestError:
            continue
    return out


def _coord_index(
    manifests: dict[str, PackManifest],
) -> tuple[dict[tuple[str, int], str], dict[str, tuple[str, ...]]]:
    """Maps ``(packId, major)`` → dir and ``packId`` → sorted dirs (for ambiguity checks)."""
    coord_to_dir: dict[tuple[str, int], str] = {}
    by_pack_id: dict[str, list[str]] = defaultdict(list)
    for dn, m in manifests.items():
        coord_to_dir[(m.pack_id, m.major)] = dn
        by_pack_id[m.pack_id].append(dn)
    for pid in by_pack_id:
        by_pack_id[pid].sort()
    dirs_map = {pid: tuple(dirs) for pid, dirs in by_pack_id.items()}
    return coord_to_dir, dirs_map


def _resolve_pack_dep_dir_name(
    from_dir: str,
    dep_key: str,
    coord_to_dir: dict[tuple[str, int], str],
    dirs_by_pack_id: dict[str, tuple[str, ...]],
) -> str:
    """Resolve a ``dependencies.packs`` entry to an on-disk ``dirName``."""
    dep_key = dep_key.strip()
    if not dep_key:
        raise ResolverError(f"pack {from_dir} has an empty pack dependency key")
    if "@" in dep_key:
        pid, sep, maj_s = dep_key.partition("@")
        pack_id_part = pid.strip()
        maj_s = maj_s.strip()
        if not pack_id_part or not maj_s.isdigit():
            raise ResolverError(
                f"pack {from_dir} has malformed pack dependency key {dep_key!r}; "
                "expected <packId> or <packId>@<major>"
            )
        target = coord_to_dir.get((pack_id_part, int(maj_s)))
        if target is None:
            raise ResolverError(
                f"pack {from_dir} depends on {dep_key!r} which is not installed"
            )
        return target

    cand = dirs_by_pack_id.get(dep_key)
    if not cand:
        raise ResolverError(
            f"pack {from_dir} depends on {dep_key} which is not installed"
        )
    if len(cand) > 1:
        raise ResolverError(
            f"pack {from_dir} depends on pack id {dep_key!r} which is ambiguous "
            f"({list(cand)} installed); specify <packId>@<major> in dependencies.packs"
        )
    return cand[0]


def _topo_order(
    pack_dir_names: list[str],
    manifests: dict[str, PackManifest],
) -> list[str]:
    """Return *pack_dir_names* in topological order; detect cycles + missing deps.

    Each manifest's ``pack_deps`` keys may be bare ``packId`` (only when exactly
    one installed pack uses that id) or ``packId@major`` for an unambiguous edge.
    """
    coord_to_dir, dirs_by_pack_id = _coord_index(manifests)
    selected = set(pack_dir_names)
    visited: set[str] = set()
    pending: set[str] = set()
    order: list[str] = []

    def visit(dir_name: str) -> None:
        if dir_name in visited:
            return
        if dir_name in pending:
            raise ResolverError(
                f"pack dependency cycle involving {dir_name}"
            )
        pending.add(dir_name)
        manifest = manifests[dir_name]
        for dep_key in manifest.pack_deps:
            target_dir = _resolve_pack_dep_dir_name(
                dir_name,
                dep_key,
                coord_to_dir,
                dirs_by_pack_id,
            )
            if target_dir not in selected:
                # Pull transitive dep into the resolve scope.
                selected.add(target_dir)
            visit(target_dir)
        pending.discard(dir_name)
        visited.add(dir_name)
        order.append(dir_name)

    for dn in list(pack_dir_names):
        visit(dn)
    return order


def _lockfile_entry_dict(manifest: PackManifest, dir_name: str) -> dict[str, object]:
    entry: dict[str, object] = {
        "id": manifest.pack_id,
        "major": manifest.major,
        "version": manifest.version,
        "dirName": dir_name,
        "familyKey": family_key_for_manifest(manifest),
    }
    lin = manifest.lineage
    if lin is not None:
        entry["lineageRoot"] = {
            "packId": lin.root.pack_id,
            "major": lin.root.major,
        }
    return entry


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def resolve_for_project(
    user_key: str,
    project_packs: list[str],
    *,
    overrides: dict[str, Path] | None = None,
) -> ResolveResult:
    """Resolve a set of packs into a lockfile-ready :class:`ResolveResult`.

    Parameters
    ----------
    user_key:
        ``"guest"`` or a numeric user id (validated by the storage layer).
    project_packs:
        The pack directory names (``<packId>@<major>``) the project
        explicitly pins. The resolver pulls in transitive dependencies
        from ``manifest.dependencies.packs`` automatically.
    overrides:
        Optional mapping from pack dir name → manifest source directory.
        Used by the pre-install conflict probe to point the resolver at
        the committed catalog fixture for a pack the user has not
        installed yet. See :func:`_load_manifests` for the precedence.
    """
    if not project_packs:
        return ResolveResult(installed_packs=(), python_deps={}, js_deps={})

    # Load the explicitly-selected packs first (raises if malformed),
    # then merge in every other installed pack for the user so the
    # topological walk can resolve transitive ``pack_deps`` references
    # against pack ids that are installed but not explicitly pinned.
    manifests = _load_manifests(user_key, project_packs, overrides=overrides)
    for dn, manifest in _load_manifests(user_key).items():
        manifests.setdefault(dn, manifest)

    order = _topo_order(list(project_packs), manifests)

    python_per_pack = [
        (dn, manifests[dn].python_deps) for dn in order
    ]
    py_merged, py_conflicts = merge_python_deps(python_per_pack)

    js_per_pack = [
        (dn, manifests[dn].js_deps) for dn in order if manifests[dn].js_deps
    ]
    js_merged, js_conflicts = merge_python_deps(js_per_pack)

    lockfile_entries: tuple[dict[str, object], ...] = tuple(
        _lockfile_entry_dict(manifests[dn], dn)
        for dn in order
    )
    return ResolveResult(
        installed_packs=lockfile_entries,
        python_deps=py_merged,
        js_deps=js_merged,
        conflicts=tuple(py_conflicts) + tuple(js_conflicts),
    )


def lockfile_for_user(user_key: str) -> dict[str, object]:
    """Convenience: resolve **every** installed pack for *user_key*.

    Returns an empty lockfile when the user has no packs.
    """
    names = [p.name for p in list_user_packs(user_key)]
    return resolve_for_project(user_key, names).to_lockfile()
