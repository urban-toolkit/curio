"""Minting proposals from tool params: node content, dataset/package/project installs, package drafts, node create, row access.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from utk_curio.backend.app.agents.application import source_grounding
from utk_curio.backend.app.agents.application import verify
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.domain import map_edits
from utk_curio.backend.app.agents.domain import node_settings
from utk_curio.backend.app.agents.domain import widget_grammar
from utk_curio.backend.app.agents.application import tool_rounds as agents_tool_rounds
from utk_curio.backend.app.agents.application.proposals import acquire as agents_acquire
from utk_curio.backend.app.agents.application.proposals import cards as agents_cards
from utk_curio.backend.app.agents.application.proposals import plan_scenarios as agents_plan_scenarios
from utk_curio.backend.app.agents.application.proposals import plans as agents_plans
from utk_curio.backend.app.agents.application.proposals import store as agents_store
from utk_curio.backend.app.agents.application.turns import delegates as agents_delegates
from utk_curio.backend.app.agents.application.turns import grounding as agents_grounding
from utk_curio.backend.app.agents.application.turns import roster as agents_roster
from utk_curio.backend.app.execution.code_references import check_widget_def, normalize_widgets
from utk_curio.backend.app.execution.workflow_spec import CONTENT_KIND_NONE, PARAMETER_TYPE
from utk_curio.backend.app.projects import storage as projects_storage
from utk_curio.backend.app.agents.domain import agent_text


def _resolve_catalog_dataset(project_id: str, dataset_id: object) -> tuple[dict | None, str]:
    """Resolve a dataset id against the project's Data Catalog (dev/50 —
    the datasets domain is the single truth; `ADR-AG-007`). Returns
    ``(item | None, error_text)``. The acting user rides the request context
    (the datasets service is user-object keyed)."""
    from flask import g

    from utk_curio.backend.app.datasets.application.catalog_service import (
        DatasetCatalogService,
    )
    from utk_curio.backend.app.datasets.domain.errors import DatasetCatalogError

    if not isinstance(dataset_id, str) or not dataset_id.strip():
        return None, agent_text.message("mint.dataset-id-required")
    try:
        item = DatasetCatalogService(getattr(g, "user", None)).get_dataset(
            dataset_id.strip(), dataflow_id=project_id
        )
    except DatasetCatalogError:
        return None, agent_text.message("mint.dataset-not-in-catalog", dataset_id=repr(dataset_id))
    except Exception as exc:  # a broken catalog is data, not a run error
        return None, agent_text.message("mint.data-catalog-unavailable", exc=exc)
    return item, ""


def _mint_dataset_install(
    user_key: str, project_id: str, loop_ctx: dict, req: dict
) -> tuple[str, str, dict | None]:
    """The dev/50 catalog-lane mutation: propose installing ONE catalog
    dataset through the existing dataset-only install flow. An
    already-installed dataset refuses at mint with the existing state —
    honest chat instead of a dead proposal (docs/06 idempotence)."""
    params = req.get("params") or {}
    item, err = _resolve_catalog_dataset(project_id, params.get("datasetId"))
    if item is None:
        return "refused", err, None
    if item.get("installed"):
        return (
            "refused",
            agent_text.message("mint.dataset-already-installed", title=repr(item.get('title'))),
            None,
        )
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", agent_text.message("mint.no-saved-spec"), None
    dataset_id = str(params.get("datasetId")).strip()
    name = str(item.get("title") or dataset_id)
    proposal_id = uuid.uuid4().hex
    summary = f"Install dataset · {name}"
    preview_bits = [name]
    if item.get("format"):
        preview_bits.append(str(item["format"]))
    if item.get("origin"):
        preview_bits.append(str(item["origin"]))
    part = content.make_proposal_part(
        proposal_id=proposal_id,
        tool="dataset.install",
        summary=summary,
        preview=" · ".join(preview_bits),
        pins={"datasetId": dataset_id},
    )
    agents_store._store_proposal(
        user_key,
        project_id,
        spec,
        loop_ctx,
        {
            "proposalId": proposal_id,
            "tool": "dataset.install",
            "datasetId": dataset_id,
            "datasetName": name,
            "summary": summary,
            "status": "pending",
        },
        part,
    )
    return (
        "proposed",
        agent_text.message("mint.dataset-install-proposed", proposal_id=proposal_id, name=repr(name)),
        part,
    )


# The model's why-needed rationale rides the proposal card — bounded so a
# runaway reply can't bloat the persisted mirror (dev/84).
_PACKAGE_REASON_MAX_CHARS = 300


def _resolve_catalog_dir_name(dir_name: str, rows: dict[str, dict]) -> tuple[dict | None, list[str]]:
    """Any spelling the roster teaches → the one Nodes Catalog row (dev/105 D1).

    The roster shows a package three ways — ``curio.notes@1`` (the dirName the
    proposal takes), ``curio.notes`` (the manifest id the model reads in
    prose), and ``curio.notes/note-surface`` (the template id the roster line
    LEADS with, optionally ``@major``). The live failure this fixes: a model
    quoted the second, the mint exact-matched the first, and the refusal
    pointed at a tool the agent did not hold. A spelling the system itself
    produced must never be refused for being that spelling (the dev/93
    posture, extended from node.create to package.install).

    Returns ``(row, [])`` on a unique hit, ``(None, candidates)`` when a bare
    package id matches more than one major — never guess a major — and
    ``(None, [])`` on a true miss. Pure: no store access, no second parser —
    the template-id form goes through :func:`canonical_template_id`.
    """
    from utk_curio.backend.app.packages.service import canonical_template_id

    row = rows.get(dir_name)
    if row is not None:
        return row, []
    package_id = dir_name
    if "/" in dir_name:  # a template id: keep only the package half
        package_id = canonical_template_id(dir_name).split("/", 1)[0]
    elif "@" in dir_name:  # a dirName whose major is not in the catalog
        return None, []
    candidates = sorted(
        name for name in rows if name.rsplit("@", 1)[0] == package_id
    )
    if len(candidates) == 1:
        return rows[candidates[0]], []
    return None, candidates


def _package_install_miss_hint(granted) -> str:
    """The way out of a dirName miss, naming ONLY sources this run can read
    (DEC-063: an instruction must be executable on the path it is given).
    The enlist roster is composed for every run holding package.install, so
    it is always nameable; packages.catalog only when granted."""
    hint = agent_text.message("mint.package-miss-hint")
    if "packages.catalog" in (granted or []):
        hint += ", " + agent_text.message("mint.package-miss-hint-catalog")
    return hint


def _mint_package_install(
    user_key: str, project_id: str, loop_ctx: dict, req: dict
) -> tuple[str, str, dict | None]:
    """The dev/84 reviewed-install lane: propose installing ONE Nodes Catalog
    package through the existing package flow. Built-ins are never proposable
    (always present) and an already-installed package refuses at mint with
    the state — honest chat instead of a dead proposal (dev/16 idempotence)."""
    from utk_curio.backend.app.packages import service as packages_services

    params = req.get("params") or {}
    dir_name = params.get("dirName")
    if not isinstance(dir_name, str) or not dir_name.strip():
        return agents_tool_rounds._refuse_params(agent_text.message("mint.dir-name-required"))
    dir_name = dir_name.strip()
    try:
        rows = {
            r["dirName"]: r
            for r in packages_services.agent_catalog_overview(user_key, project_id)
        }
    except Exception as exc:  # a broken catalog is data, not a run error
        return "refused", agent_text.message("mint.nodes-catalog-unavailable", exc=exc), None
    row, candidates = _resolve_catalog_dir_name(dir_name, rows)
    if row is None and candidates:
        return agents_tool_rounds._refuse_params(
            agent_text.message(
                "mint.package-ambiguous-major", dir_name=repr(dir_name), candidates=', '.join(candidates),
            )
        )
    if row is None:
        return agents_tool_rounds._refuse_params(
            agent_text.message(
                "mint.package-not-in-catalog", dir_name=repr(dir_name),
                hint=_package_install_miss_hint(loop_ctx.get('granted')),
            )
        )
    dir_name = row["dirName"]  # the canonical dirName is what gets pinned
    if row["builtin"]:
        return agents_tool_rounds._refuse_params(
            agent_text.message("mint.package-built-in", name=repr(row['name']))
        )
    if row["installed"]:
        return agents_tool_rounds._refuse_params(
            agent_text.message("mint.package-already-installed", name=repr(row['name']))
        )
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", agent_text.message("mint.no-saved-spec"), None
    reason = params.get("reason")
    reason = reason.strip()[:_PACKAGE_REASON_MAX_CHARS] if isinstance(reason, str) else ""
    # dev/105 A3: the findings ride the ENLIST request as the A12 rows the
    # AUTHOR rung already carries — Apply enlists the package and then queues
    # one node.create card per row below this one (one parser: the dev/90
    # reader). Absent rows → enlist only, said so at Apply.
    notes = agents_delegates._notes_from_delegate_inputs({"notes": params.get("notes")}) or []
    proposal_id = uuid.uuid4().hex
    summary = f"Install package · {row['name']}" + (
        f" · {len(notes)} note{'s' if len(notes) != 1 else ''} to follow" if notes else ""
    )
    preview = reason or (row.get("description") or dir_name)
    if notes:
        preview += "\n\nNotes to follow:\n" + "\n".join(
            f"- {n.get('title') or 'Note'} · {n['content'][:80]}"
            + ("…" if len(n["content"]) > 80 else "")
            for n in notes
        )
    part = content.make_proposal_part(
        proposal_id=proposal_id,
        tool="package.install",
        summary=summary,
        preview=preview,
        pins={"dirName": dir_name},
    )
    proposal = {
        "proposalId": proposal_id,
        "tool": "package.install",
        "dirName": dir_name,
        "packageName": row["name"],
        "reason": reason,
        "summary": summary,
        "status": "pending",
    }
    if notes:
        proposal["notes"] = notes
    agents_store._store_proposal(user_key, project_id, spec, loop_ctx, proposal, part)
    return (
        "proposed",
        agent_text.message("mint.package-install-proposed", proposal_id=proposal_id, name=repr(row['name'])),
        part,
    )


#: How long a draft's justification may be: the review card shows it whole.
_JUSTIFICATION_MAX_CHARS = 2000


def _draft_new_templates(user_key: str, request) -> list[dict]:
    """The templates a package draft adds, as its manifest writes them: every
    template of a create, and the templates of an extend that its installed
    target does not declare (the build's merge plan counts additions the same
    way). An extend whose target cannot be read adds none here: its build
    refuses it."""
    from utk_curio.backend.app.packages import service as packages_services

    templates = [
        t for t in request.manifest.get("templates") or []
        if isinstance(t, dict) and isinstance(t.get("id"), str)
    ]
    if request.mode != "extend":
        return templates
    try:
        target = packages_services.load_package_manifest(
            packages_services.package_dir(user_key, request.target))
    except (packages_services.ManifestError, OSError):
        return []
    kept = {t.template_id for t in target.templates}
    return [t for t in templates if t["id"] not in kept]


def _reuse_twin(template: dict, existing: list[dict]) -> dict | None:
    """The available template a new one would duplicate (reuse territory):
    one with the same label, or one whose id is the slug of the new label."""
    from utk_curio.backend.app.packages import service as packages_services

    label = str(template.get("label") or template["id"]).strip()
    slug = packages_services.template_slug(label)
    for entry in existing:
        if str(entry.get("label") or "").strip().lower() == label.lower():
            return entry
        if slug and str(entry.get("id") or "").rsplit("/", 1)[-1] == slug:
            return entry
    return None


def _new_template_code(request, template: dict) -> list[tuple[str, str, str]]:
    """``(where, code, engine)`` for the code a new template brings, when its
    nodes hold code (derived from the manifest's own facts, never from a list
    of names): its source file and the content of each node the draft
    creates from it. A template the manifest rules refuse brings none here:
    its build refuses it."""
    from utk_curio.backend.app.packages import service as packages_services
    from utk_curio.backend.app.packages.domain.manifest import TemplateManifest

    try:
        parsed = TemplateManifest.from_json(template, where=f"template {template['id']!r}")
    except packages_services.ManifestError:
        return []
    if packages_services.template_content_kind(parsed) != packages_services.CONTENT_KIND_CODE:
        return []
    pieces: list[tuple[str, str, str]] = []
    source = request.files.get(parsed.source or "")
    if source is not None:
        try:
            pieces.append((agent_text.message("mint.new-template-where-source", source=parsed.source), source.decode("utf-8"), parsed.engine))
        except UnicodeDecodeError:
            pass
    for index, node in enumerate(request.nodes):
        if node.template_id == parsed.template_id and node.content:
            pieces.append((f"nodes[{index}].content", node.content, parsed.engine))
    return pieces


def _new_template_checks(
    user_key: str, project_id: str, loop_ctx: dict, request, justification: object,
) -> tuple[tuple[str, str, None] | None, str, dict | None]:
    """What every template a package draft adds must pass before it is built,
    since a draft is the one way an agent makes a node type: a justification
    the user judges on the review card, a label no available template has,
    and code that reads only grounded sources.

    Returns ``(refusal, justification, source)``: the mint's refusal, or None
    with the reviewed justification (empty when the draft adds no template)
    and the ``source`` payload of what the new code reads. Each refusal says
    what to change and is a free correction."""
    from utk_curio.backend.app.packages import service as packages_services

    added = _draft_new_templates(user_key, request)
    if not added:
        return None, "", None
    names = ", ".join(t["id"] for t in added)
    reason = justification.strip() if isinstance(justification, str) else ""
    if not reason:
        return agents_tool_rounds._refuse_params(
            agent_text.message("mint.draft-justification-required", s='s' if len(added) > 1 else '', names=names)
        ), "", None
    if len(reason) > _JUSTIFICATION_MAX_CHARS:
        return agents_tool_rounds._refuse_params(
            agent_text.message(
                "mint.draft-justification-too-long", length=len(reason), max_chars=_JUSTIFICATION_MAX_CHARS,
            )
        ), "", None
    try:
        existing = packages_services.available_templates(user_key, project_id)
    except Exception as exc:  # noqa: BLE001: a broken registry is data, not a run error
        return ("refused", agent_text.message("mint.template-registry-unavailable", exc=exc), None), "", None
    for template in added:
        twin = _reuse_twin(template, existing)
        if twin is not None:
            return agents_tool_rounds._refuse_params(
                agent_text.message(
                    "mint.draft-template-duplicates", template_id=repr(template['id']), twin_id=twin['id'],
                    twin_label=repr(twin['label']),
                )
            ), "", None
    refs: list[dict] = []
    for template in added:
        for where, code, engine in _new_template_code(request, template):
            # dev/114 (DEC-072): the gate for path and URL literals. The
            # no-source rule needs a known data-loading type, which a new
            # template is not.
            verdict, refusal = agents_grounding._gate_generated_content(
                user_key, project_id, loop_ctx,
                code=code, engine=engine, node_type=None, is_data_loading=False,
            )
            if refusal:
                return agents_tool_rounds._refuse_params(
                    agent_text.message(
                        "mint.new-template-ungrounded", template_id=repr(template['id']), where=where, refusal=refusal,
                    )
                ), "", None
            if verdict.source:
                refs.extend(verdict.source.get("refs") or [])
    return None, reason, (source_grounding.source_payload(refs) if refs else None)


def _mint_package_draft_apply(
    user_key: str, project_id: str, loop_ctx: dict, req: dict
) -> tuple[str, str, dict | None]:
    """The dev/89 authoring lane: validate the typed build request, run the
    isolated build service (resolve → compile → preview → package — all
    staged, content-addressed, digest-idempotent), and mint the reviewed
    package-draft proposal from its provenance.

    Every template the draft adds first passes :func:`_new_template_checks`,
    before anything is built. The ``justification`` is review prose, not
    build input: it never reaches the build request or its digest, so a
    reworded justification reuses the same build.

    A build failure is a refusal carrying the findings — the model revises
    the draft; nothing dangles. The proposal persists only bounded
    provenance (digests, diff, findings, preview digests, requested nodes)
    — the artifact itself stays in private staging until Apply promotes the
    exact reviewed digest.
    """
    from utk_curio.backend.app.packages.builder import models as build_models
    from utk_curio.backend.app.packages.builder import pipeline as build_pipeline

    params = req.get("params") or {}
    justification = None
    if isinstance(params, dict):
        params = dict(params)
        justification = params.pop("justification", None)
    try:
        request = build_models.parse_build_request(params)
    except (build_models.BuildRequestError, ValueError) as exc:
        return "refused", agent_text.message("mint.draft-request-invalid", exc=exc), None
    refusal, justification, source = _new_template_checks(
        user_key, project_id, loop_ctx, request, justification,
    )
    if refusal is not None:
        return refusal
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", agent_text.message("mint.no-saved-spec"), None
    try:
        job = build_pipeline.run_build(user_key, request)
    except Exception as exc:  # noqa: BLE001 — a broken build service is data
        return "refused", agent_text.message("mint.draft-build-unavailable", exc=exc), None
    if job.phase != "ready":
        result = job.result
        details = ""
        if result is not None:
            details = "; ".join(list(result.warnings)[:2] + list(result.policy_findings)[:3])
        if not details:
            details = "; ".join(e["message"] for e in job.events[-2:])
        return "refused", agent_text.message("mint.draft-build-incomplete", phase=job.phase, details=details), None

    result = job.result
    manifest_name = str(request.manifest.get("name") or request.target)
    action = "Extend" if request.mode == "extend" else "Build"
    summary = f"{action} package · {manifest_name}"
    diff = result.diff or {}
    files_diff = diff.get("files") or {}
    preview_line = (
        f"{len(files_diff.get('added') or [])} added / "
        f"{len(files_diff.get('modified') or [])} modified / "
        f"{len(files_diff.get('preserved') or [])} preserved files; "
        f"{len(request.nodes)} node(s) after install"
    )
    # memo dev/91 §5: the trust edge is stated ON the card, before Apply —
    # a backend-bearing draft names its handlers and declared permissions.
    backend_card = None
    if result.backend is not None:
        permissions = [
            p for p in (request.manifest.get("permissions") or [])
            if isinstance(p, str)
        ]
        backend_card = {
            "handlers": list(result.backend.get("handlers") or []),
            "permissions": permissions,
            "network": "server-network" in permissions,
        }
        names = ", ".join(h.get("name", "?") for h in backend_card["handlers"])
        preview_line += (
            f"; runs server-side code in the package sandbox — handlers: {names}"
            + ("; may reach the network (server-network declared)"
               if backend_card["network"] else "")
        )
    proposal_id = uuid.uuid4().hex
    part = content.make_proposal_part(
        proposal_id=proposal_id,
        tool="package.draft.apply",
        summary=summary,
        preview=preview_line,
        pins={"artifactDigest": result.artifact_digest, "target": request.target},
    )
    if backend_card is not None:
        part["backend"] = backend_card
    # dev/96: the diff/dependencies/preview slice rides the PART (the card's
    # reload-safe render source) — the Apply text's review claim, finally true.
    draft_card = agents_cards._draft_card_payload(request, result)
    part["draft"] = draft_card
    proposal = {
        "proposalId": proposal_id,
        "tool": "package.draft.apply",
        "mode": request.mode,
        "target": request.target,
        "draftCard": draft_card,  # mirror copy: listing symmetry (dev/96)
        "packageName": manifest_name,
        "buildId": job.build_id,
        "artifactDigest": result.artifact_digest,
        "baseDigest": request.base_digest,
        "diff": diff,
        "policyFindings": list(result.policy_findings),
        "preview": result.preview,
        # dev/91: full backend provenance (probe rows, scan findings)
        # persists with the proposal for reload and the apply record.
        "backend": result.backend,
        "requestedNodes": [n.to_payload() for n in request.nodes],
        "summary": summary,
        "status": "pending",
    }
    # The justification is what the user judges first, and the source block
    # says what the new code reads: both ride the card and the record.
    for key, value in (("justification", justification), ("source", source)):
        if value:
            part[key] = value
            proposal[key] = value
    agents_store._store_proposal(user_key, project_id, spec, loop_ctx, proposal, part)
    return (
        "proposed",
        agent_text.message(
            "mint.draft-proposed", proposal_id=proposal_id, summary=summary.lower(), digest=result.artifact_digest[:12],
        ),
        part,
    )


def _mint_proposal(
    user_key: str, project_id: str, loop_ctx: dict, req: dict
) -> tuple[str, str, dict | None]:
    """Turn a granted mutate toolRequest into a review proposal (memos dev/41,
    dev/48 — a per-tool dispatch over one shared persistence path).

    The loop never executes a mutation (`DEC-006`): validation failures come
    back as tool results the model recovers from; success mints a ``proposal``
    part (persisted with the turn) plus the attachment's ``activeProposal``
    mirror, carrying the tool's revision-safety basis the apply endpoint
    re-checks (`REQ-REVIEW-001`).
    Returns ``(status, text_for_model, proposal_part | None)``."""
    session_id = loop_ctx.get("session_id")
    if not isinstance(session_id, str):
        return "refused", agent_text.message("mint.no-conversation"), None
    tool = req.get("tool")
    if tool == "node.content.write":
        return _mint_node_content_write(user_key, project_id, loop_ctx, req)
    if tool == "node.settings.write":
        return _mint_node_settings_write(user_key, project_id, loop_ctx, req)
    if tool == "node.create":
        return _mint_node_create(user_key, project_id, loop_ctx, req)
    if tool == "dataset.install":
        return _mint_dataset_install(user_key, project_id, loop_ctx, req)
    if tool == "discovery.acquire":
        return agents_acquire._mint_discovery_acquire(user_key, project_id, loop_ctx, req)
    if tool == "package.install":
        return _mint_package_install(user_key, project_id, loop_ctx, req)
    if tool == "package.draft.apply":
        return _mint_package_draft_apply(user_key, project_id, loop_ctx, req)
    if tool == "dataflow.plan.write":
        return _mint_plan_from_params(user_key, project_id, loop_ctx, req)
    return "refused", agent_text.message("mint.no-proposal-flow", tool=repr(tool)), None


def _mint_plan_from_params(
    user_key: str, project_id: str, loop_ctx: dict, req: dict
) -> tuple[str, str, dict | None]:
    """The plan's toolRequest form (dev/55): the grants paragraph teaches the
    generic toolRequest syntax, so the runtime honors it as a first-class
    equivalent of the dataflowPlan block. The payload is ``params.dataflowPlan``
    (the nested shape models produce) or ``params`` itself; validation errors
    return as the tool refusal — the existing tool-result round feeds them
    back, so an imperfect attempt self-corrects on the shared budget."""
    params = req.get("params") or {}
    raw = params.get("dataflowPlan", params)
    plan, errors = content.parse_dataflow_plan_verbose(raw)
    if errors:
        listed = "\n".join(f"- {e}" for e in errors[:10])
        return (
            "refused",
            agent_text.message("mint.plan-params-invalid", listed=listed),
            None,
        )
    return agents_plans._mint_dataflow_plan(user_key, project_id, loop_ctx, plan)


def _node_display_name(node: dict, entry: dict | None) -> str:
    """The words a card uses for an existing node: "Python Computation node",
    or "Python Computation node · Load boundaries" when the node has a title."""
    label = (entry or {}).get("label")
    name = f"{label} node" if isinstance(label, str) and label.strip() else "node"
    title = node.get("title")
    return name + (f" · {title}" if isinstance(title, str) and title.strip() else "")


def _target_node_id(loop_ctx: dict, params: dict) -> str | None:
    """The node a request names in ``nodeId``, else the node the agent is
    attached to, else None."""
    node_id = params.get("nodeId")
    if isinstance(node_id, str) and node_id:
        return node_id
    target = loop_ctx.get("target")
    return target.get("targetId") if isinstance(target, dict) and target.get("kind") == "node" else None


def _mint_node_content_write(
    user_key: str, project_id: str, loop_ctx: dict, req: dict
) -> tuple[str, str, dict | None]:
    """The dev/41 mutation: replace one existing node's content, digest-pinned."""

    params = req.get("params") or {}
    node_id = _target_node_id(loop_ctx, params)
    if not node_id:
        return "refused", agent_text.message("tools.no-node-id"), None
    proposed = content.extract_node_content(params.get("content"))
    if not proposed:
        return "refused", agent_text.message("mint.content-required"), None
    if len(proposed) > content.PROPOSAL_CONTENT_MAX_CHARS:
        return "refused", agent_text.message("mint.content-too-large"), None
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", agent_text.message("mint.no-saved-spec"), None
    nodes = (spec.get("dataflow") or {}).get("nodes") or []
    node = next((n for n in nodes if isinstance(n, dict) and n.get("id") == node_id), None)
    if node is None:
        return "refused", agent_text.message("tools.node-not-in-spec", node_id=repr(node_id)), None
    # dev/114 (DEC-072): the gate, keyed on the EXISTING node's type — the
    # dev/73 runtime review mint inherits it (a refusal is its honest text).
    from utk_curio.backend.app.packages import service as packages_services

    entry, _err = packages_services.resolve_template(user_key, project_id, node.get("type"))
    verdict, refusal = agents_grounding._gate_generated_content(
        user_key, project_id, loop_ctx,
        code=proposed, engine=source_grounding.code_engine(entry),
        node_type=node.get("type"), params=params,
        base=loop_ctx.get("_grounding_base"), chips=agents_grounding._chip_context(spec, node_id),
        node_id=node_id,
    )
    if refusal:
        return agents_tool_rounds._refuse_params(refusal)
    # A Map Edits node's code is held to what the node reads; the code it
    # holds already is the user's own.
    unreadable = map_edits.refusal(user_key, project_id, node.get("type"), proposed, current=node.get("content") or "")
    if unreadable:
        return agents_tool_rounds._refuse_params(unreadable)
    basis = hashlib.sha256((node.get("content") or "").encode("utf-8")).hexdigest()
    proposal_id = uuid.uuid4().hex
    # The node as the user knows it, the way node.create names one: its kind,
    # and its title when it has one. The id is for the pins (#506).
    node_name = _node_display_name(node, entry)
    summary = f"Replace the content of the {node_name}"
    part = content.make_proposal_part(
        proposal_id=proposal_id,
        tool="node.content.write",
        summary=summary,
        preview=proposed,
        pins={"nodeId": node_id, "contentSha256": basis},
    )
    proposal = {
        "proposalId": proposal_id,
        "tool": "node.content.write",
        "nodeId": node_id,
        "nodeName": node_name,
        "content": proposed,
        "contentSha256": basis,
        "summary": summary,
        "status": "pending",
    }
    if verdict.source:
        part["source"] = verdict.source
        proposal["source"] = verdict.source
    agents_store._store_proposal(user_key, project_id, spec, loop_ctx, proposal, part)
    return (
        "proposed",
        agent_text.message("mint.content-write-proposed", proposal_id=proposal_id, node_id=repr(node_id)),
        part,
    )


