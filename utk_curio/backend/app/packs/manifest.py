"""Minimal pack-manifest reader and validator.

Implements the supported subset described in ``docs/nodesfactory@docs/manifest_spec.md``
(normative schema), ``docs/nodesfactory@docs/overview.md``, and
``docs/nodesfactory@docs/backend.md`` (manifest loading), which is what the
palette, installer, and resolver consume today. Validation is intentionally
narrow — full ``$schema`` enforcement and richer semver stories are tracked in
``docs/nodesfactory@docs/warehouse_v2.md``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from utk_curio.backend.app.packs.pack_channel import normalize_distribution_channel
from utk_curio.backend.app.packs.storage import KIND_ID_RE, PACK_DIR_RE, PackId


class ManifestError(ValueError):
    """Raised when a pack manifest is malformed or violates the supported schema."""


@dataclass(frozen=True)
class PackLineageCoord:
    """A pack coordinate ``packId`` + ``major`` (same as on-disk directory semantics)."""

    pack_id: str
    major: int


@dataclass(frozen=True)
class PackLineage:
    """Fork provenance: immediate parent and stable family anchor."""

    forked_from: PackLineageCoord
    root: PackLineageCoord


def _parse_lineage_coord(raw: object, *, where: str) -> PackLineageCoord:
    if not isinstance(raw, dict):
        raise ManifestError(f"{where}: expected object, got {type(raw).__name__}")
    pack_id = raw.get("packId")
    major = raw.get("major")
    if not isinstance(pack_id, str):
        raise ManifestError(f"{where}.packId must be a string")
    if not isinstance(major, int) or major < 0:
        raise ManifestError(f"{where}.major must be a non-negative int")
    dir_name = f"{pack_id}@{major}"
    if not PACK_DIR_RE.match(dir_name):
        raise ManifestError(
            f"{where}: invalid coordinate {dir_name!r}; expected '<packId>@<major>' "
            f"matching pack directory rules"
        )
    return PackLineageCoord(pack_id=pack_id, major=major)


def _parse_lineage(
    raw_lineage: object,
    *,
    where_prefix: str,
    self_pack_id: str,
    self_major: int,
) -> PackLineage | None:
    if raw_lineage is None:
        return None
    if not isinstance(raw_lineage, dict):
        raise ManifestError(f"{where_prefix}.lineage must be an object")
    fork_raw = raw_lineage.get("forkedFrom")
    if fork_raw is None:
        raise ManifestError(f"{where_prefix}.lineage.forkedFrom is required")
    forked_from = _parse_lineage_coord(fork_raw, where=f"{where_prefix}.lineage.forkedFrom")
    root_raw = raw_lineage.get("root")
    if root_raw is None:
        root = forked_from
    else:
        root = _parse_lineage_coord(root_raw, where=f"{where_prefix}.lineage.root")

    self_coord = PackLineageCoord(pack_id=self_pack_id, major=self_major)
    if forked_from == self_coord:
        raise ManifestError(f"{where_prefix}.lineage.forkedFrom must differ from this pack")
    if root == self_coord:
        raise ManifestError(f"{where_prefix}.lineage.root must differ from this pack")

    return PackLineage(forked_from=forked_from, root=root)


def _parse_curio_palette_dock_hidden(raw: dict, *, where: str) -> bool:
    """Return whether ``curio.paletteDock.hiddenFromForkPaletteDock`` is true."""
    raw_curio = raw.get("curio")
    if raw_curio is None:
        return False
    if not isinstance(raw_curio, dict):
        raise ManifestError(f"{where}: curio must be an object")
    dock = raw_curio.get("paletteDock")
    if dock is None:
        return False
    if not isinstance(dock, dict):
        raise ManifestError(f"{where}: curio.paletteDock must be an object")
    hid = dock.get("hiddenFromForkPaletteDock")
    if hid is None:
        return False
    if hid is not True and hid is not False:
        raise ManifestError(f"{where}: curio.paletteDock.hiddenFromForkPaletteDock must be a boolean")
    return hid is True


@dataclass(frozen=True)
class PortDef:
    types: list[str]
    cardinality: str = "1"

    @classmethod
    def from_json(cls, raw: object, *, where: str) -> "PortDef":
        if not isinstance(raw, dict):
            raise ManifestError(f"{where}: expected object, got {type(raw).__name__}")
        types = raw.get("types")
        if not isinstance(types, list) or not all(isinstance(t, str) for t in types):
            raise ManifestError(f"{where}.types must be a list of strings")
        card = raw.get("cardinality", "1")
        if not isinstance(card, str):
            raise ManifestError(f"{where}.cardinality must be a string")
        return cls(types=list(types), cardinality=card)


@dataclass(frozen=True)
class NodeKindManifest:
    kind_id: str
    label: str
    category: str
    engine: str  # 'python' | 'javascript'
    description: str
    icon: str | None
    input_ports: list[PortDef]
    output_ports: list[PortDef]
    editor: str  # 'code' | 'widgets' | 'grammar' | 'none'
    has_code: bool
    has_widgets: bool
    has_grammar: bool
    template_dir: str | None  # relative to pack root, e.g. 'templates/uhvi-load'
    default_template: str | None  # path relative to pack root
    grammar_dir: str | None
    widget_dir: str | None

    @classmethod
    def from_json(cls, raw: object, *, where: str) -> "NodeKindManifest":
        if not isinstance(raw, dict):
            raise ManifestError(f"{where}: expected object")
        kind_id = raw.get("id")
        if not isinstance(kind_id, str) or not KIND_ID_RE.match(kind_id):
            raise ManifestError(
                f"{where}.id must match {KIND_ID_RE.pattern}, got {kind_id!r}"
            )
        engine = raw.get("engine", "python")
        if engine not in ("python", "javascript"):
            raise ManifestError(f"{where}.engine must be 'python' or 'javascript'")
        editor = raw.get("editor", "code")
        if editor not in ("code", "widgets", "grammar", "none"):
            raise ManifestError(f"{where}.editor must be one of code|widgets|grammar|none")
        in_ports_raw = raw.get("inputPorts", [])
        out_ports_raw = raw.get("outputPorts", [])
        if not isinstance(in_ports_raw, list) or not isinstance(out_ports_raw, list):
            raise ManifestError(f"{where}.inputPorts/outputPorts must be lists")
        return cls(
            kind_id=kind_id,
            label=str(raw.get("label", kind_id)),
            category=str(raw.get("category", "computation")),
            engine=engine,
            description=str(raw.get("description", "")),
            icon=raw.get("icon") if isinstance(raw.get("icon"), str) else None,
            input_ports=[PortDef.from_json(p, where=f"{where}.inputPorts[{i}]")
                         for i, p in enumerate(in_ports_raw)],
            output_ports=[PortDef.from_json(p, where=f"{where}.outputPorts[{i}]")
                          for i, p in enumerate(out_ports_raw)],
            editor=editor,
            has_code=bool(raw.get("hasCode", editor == "code")),
            has_widgets=bool(raw.get("hasWidgets", False)),
            has_grammar=bool(raw.get("hasGrammar", editor == "grammar")),
            template_dir=raw.get("templateDir") if isinstance(raw.get("templateDir"), str) else None,
            default_template=(
                raw.get("defaultTemplate") if isinstance(raw.get("defaultTemplate"), str) else None
            ),
            grammar_dir=raw.get("grammarDir") if isinstance(raw.get("grammarDir"), str) else None,
            widget_dir=raw.get("widgetDir") if isinstance(raw.get("widgetDir"), str) else None,
        )


@dataclass(frozen=True)
class PackManifest:
    pack_id: str
    major: int
    version: str
    name: str
    publisher: str
    description: str
    license: str | None
    kinds: list[NodeKindManifest] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    python_deps: dict[str, str] = field(default_factory=dict)
    js_deps: dict[str, str] = field(default_factory=dict)
    pack_deps: dict[str, str] = field(default_factory=dict)
    lineage: PackLineage | None = None
    channel: str = "stable"  # ``distribution.channel``; default stable — on catalog payloads
    hidden_from_fork_palette_dock: bool = False

    @property
    def dir_name(self) -> str:
        return f"{self.pack_id}@{self.major}"

    def canonical_for(self, kind_id: str) -> str:
        return f"{self.pack_id}/{kind_id}@{self.major}"


def load_pack_manifest(pack_dir_path: Path) -> PackManifest:
    """Read ``<pack_dir>/manifest.json`` and validate the supported subset.

    Cross-checks the directory name against the manifest's ``id`` and
    ``compatibility.major`` (the on-disk dir is authoritative for which
    pack is being loaded; the manifest must agree).
    """
    manifest_path = pack_dir_path / "manifest.json"
    if not manifest_path.is_file():
        raise ManifestError(f"missing manifest.json in {pack_dir_path}")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{manifest_path}: invalid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ManifestError(f"{manifest_path}: top-level must be an object")

    pack_id = raw.get("id")
    if not isinstance(pack_id, str) or not PACK_DIR_RE.match(f"{pack_id}@0"):
        raise ManifestError(f"{manifest_path}.id is missing or malformed")

    compatibility = raw.get("compatibility") or {}
    if not isinstance(compatibility, dict):
        raise ManifestError(f"{manifest_path}.compatibility must be an object")
    major = compatibility.get("major")
    if not isinstance(major, int) or major < 0:
        raise ManifestError(f"{manifest_path}.compatibility.major must be a non-negative int")

    expected_dir = f"{pack_id}@{major}"
    if pack_dir_path.name != expected_dir:
        raise ManifestError(
            f"directory name {pack_dir_path.name!r} does not match "
            f"manifest id/major {expected_dir!r}"
        )
    # Belt-and-braces — also confirm the dir name still parses cleanly.
    PackId.parse_dir(pack_dir_path.name)

    version = raw.get("version")
    if not isinstance(version, str) or not version:
        raise ManifestError(f"{manifest_path}.version must be a non-empty string")

    kinds_raw = raw.get("kinds") or []
    if not isinstance(kinds_raw, list) or not kinds_raw:
        raise ManifestError(f"{manifest_path}.kinds must be a non-empty list")
    kinds = [
        NodeKindManifest.from_json(k, where=f"{manifest_path}.kinds[{i}]")
        for i, k in enumerate(kinds_raw)
    ]

    deps = raw.get("dependencies") or {}
    if not isinstance(deps, dict):
        raise ManifestError(f"{manifest_path}.dependencies must be an object")
    python_deps = deps.get("python") or {}
    js_deps = deps.get("js") or {}
    pack_deps = deps.get("packs") or {}
    for label, val in (("python", python_deps), ("js", js_deps), ("packs", pack_deps)):
        if not isinstance(val, dict):
            raise ManifestError(f"{manifest_path}.dependencies.{label} must be an object")

    perms = raw.get("permissions") or []
    if not isinstance(perms, list) or not all(isinstance(p, str) for p in perms):
        raise ManifestError(f"{manifest_path}.permissions must be a list of strings")

    lineage = _parse_lineage(
        raw.get("lineage"),
        where_prefix=str(manifest_path),
        self_pack_id=pack_id,
        self_major=major,
    )

    hidden_from_fork = _parse_curio_palette_dock_hidden(raw, where=str(manifest_path))

    distribution = raw.get("distribution") or {}
    if not isinstance(distribution, dict):
        raise ManifestError(f"{manifest_path}.distribution must be an object")
    channel = normalize_distribution_channel(distribution.get("channel"))

    return PackManifest(
        pack_id=pack_id,
        major=major,
        version=version,
        name=str(raw.get("name", pack_id)),
        publisher=str(raw.get("publisher", "")),
        description=str(raw.get("description", "")),
        license=raw.get("license") if isinstance(raw.get("license"), str) else None,
        kinds=kinds,
        permissions=list(perms),
        python_deps=dict(python_deps),
        js_deps=dict(js_deps),
        pack_deps=dict(pack_deps),
        lineage=lineage,
        channel=channel,
        hidden_from_fork_palette_dock=hidden_from_fork,
    )
