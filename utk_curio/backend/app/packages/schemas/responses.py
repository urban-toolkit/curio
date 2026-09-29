"""The JSON shape of a package on the wire — ``package_payload`` is THE serializer every route and listing uses.

Schemas layer of the packages package (memo dev/143, B2-b): lifted out of ``routes.py`` so handlers
parse, call and serialize and carry no rules; every function keeps its body.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path

from utk_curio.backend.app.packages.domain.catalog_family import family_key_for_manifest
from utk_curio.backend.app.packages.domain.manifest import PackageManifest


README_MAX_BYTES = 64 * 1024  # 64 KiB cap on README content surfaced via payload.


def lineage_payload(manifest: PackageManifest) -> dict | None:
    lin = manifest.lineage
    if lin is None:
        return None
    return {
        "forkedFrom": {
            "packageId": lin.forked_from.package_id,
            "major": lin.forked_from.major,
        },
        "root": {
            "packageId": lin.root.package_id,
            "major": lin.root.major,
        },
    }


def manifest_json_mtime_ms(package_path: Path) -> int:
    """Epoch milliseconds of ``manifest.json`` mtime (0 if missing/unreadable).

    Exposed as ``installUpdatedAtMs`` for diagnostics (last write on disk).
    Canonical package ordering uses ``createdAtMs`` from the manifest.
    """
    try:
        return int((package_path / "manifest.json").stat().st_mtime * 1000)
    except OSError:
        return 0


def package_payload(manifest: PackageManifest, *, package_mtime_path: Path | None = None) -> dict:
    templates = []
    for tpl in manifest.templates:
        templates.append(
            {
                "id": manifest.canonical_for(tpl.template_id),
                "templateId": tpl.template_id,
                "label": tpl.label,
                "category": tpl.category,
                "engine": tpl.engine,
                "description": tpl.description,
                "icon": tpl.icon,
                "iconRef": tpl.icon_ref,
                "behavior": tpl.behavior,
                "paletteOrder": tpl.palette_order,
                "editor": tpl.editor,
                "hasCode": tpl.has_code,
                "hasWidgets": tpl.has_widgets,
                "hasGrammar": tpl.has_grammar,
                "grammarId": tpl.grammar_id,
                "badge": tpl.badge,
                "inputPorts": [asdict(p) if is_dataclass(p) else p for p in tpl.input_ports],
                "outputPorts": [asdict(p) if is_dataclass(p) else p for p in tpl.output_ports],
                "source": tpl.source,
                "bidirectional": tpl.bidirectional,
                "containerStyle": tpl.container_style,
                "hasProvenance": tpl.has_provenance,
                "tutorialId": tpl.tutorial_id,
                # dev/91: the declared backend handler this template's Run
                # invokes through the package backend sandbox (null = none).
                "backendHandler": tpl.backend_handler,
            }
        )
    payload = {
        "packageId": manifest.package_id,
        "major": manifest.major,
        "version": manifest.version,
        "name": manifest.name,
        "publisher": manifest.publisher,
        "description": manifest.description,
        "license": manifest.license,
        "permissions": manifest.permissions,
        "dependencies": {
            "packages": dict(manifest.package_deps),
            "python": dict(manifest.python_deps),
            "js": dict(manifest.js_deps),
        },
        "templates": templates,
        "dirName": manifest.dir_name,
        "lineage": lineage_payload(manifest),
        "familyKey": family_key_for_manifest(manifest),
        "channel": manifest.channel,
        **({"readOnly": True} if manifest.read_only else {}),
        "createdAtMs": manifest.created_at_ms,
        **({"behaviorScript": manifest.behavior_script} if manifest.behavior_script else {}),
    }
    if manifest.created_at_iso:
        payload["createdAt"] = manifest.created_at_iso
    if package_mtime_path is not None:
        payload["installUpdatedAtMs"] = manifest_json_mtime_ms(package_mtime_path)
        # Surface README contents (capped) so the metadata editor can pre-populate.
        readme_path = package_mtime_path / "README.md"
        if readme_path.is_file():
            try:
                raw = readme_path.read_text(encoding="utf-8")
                payload["readme"] = raw[:README_MAX_BYTES]
            except OSError:
                pass
    return payload


def resolve_payload(result) -> dict:
    """``{"lockfile", "conflicts"}`` of a :class:`ResolveResult` — the resolve
    probe's body (and the shape the agents' resolve report echoes)."""
    return {
        "lockfile": result.to_lockfile(),
        "conflicts": [
            {
                "package": c.package,
                "ranges": [{"packageDir": p, "range": r} for (p, r) in c.ranges],
            }
            for c in result.conflicts
        ],
    }


def libraries_payload(agg, install_refusal: str | None = None) -> dict:
    """``{"standalone", "fromPackages", "installAllowed", "installDisabledReason"}``
    of a :class:`LibraryList`: whether POST/DELETE would be refused rides along,
    so the modal can hide controls that could only fail and say why (#309)."""
    return {
        "standalone": agg.standalone,
        "fromPackages": [
            {"name": e.name, "spec": e.spec, "kind": e.kind, "source": e.source,
             "installed": e.installed}
            for e in agg.from_packages
        ],
        "installAllowed": install_refusal is None,
        "installDisabledReason": install_refusal,
    }
