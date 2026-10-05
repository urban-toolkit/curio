"""Bounded review-card payloads (the package-draft card, memo dev/96).

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations


# dev/96: the rich review card's bounded payload — parts persist with every
# turn (the A6 lesson), so every list carries a cap AND its true total; the
# card renders the slice, the overflow count keeps it honest.
_DRAFT_CARD_MAX_FILES = 20


_DRAFT_CARD_MAX_TEMPLATES = 10


_DRAFT_CARD_MAX_DEP_ROWS = 10


_DRAFT_CARD_MAX_FINDINGS = 10


_DRAFT_CARD_MAX_PREVIEW_TEMPLATES = 8


_DRAFT_CARD_MAX_PREVIEW_REASONS = 3


_DRAFT_CARD_MAX_NODES = 8


_FINDING_SEVERITY_ORDER = {"block": 0, "warn": 1, "note": 2}


def _draft_card_payload(request, result) -> dict:
    """dev/96: the diff, dependencies, and preview the Apply text has always
    CLAIMED the user reviewed — composed once at mint from the typed build
    result, bounded per list (cap + honest total, never silent truncation),
    and attached to the transcript part so the card renders it reload-safe.
    Absent sections stay absent; a plain dep-less create carries no
    Dependencies section at all."""
    card: dict = {"mode": request.mode, "target": request.target}

    diff = result.diff or {}
    files = diff.get("files") or {}
    card["files"] = {
        "added": [str(p) for p in (files.get("added") or [])[:_DRAFT_CARD_MAX_FILES]],
        "modified": [str(p) for p in (files.get("modified") or [])[:_DRAFT_CARD_MAX_FILES]],
        "addedTotal": len(files.get("added") or []),
        "modifiedTotal": len(files.get("modified") or []),
        # 0 is information — a create preserves nothing and SAYS so.
        "preservedTotal": len(files.get("preserved") or []),
    }
    templates = diff.get("templates") or {}
    card["templates"] = {
        "added": [str(t) for t in (templates.get("added") or [])[:_DRAFT_CARD_MAX_TEMPLATES]],
        "modified": [str(t) for t in (templates.get("modified") or [])[:_DRAFT_CARD_MAX_TEMPLATES]],
        "addedTotal": len(templates.get("added") or []),
        "modifiedTotal": len(templates.get("modified") or []),
        "preservedTotal": len(templates.get("preserved") or []),
    }

    sbom = (result.dependencies or {}).get("sbom") or {}
    python_rows = [
        {"name": str(r.get("name")), "constraint": str(r.get("constraint") or "*")}
        for r in (sbom.get("python") or []) if isinstance(r, dict)
    ]
    js_rows = [
        {"name": str(r.get("name")),
         "version": str(r.get("resolvedVersion") or r.get("constraint") or "*")}
        for r in ((sbom.get("js") or {}).get("direct") or []) if isinstance(r, dict)
    ]
    findings = [
        {"severity": str(f.get("severity")), "code": str(f.get("code")),
         "message": str(f.get("message"))[:300]}
        for f in (sbom.get("findings") or []) if isinstance(f, dict)
    ]
    # Blocks sort first: the cap must never hide a block behind notes.
    findings.sort(key=lambda f: _FINDING_SEVERITY_ORDER.get(f["severity"], 3))
    if python_rows or js_rows or findings:
        # dev/97: where the python deps will LIVE — the same routing rule
        # promote applies (one core, two adapters — the card can never
        # disagree with the install).
        from utk_curio.backend.app.packages.service import dep_destinations_raw

        home, _home_reason = dep_destinations_raw(request.manifest or {})
        card["dependencies"] = {
            "home": home,
            "python": python_rows[:_DRAFT_CARD_MAX_DEP_ROWS],
            "pythonTotal": len(python_rows),
            "js": js_rows[:_DRAFT_CARD_MAX_DEP_ROWS],
            "jsTotal": len(js_rows),
            "findings": findings[:_DRAFT_CARD_MAX_FINDINGS],
            "findingsTotal": len(findings),
            "blocked": bool(sbom.get("blocked")),
        }

    preview = result.preview
    if isinstance(preview, dict):
        states = preview.get("states") or {}
        template_rows = []
        for template_id in sorted(states)[:_DRAFT_CARD_MAX_PREVIEW_TEMPLATES]:
            per_state = states.get(template_id) or {}
            failed = sorted(
                state for state, payload in per_state.items()
                if isinstance(payload, dict) and payload.get("consoleErrors")
            )
            template_rows.append({
                "templateId": template_id,
                "ok": not failed,
                "failedStates": failed,
            })
        card["preview"] = {
            "status": str(preview.get("status") or "unknown"),
            "reasons": [str(r)[:300] for r in
                        (preview.get("reasons") or [])[:_DRAFT_CARD_MAX_PREVIEW_REASONS]],
            "reasonsTotal": len(preview.get("reasons") or []),
            "templates": template_rows,
            "runnerVersion": str(preview.get("runnerVersion") or ""),
        }

    if request.nodes:
        card["requestedNodes"] = {
            "rows": [
                {"title": node.title or node.template_id,
                 "color": (node.appearance or {}).get("backgroundColor", "")}
                for node in request.nodes[:_DRAFT_CARD_MAX_NODES]
            ],
            "total": len(request.nodes),
        }
    return card