#: What node.settings.write changes, in the order its schema lists them: the
#: settings ``node_settings`` walks, then the node's widget values.
_SETTING_PARAMS = ("dataPool", "simpleVis", "spatialJoin", "widgets")


def _settings_basis(node: dict, change: dict) -> str:
    """The digest of what *change* touches on *node*, as the node reads it:
    its type, each setting the change names as the node does it
    (``node_settings.saved``) and each widget it gives a value to. The apply
    takes it again, so a setting changed since the review stales the card and
    one the change does not touch leaves it as it is."""
    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    values = change.get("widgets") or {}
    touched = {
        "type": node.get("type"),
        "settings": {key: setting for key, setting in node_settings.saved(metadata).items() if key in change},
        "widgets": [widget for widget in normalize_widgets(metadata.get("widgets")) if widget["name"] in values],
    }
    return hashlib.sha256(json.dumps(touched, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _mint_node_settings_write(
    user_key: str, project_id: str, loop_ctx: dict, req: dict
) -> tuple[str, str, dict | None]:
    """A change of one existing node's settings: a Data Pool's modes, a Simple
    View's image column, a Spatial Join's operation and output, and the values
    of its widgets, each judged by its node's own rule on a node whose
    template keeps it, worded for the card as the node words it, and pinned to
    what it touches (``_settings_basis``)."""
    params = req.get("params") or {}
    taken = ("nodeId", *_SETTING_PARAMS)
    unknown = sorted(str(key) for key in set(params) - set(taken))
    if unknown:
        return agents_tool_rounds._refuse_params(agent_text.message(
            "node-settings.unknown-params", unknown=", ".join(unknown), keys=", ".join(taken),
        ))
    if all(params.get(key) is None for key in _SETTING_PARAMS):
        return agents_tool_rounds._refuse_params(agent_text.message(
            "node-settings.nothing-given", keys=", ".join(_SETTING_PARAMS[:-1]) + " or " + _SETTING_PARAMS[-1],
        ))
    node_id = _target_node_id(loop_ctx, params)
    if not node_id:
        return "refused", agent_text.message("tools.no-node-id"), None
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", agent_text.message("mint.no-saved-spec"), None
    nodes = (spec.get("dataflow") or {}).get("nodes") or []
    node = next((n for n in nodes if isinstance(n, dict) and n.get("id") == node_id), None)
    if node is None:
        return "refused", agent_text.message("tools.node-not-in-spec", node_id=repr(node_id)), None
    from utk_curio.backend.app.packages import service as packages_services

    entry, _err = packages_services.resolve_template(user_key, project_id, node.get("type"))
    label = (entry or {}).get("label") or node.get("type")
    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    # Each setting by its node's rule, on a node whose template keeps it.
    change, problems = node_settings.parse_change(params, "params")
    if change:
        behavior = packages_services.template_behavior(user_key, project_id, node.get("type"))
        problems += node_settings.template_problems(change, behavior, label, lambda key: f"params.{key}")
    # Each value by its widget's rule, as the Widgets tab takes it.
    widgets = normalize_widgets(metadata.get("widgets"))
    values, widget_problems = widget_grammar.parse_values(params.get("widgets"), widgets, "params.widgets", label)
    problems += widget_problems
    if problems:
        return agents_tool_rounds._refuse_params("; ".join(problems))
    by_name = {widget["name"]: widget for widget in widgets}
    lines = node_settings.describe_change(change) + [
        widget_grammar.describe_value(by_name[name], value) for name, value in (values or {}).items()
    ]
    if not node_settings.changes_anything(metadata, change) and not widget_grammar.changes_anything(widgets, values or {}):
        return agents_tool_rounds._refuse_params(agent_text.message(
            "node-settings.changes-nothing", label=label, settings="; ".join(lines),
        ))
    if values is not None:
        change["widgets"] = values
    basis = _settings_basis(node, change)
    proposal_id = uuid.uuid4().hex
    node_name = _node_display_name(node, entry)
    summary = f"Change the settings of the {node_name}"
    part = content.make_proposal_part(
        proposal_id=proposal_id,
        tool="node.settings.write",
        summary=summary,
        preview="\n".join(lines),
        pins={"nodeId": node_id, "settingsSha256": basis},
    )
    # The card's lines, each change in its node's own words.
    part["settingLines"] = lines
    proposal = {
        "proposalId": proposal_id,
        "tool": "node.settings.write",
        "nodeId": node_id,
        "nodeName": node_name,
        "settings": change,
        "settingLines": lines,
        "settingsSha256": basis,
        "summary": summary,
        "status": "pending",
    }
    agents_store._store_proposal(user_key, project_id, spec, loop_ctx, proposal, part)
    return (
        "proposed",
        agent_text.message("mint.settings-write-proposed", proposal_id=proposal_id, node_id=repr(node_id)),
        part,
    )


def _node_create_widgets(entry: dict, raw: object, nodes: list) -> tuple[list, list[str]]:
    """#662: the widgets a created node declares, or why they are refused: a
    widget is placed by a node's code or spec, so only such a node holds one.
    A Parameter node holds exactly one, which no other Parameter node of the
    dataflow (*nodes*) names: a plan's Parameter node's rule
    (``plan_scenarios.mint_errors``), in its words."""
    widgets, problems = widget_grammar.parse_widgets(raw, "params.widgets")
    if problems:
        return [], problems
    if str(entry.get("id") or "").split("@", 1)[0] == PARAMETER_TYPE:
        if len(widgets) != 1:
            return [], [agent_text.message("plan.parameter-one-widget", where="the node you create")]
        taken = agents_plan_scenarios._parameter_widgets(nodes, set())
        problem = check_widget_def(widgets[0], taken, parameter=True)
        if problem:
            return [], [f"params.widgets[0] ({widgets[0]['name']!r}): {problem}"]
        return widgets, []
    if widgets and entry.get("contentKind") not in ("code", "grammar"):
        return [], [agent_text.message("mint.widgets-not-placeable", label=entry.get('label') or entry.get('id'))]
    return widgets, []


def _node_create_settings(
    user_key: str, project_id: str, entry: dict, params: dict,
) -> tuple[dict, list[str]]:
    """A created node's settings, by key (a Spatial Join's operation and
    output, a Data Pool's conflict modes, a Simple View's image column), or
    why they are refused: each node's own rule, on a node whose template
    keeps the setting."""
    from utk_curio.backend.app.packages import service as packages_services

    settings, problems = node_settings.parse(params, "params")
    if problems or not settings:
        return {}, problems
    behavior = packages_services.template_behavior(user_key, project_id, entry["id"])
    problems = node_settings.template_problems(
        settings, behavior, entry.get("label") or entry["id"], lambda key: f"params.{key}",
    )
    return ({}, problems) if problems else (settings, [])


def _node_create_starter(user_key: str, project_id: str, entry: dict) -> dict | None:
    """What a created node starts with when its template's starter is its
    whole content (``starterIsContent``): the starter and the template's
    widgets, as a planned node of it starts (``plans._content_starters``), or
    None for any other template, whose content the request gives."""
    from utk_curio.backend.app.packages import service as packages_services

    return packages_services.content_starters(user_key, project_id, [entry["id"]]).get(entry["id"])


def _mint_node_create(
    user_key: str, project_id: str, loop_ctx: dict, req: dict
) -> tuple[str, str, dict | None]:
    """The dev/48 graph-shape mutation: propose ONE new node of an existing,
    project-available template. No digest pin — the node id is server-minted
    at apply (there is no target whose drift can corrupt); the template is
    re-validated at apply instead (`REQ-REVIEW-001` stays structural)."""
    params = req.get("params") or {}
    # Any model-supplied "id" is ignored: ids are server-minted at apply only.
    entry, err = agents_roster._available_template(user_key, project_id, params.get("nodeType"))
    if entry is None:
        return agents_tool_rounds._refuse_params(err)
    proposed = content.extract_node_content(params.get("content"))
    # A template whose starter is its whole content, such as each Scout
    # chart, gives the node that starter, as a plan does: the request gives
    # no content, and sets the template's widgets by name.
    starter = _node_create_starter(user_key, project_id, entry)
    if starter is not None and proposed:
        return agents_tool_rounds._refuse_params(agent_text.message(
            "mint.starter-is-content", label=entry.get("label") or entry["id"],
            widgets=", ".join(w["name"] for w in starter["widgets"]),
        ))
    if starter is not None:
        proposed = starter["content"]
    # A node that holds no content, such as a Spatial Join, is proposed without it.
    if not proposed and entry.get("contentKind") != CONTENT_KIND_NONE:
        return agents_tool_rounds._refuse_params(agent_text.message("mint.content-required"))
    if len(proposed) > content.PROPOSAL_CONTENT_MAX_CHARS:
        return agents_tool_rounds._refuse_params(agent_text.message("mint.content-too-large"))
    settings, setting_errors = _node_create_settings(user_key, project_id, entry, params)
    if setting_errors:
        return agents_tool_rounds._refuse_params("; ".join(setting_errors))
    # The dataflow the widgets are checked in: a Parameter node's widget is
    # named as no other Parameter node's is.
    saved = projects_storage.read_spec(user_key, project_id)
    if saved is None:
        return "refused", agent_text.message("mint.no-saved-spec"), None
    # Read before the gate: a chart's or a map's document is checked with the
    # widgets the node declares.
    widgets, widget_errors = _node_create_widgets(
        entry, params.get("widgets"),
        [n for n in (saved.get("dataflow") or {}).get("nodes") or [] if isinstance(n, dict)],
    )
    if widget_errors:
        return agents_tool_rounds._refuse_params("; ".join(widget_errors))
    if starter is not None:
        # The template's widgets, each the request names set as it says, at
        # mint, so the card shows what Apply writes.
        widgets = agents_plan_scenarios._set_over(starter["widgets"], widgets)
    # dev/114 (DEC-072): the source-grounding gate — BEFORE any store write.
    # A same-run node.create after the runtime minted dataset candidates is
    # refused too: the user reviews and confirms a source first (DEC-006).
    if loop_ctx.get("_candidates_pending_review"):
        return agents_tool_rounds._refuse_params(agent_text.message("grounding.candidates-pending"))
    # A starter is the template's own content, which a plan does not gate
    # either; any other content passes the gate.
    verdict, refusal = (None, None) if starter is not None else agents_grounding._gate_generated_content(
        user_key, project_id, loop_ctx,
        code=proposed, engine=source_grounding.code_engine(entry), node_type=entry["id"], params=params,
        chips=agents_grounding._chip_context(saved, widgets=widgets),
        widgets=widgets,
    )
    if refusal:
        return agents_tool_rounds._refuse_params(refusal)
    unreadable = None if starter is not None else map_edits.refusal(user_key, project_id, entry["id"], proposed)
    if unreadable:
        return agents_tool_rounds._refuse_params(unreadable)
    goal = params.get("goal")
    goal = goal.strip() if isinstance(goal, str) and goal.strip() else None
    # dev/105 A2 (additive): the node's HEADER. The note behavior renders
    # `title` (falling back to "Note"); `goal` is the purpose line. The mint
    # used to drop this param while the prompt asked for it — the second
    # live test's notes were all headed "Note".
    title = params.get("title")
    title = title.strip()[:agents_delegates._NODE_TITLE_MAX_CHARS] if isinstance(title, str) and title.strip() else None
    # dev/89 (additive): optional appearance, normalized by the ONE shared
    # utility — an invalid or inaccessible color refuses at mint, loudly.
    from utk_curio.backend.app.packages.application.note_palette import NOTE_PALETTE
    from utk_curio.backend.app.packages.domain import node_appearance

    raw_appearance = params.get("appearance")
    if raw_appearance is None and agents_delegates._notes_agent_run(loop_ctx) and entry.get("presentation"):
        # dev/105 A2: the A13 default on the Researcher's OWN attachment path
        # — dev/95 already filled it on the delegate path. First note of the
        # run yellow (the question), the rest green (answers). Only a
        # note-composing run on a PRESENTATION template; a supplied color
        # always wins; every other agent/template is byte-unchanged.
        k = loop_ctx.get("_note_creates", 0)
        raw_appearance = {"backgroundColor": agents_delegates._NOTES_DEFAULT_COLORS[min(k, 1)]}
    try:
        appearance = node_appearance.normalize_appearance(raw_appearance, NOTE_PALETTE)
    except node_appearance.AppearanceError as exc:
        return agents_tool_rounds._refuse_params(agent_text.message("mint.appearance-invalid", exc=exc))
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", agent_text.message("mint.no-saved-spec"), None
    proposal_id = uuid.uuid4().hex
    summary = f"Create a new {entry['label']} node" + (f" · {title}" if title else "")
    if widgets:
        summary += " · widgets " + ", ".join(w["name"] for w in widgets)
    for words in node_settings.describe(settings):
        summary += " · " + words
    part = content.make_proposal_part(
        proposal_id=proposal_id,
        tool="node.create",
        summary=summary,
        preview=proposed,
        # dev/119 (DEC-076): the roster's own answer to "can the sandbox run
        # this kind" rides the card — display, never a revision pin — so no
        # frontend file keeps a list of executable kinds.
        pins={"nodeType": entry["id"], "executable": bool(entry.get("executable"))},
    )
    proposal = {
        "proposalId": proposal_id,
        "tool": "node.create",
        "nodeType": entry["id"],
        "content": proposed,
        "summary": summary,
        "status": "pending",
    }
    if verdict is not None and verdict.source:
        # dev/114: what the code opens/fetches and how it was grounded — the
        # card's Source block; display + provenance, never a pin.
        part["source"] = verdict.source
        proposal["source"] = verdict.source
    if goal:
        proposal["goal"] = goal
    if title:
        proposal["title"] = title
    if appearance:
        proposal["appearance"] = appearance
    if widgets:
        proposal["widgets"] = widgets
    proposal.update(settings)
    agents_store._store_proposal(user_key, project_id, spec, loop_ctx, proposal, part)
    loop_ctx["_note_creates"] = loop_ctx.get("_note_creates", 0) + 1  # A13 index
    return (
        "proposed",
        agent_text.message("mint.node-create-proposed", proposal_id=proposal_id, label=entry['label']),
        part,
    )


def _mint_row_access(row: dict) -> None:
    """dev/132: what the user can DO with this row, minted from the probe.

    The owner's instruction splits the external lane: a row code can fetch is
    delegated automatically, a row a person must download from a portal
    carries the steps and an Import button. Both halves need the same thing
    first — a verdict, recorded by the runtime from what it observed
    (``DEC-053``), never a claim the model made. ``access`` is that verdict;
    ``downloadSteps`` rides only the manual answer.
    """
    outcome = row.get("verification") if isinstance(row.get("verification"), dict) else {}
    verdict = verify.classify_access(outcome, row.get("url"))
    row["access"] = verdict["access"]
    row["accessWhy"] = verdict["why"]
    if verdict["access"] == verify.ACCESS_MANUAL:
        steps = verify.download_steps(row, outcome)
        if steps:
            row["downloadSteps"] = steps


def _mint_project_install(
    user_key: str, project_id: str, loop_ctx: dict, coord: str, name: str, capability: str
) -> tuple[str, str, dict | None]:
    """The missing-specialist proposal (dev/48 §3.4, `REQ-ORCH-001`): a
    reviewed ``Install in project`` — never a silent install, never an
    install call from the loop. Returns ``(status, text, part | None)``."""
    session_id = loop_ctx.get("session_id")
    if not isinstance(session_id, str):
        return (
            "refused",
            agent_text.message("mint.specialist-no-conversation", coord=coord),
            None,
        )
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", agent_text.message("mint.no-saved-spec"), None
    proposal_id = uuid.uuid4().hex
    summary = f"Install {name} in this project"
    preview = (
        f"Capability {capability} is handled by {name} ({coord}), which is not "
        "installed in this project. Applying installs only this project template — "
        "it does not import, attach, run, publish, or grant anything."
    )
    part = content.make_proposal_part(
        proposal_id=proposal_id,
        tool="project.install",
        summary=summary,
        preview=preview,
        pins={"coord": coord},
    )
    agents_store._store_proposal(
        user_key,
        project_id,
        spec,
        loop_ctx,
        {
            "proposalId": proposal_id,
            "tool": "project.install",
            "coord": coord,
            "summary": summary,
            "status": "pending",
        },
        part,
    )
    return (
        "proposed",
        agent_text.message("mint.specialist-install-proposed", coord=coord, proposal_id=proposal_id),
        part,
    )
