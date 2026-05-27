"""Package-manifest reader and validator.

Implements the supported subset of the v2 manifest schema (canonical
spec: ``docs/schemas/node-package.v3.json``). This is what the palette,
installer, and resolver consume.

User-facing overview: ``docs/CATALOG.md``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from utk_curio.backend.app.packages.package_channel import normalize_distribution_channel
from utk_curio.backend.app.packages.storage import TEMPLATE_ID_RE, PACKAGE_DIR_RE, PackageId


class ManifestError(ValueError):
    """Raised when a package manifest is malformed or violates the supported schema."""


def _parse_created_at_from_manifest(raw: object, *, where: str) -> tuple[str | None, int]:
    """Parse optional top-level ``createdAt`` ISO 8601 instant.

    Returns ``(canonical_iso_with_Z, epoch_ms)`` or ``(None, 0)`` when omitted/blank.
    Naive timestamps are interpreted as UTC.
    """
    if raw is None:
        return None, 0
    if isinstance(raw, (int, float, bool)):
        raise ManifestError(
            f"{where}.createdAt must be an ISO 8601 instant string when present "
            f"(got {type(raw).__name__})"
        )
    if not isinstance(raw, str):
        raise ManifestError(f"{where}.createdAt must be a string ISO 8601 instant")
    s = raw.strip()
    if not s:
        return None, 0

    iso_in = s
    try:
        if iso_in.endswith("Z") or iso_in.endswith("z"):
            base = iso_in[:-1]
            dt = datetime.fromisoformat(base).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(iso_in)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
    except ValueError as exc:
        raise ManifestError(f"{where}.createdAt is not valid ISO 8601: {s!r}") from exc

    utc = dt
    frac = utc.microsecond
    canon_body = utc.strftime("%Y-%m-%dT%H:%M:%S")
    if frac:
        canon_body += "." + f"{frac:06d}".rstrip("0")
    canon = canon_body + "Z"
    return canon, int(utc.timestamp() * 1000)


@dataclass(frozen=True)
class PackageLineageCoord:
    """A package coordinate ``packageId`` + ``major`` (same as on-disk directory semantics)."""

    package_id: str
    major: int


@dataclass(frozen=True)
class PackageLineage:
    """Fork provenance: immediate parent and stable family anchor."""

    forked_from: PackageLineageCoord
    root: PackageLineageCoord


def _parse_lineage_coord(raw: object, *, where: str) -> PackageLineageCoord:
    if not isinstance(raw, dict):
        raise ManifestError(f"{where}: expected object, got {type(raw).__name__}")
    package_id = raw.get("packageId")
    major = raw.get("major")
    if not isinstance(package_id, str):
        raise ManifestError(f"{where}.packageId must be a string")
    if not isinstance(major, int) or major < 0:
        raise ManifestError(f"{where}.major must be a non-negative int")
    dir_name = f"{package_id}@{major}"
    if not PACKAGE_DIR_RE.match(dir_name):
        raise ManifestError(
            f"{where}: invalid coordinate {dir_name!r}; expected '<packageId>@<major>' "
            f"matching package directory rules"
        )
    return PackageLineageCoord(package_id=package_id, major=major)


def _parse_lineage(
    raw_lineage: object,
    *,
    where_prefix: str,
    self_packageage_id: str,
    self_major: int,
) -> PackageLineage | None:
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

    self_coord = PackageLineageCoord(package_id=self_packageage_id, major=self_major)
    if forked_from == self_coord:
        raise ManifestError(f"{where_prefix}.lineage.forkedFrom must differ from this package")
    if root == self_coord:
        raise ManifestError(f"{where_prefix}.lineage.root must differ from this package")

    return PackageLineage(forked_from=forked_from, root=root)


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
class TemplateManifest:
    template_id: str
    label: str
    category: str
    engine: str  # 'python' | 'javascript'
    description: str
    icon: str | None  # legacy free-form icon string (rare; iconRef preferred)
    icon_ref: str | None  # "<source>:<icon-id>" key for the frontend iconRegistry
    lifecycle: str | None  # key into the frontend lifecycleRegistry (e.g. "code", "vega")
    palette_order: int | None
    input_ports: list[PortDef]
    output_ports: list[PortDef]
    editor: str  # 'code' | 'widgets' | 'grammar' | 'none'
    has_code: bool
    has_widgets: bool
    has_grammar: bool
    grammar_id: str | None  # grammar adapter key (e.g. "vega-lite") when editor=="grammar"
    badge: str | None  # palette card badge label (e.g. "VEGA", "AUTK", "PACKAGE")
    source: str | None  # package-relative path to one optional starter file
    bidirectional: bool  # adds the third "in/out" handle for interaction-loop templates
    container_style: dict | None  # {"nodeWidth": int?, "nodeHeight": int?, "noContent": bool?, "disablePlay": bool?}
    has_provenance: bool | None  # explicit override for the provenance editor tab (defaults to true client-side)
    tutorial_id: str | None  # anchor id for the in-app tutorial system
    grammar_dir: str | None
    widget_dir: str | None

    @classmethod
    def from_json(cls, raw: object, *, where: str) -> "TemplateManifest":
        if not isinstance(raw, dict):
            raise ManifestError(f"{where}: expected object")
        template_id = raw.get("id")
        if not isinstance(template_id, str) or not TEMPLATE_ID_RE.match(template_id):
            raise ManifestError(
                f"{where}.id must match {TEMPLATE_ID_RE.pattern}, got {template_id!r}"
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
        lifecycle_raw = raw.get("lifecycle")
        if lifecycle_raw is not None and not (isinstance(lifecycle_raw, str) and lifecycle_raw):
            raise ManifestError(f"{where}.lifecycle must be a non-empty string when present")
        palette_order_raw = raw.get("paletteOrder")
        if palette_order_raw is not None and not isinstance(palette_order_raw, int):
            raise ManifestError(f"{where}.paletteOrder must be an integer when present")
        container_style_raw = raw.get("containerStyle")
        if container_style_raw is not None and not isinstance(container_style_raw, dict):
            raise ManifestError(f"{where}.containerStyle must be an object when present")
        has_provenance_raw = raw.get("hasProvenance")
        if has_provenance_raw is not None and not isinstance(has_provenance_raw, bool):
            raise ManifestError(f"{where}.hasProvenance must be a boolean when present")
        return cls(
            template_id=template_id,
            label=str(raw.get("label", template_id)),
            category=str(raw.get("category", "computation")),
            engine=engine,
            description=str(raw.get("description", "")),
            icon=raw.get("icon") if isinstance(raw.get("icon"), str) else None,
            icon_ref=raw.get("iconRef") if isinstance(raw.get("iconRef"), str) else None,
            lifecycle=lifecycle_raw,
            palette_order=palette_order_raw,
            input_ports=[PortDef.from_json(p, where=f"{where}.inputPorts[{i}]")
                         for i, p in enumerate(in_ports_raw)],
            output_ports=[PortDef.from_json(p, where=f"{where}.outputPorts[{i}]")
                          for i, p in enumerate(out_ports_raw)],
            editor=editor,
            has_code=bool(raw.get("hasCode", editor == "code")),
            has_widgets=bool(raw.get("hasWidgets", False)),
            has_grammar=bool(raw.get("hasGrammar", editor == "grammar")),
            grammar_id=raw.get("grammarId") if isinstance(raw.get("grammarId"), str) else None,
            badge=raw.get("badge") if isinstance(raw.get("badge"), str) else None,
            source=raw.get("source") if isinstance(raw.get("source"), str) else None,
            bidirectional=bool(raw.get("bidirectional", False)),
            container_style=container_style_raw,
            has_provenance=has_provenance_raw,
            tutorial_id=raw.get("tutorialId") if isinstance(raw.get("tutorialId"), str) else None,
            grammar_dir=raw.get("grammarDir") if isinstance(raw.get("grammarDir"), str) else None,
            widget_dir=raw.get("widgetDir") if isinstance(raw.get("widgetDir"), str) else None,
        )


@dataclass(frozen=True)
class PackageManifest:
    package_id: str
    major: int
    version: str
    name: str
    publisher: str
    description: str
    license: str | None
    templates: list[TemplateManifest] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    python_deps: dict[str, str] = field(default_factory=dict)
    js_deps: dict[str, str] = field(default_factory=dict)
    package_deps: dict[str, str] = field(default_factory=dict)
    lineage: PackageLineage | None = None
    channel: str = "stable"  # ``distribution.channel``; default stable — on catalog payloads
    read_only: bool = False
    created_at_iso: str | None = None
    created_at_ms: int = 0
    # Optional path (relative to package dir) of a pre-built JS bundle that
    # registers this package's lifecycle hooks against `window.curio` at
    # load time. When set, the frontend injects a <script src=...> for it
    # before building descriptors. See docs/EXTENDING.md §5 for the
    # contract package authors follow.
    lifecycle_script: str | None = None

    @property
    def dir_name(self) -> str:
        return f"{self.package_id}@{self.major}"

    def canonical_for(self, template_id: str) -> str:
        return f"{self.package_id}/{template_id}@{self.major}"


def load_packageage_manifest(package_dir_path: Path) -> PackageManifest:
    """Read ``<package_dir>/manifest.json`` and validate the supported subset.

    Cross-checks the directory name against the manifest's ``id`` and
    ``compatibility.major`` (the on-disk dir is authoritative for which
    package is being loaded; the manifest must agree).
    """
    manifest_path = package_dir_path / "manifest.json"
    if not manifest_path.is_file():
        raise ManifestError(f"missing manifest.json in {package_dir_path}")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{manifest_path}: invalid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ManifestError(f"{manifest_path}: top-level must be an object")

    package_id = raw.get("id")
    if not isinstance(package_id, str) or not PACKAGE_DIR_RE.match(f"{package_id}@0"):
        raise ManifestError(f"{manifest_path}.id is missing or malformed")

    compatibility = raw.get("compatibility") or {}
    if not isinstance(compatibility, dict):
        raise ManifestError(f"{manifest_path}.compatibility must be an object")
    major = compatibility.get("major")
    if not isinstance(major, int) or major < 0:
        raise ManifestError(f"{manifest_path}.compatibility.major must be a non-negative int")

    expected_dir = f"{package_id}@{major}"
    if package_dir_path.name != expected_dir:
        raise ManifestError(
            f"directory name {package_dir_path.name!r} does not match "
            f"manifest id/major {expected_dir!r}"
        )
    # Belt-and-braces — also confirm the dir name still parses cleanly.
    PackageId.parse_dir(package_dir_path.name)

    version = raw.get("version")
    if not isinstance(version, str) or not version:
        raise ManifestError(f"{manifest_path}.version must be a non-empty string")

    templates_raw = raw.get("templates") or []
    if not isinstance(templates_raw, list) or not templates_raw:
        raise ManifestError(f"{manifest_path}.templates must be a non-empty list")
    templates = [
        TemplateManifest.from_json(t, where=f"{manifest_path}.templates[{i}]")
        for i, t in enumerate(templates_raw)
    ]

    deps = raw.get("dependencies") or {}
    if not isinstance(deps, dict):
        raise ManifestError(f"{manifest_path}.dependencies must be an object")
    python_deps = deps.get("python") or {}
    js_deps = deps.get("js") or {}
    package_deps = deps.get("packages") or {}
    for label, val in (("python", python_deps), ("js", js_deps), ("packages", package_deps)):
        if not isinstance(val, dict):
            raise ManifestError(f"{manifest_path}.dependencies.{label} must be an object")

    perms = raw.get("permissions") or []
    if not isinstance(perms, list) or not all(isinstance(p, str) for p in perms):
        raise ManifestError(f"{manifest_path}.permissions must be a list of strings")

    lineage = _parse_lineage(
        raw.get("lineage"),
        where_prefix=str(manifest_path),
        self_packageage_id=package_id,
        self_major=major,
    )

    read_only_raw = raw.get("readOnly")
    if read_only_raw is not None and not isinstance(read_only_raw, bool):
        raise ManifestError(f"{manifest_path}.readOnly must be a boolean")
    read_only = bool(read_only_raw)

    distribution = raw.get("distribution") or {}
    if not isinstance(distribution, dict):
        raise ManifestError(f"{manifest_path}.distribution must be an object")
    channel = normalize_distribution_channel(distribution.get("channel"))

    created_at_iso, created_at_ms = _parse_created_at_from_manifest(
        raw.get("createdAt"), where=f"{manifest_path}"
    )

    lifecycle_script_raw = raw.get("lifecycleScript")
    if lifecycle_script_raw is not None and not isinstance(lifecycle_script_raw, str):
        raise ManifestError(f"{manifest_path}.lifecycleScript must be a string when present")
    lifecycle_script = (
        lifecycle_script_raw.strip() if isinstance(lifecycle_script_raw, str) else None
    ) or None

    return PackageManifest(
        package_id=package_id,
        major=major,
        version=version,
        name=str(raw.get("name", package_id)),
        publisher=str(raw.get("publisher", "")),
        description=str(raw.get("description", "")),
        license=raw.get("license") if isinstance(raw.get("license"), str) else None,
        templates=templates,
        permissions=list(perms),
        python_deps=dict(python_deps),
        js_deps=dict(js_deps),
        package_deps=dict(package_deps),
        lineage=lineage,
        channel=channel,
        read_only=read_only,
        created_at_iso=created_at_iso,
        created_at_ms=created_at_ms,
        lifecycle_script=lifecycle_script,
    )


def merge_missing_manifest_created_at(package_root: Path) -> bool:
    """Persist ``manifest.json`` ``createdAt`` (UTC ISO) when absent or unparsable as zero-ms.

    Returns ``True`` if the manifest file was rewritten. Intended for installers
    so older archives without canonical ordering timestamps still serialize a
    stable ``createdAt`` on disk once.
    """
    manifest_path = package_root / "manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(raw, dict):
        return False
    _, existing_ms = _parse_created_at_from_manifest(
        raw.get("createdAt"), where=str(manifest_path)
    )
    if existing_ms > 0:
        return False
    raw["createdAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest_path.write_text(
        json.dumps(raw, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _, check = _parse_created_at_from_manifest(
        json.loads(manifest_path.read_text(encoding="utf-8")).get("createdAt"),
        where=str(manifest_path),
    )
    if check <= 0:
        raise ManifestError(f"{manifest_path}: failed to stamp canonical createdAt")
    return True
