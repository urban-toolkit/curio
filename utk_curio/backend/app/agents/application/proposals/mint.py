"""Minting proposals from tool params: node content, template create, dataset/package/project installs, package drafts, node create, row access.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import hashlib
import uuid

from utk_curio.backend.app.agents.application import verify
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.domain import widget_grammar
from utk_curio.backend.app.agents.application import tool_rounds as agents_tool_rounds
from utk_curio.backend.app.agents.application.proposals import acquire as agents_acquire
from utk_curio.backend.app.agents.application.proposals import cards as agents_cards
from utk_curio.backend.app.agents.application.proposals import plans as agents_plans
from utk_curio.backend.app.agents.application.proposals import store as agents_store
from utk_curio.backend.app.agents.application.turns import delegates as agents_delegates
from utk_curio.backend.app.agents.application.turns import grounding as agents_grounding
from utk_curio.backend.app.agents.application.turns import roster as agents_roster
from utk_curio.backend.app.projects import storage as projects_storage


_TEMPLATE_ENGINES = ("python", "javascript")


def _mint_node_template_create(
    user_key: str, project_id: str, loop_ctx: dict, req: dict
) -> tuple[str, str, dict | None]:
    """The dev/48 §3.2b creation fallback: a reviewed proposal for a NEW
    custom node type. The runtime cannot judge adequacy — the review card is
    the adequacy gate, so a written justification is mandatory, and a label
    that collides with an available template is refused as reuse territory."""
    from utk_curio.backend.app.packages import service as packages_services

    params = req.get("params") or {}
    justification = params.get("justification")
    if not isinstance(justification, str) or not justification.strip():
        return (
            "refused",
            "the review needs your reasoning — state which existing templates you "
            "considered and why they don't fit (params.justification)",
            None,
        )
    template = params.get("template")
    if not isinstance(template, dict):
        return "refused", "params.template must be an object", None
    label = str(template.get("label") or "").strip()
    slug = packages_services.template_slug(label)
    if not slug:
        return "refused", "template.label must be a non-empty name", None
    engine = template.get("engine") or "python"
    if engine not in _TEMPLATE_ENGINES:
        return "refused", "template.engine must be 'python' or 'javascript'", None
    code = content.extract_node_content(template.get("content"))
    if not code:
        return "refused", "template.content must be a non-empty string", None
    if len(code) > content.PROPOSAL_CONTENT_MAX_CHARS:
        return "refused", "template.content exceeds the proposal size bound", None
    # dev/114 (DEC-072): a new type's first-node content passes the same gate
    # for path/URL literals (the no-source rule needs a known data-loading
    # type, which a brand-new template is not).
    verdict, refusal = agents_grounding._gate_generated_content(
        user_key, project_id, loop_ctx,
        code=code, engine=engine, node_type=None, params=params, is_data_loading=False,
    )
    if refusal:
        return agents_tool_rounds._refuse_params(refusal)
    try:
        existing = packages_services.available_templates(user_key, project_id)
    except Exception as exc:
        return "refused", f"the node template registry is unavailable: {exc}", None
    collision = next(
        (
            t
            for t in existing
            if t["id"].rsplit("/", 1)[-1] == slug
            or t["label"].strip().lower() == label.lower()
        ),
        None,
    )
    if collision is not None:
        return (
            "refused",
            f"a template like this already exists ({collision['id']}) — that is reuse "
            "territory: propose a node.create with it instead",
            None,
        )
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", "no saved project spec is available", None
    proposal_id = uuid.uuid4().hex
    summary = f"Create a new custom node type · {label}"
    description = str(template.get("description") or "").strip()
    part = content.make_proposal_part(
        proposal_id=proposal_id,
        tool="node.template.create",
        summary=summary,
        preview=code,
        pins={"templateSlug": slug},
    )
    # The justification + definition ride the part for the review card —
    # the justification is what the user judges (memo dev/48 §3.2b).
    part["justification"] = justification.strip()
    part["template"] = {"label": label, "engine": engine, "description": description}
    if verdict.source:
        part["source"] = verdict.source  # dev/114
    agents_store._store_proposal(
        user_key,
        project_id,
        spec,
        loop_ctx,
        {
            "proposalId": proposal_id,
            "tool": "node.template.create",
            "justification": justification.strip(),
            "template": {
                "label": label,
                "engine": engine,
                "description": description,
                "content": code,
            },
            "summary": summary,
            "status": "pending",
        },
        part,
    )
    return (
        "proposed",
        f"proposal {proposal_id} created for a new custom node type {label!r}; it "
        "awaits the user's explicit review — do NOT assume the type or node exists",
        part,
    )


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
        return None, "params.datasetId must be a non-empty dataset id string"
    try:
        item = DatasetCatalogService(getattr(g, "user", None)).get_dataset(
            dataset_id.strip(), dataflow_id=project_id
        )
    except DatasetCatalogError:
        return None, (
            f"dataset {dataset_id!r} is not in this project's Data Catalog — "
            "propose only ids from catalog.search results"
        )
    except Exception as exc:  # a broken catalog is data, not a run error
        return None, f"the Data Catalog is unavailable: {exc}"
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
            f"dataset {item.get('title')!r} is already installed in this project — "
            "tell the user instead of proposing",
            None,
        )
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", "no saved project spec is available", None
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
        f"proposal {proposal_id} created to install dataset {name!r}; it awaits the "
        "user's explicit review — do NOT assume it was installed",
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
    hint = (
        "use the dirName shown in parentheses after '(package …)' in the "
        "'Installed but NOT enlisted in this project' list"
    )
    if "packages.catalog" in (granted or []):
        hint += ", or a dirName from packages.catalog results"
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
        return agents_tool_rounds._refuse_params("params.dirName must be a non-empty package dirName string")
    dir_name = dir_name.strip()
    try:
        rows = {
            r["dirName"]: r
            for r in packages_services.agent_catalog_overview(user_key, project_id)
        }
    except Exception as exc:  # a broken catalog is data, not a run error
        return "refused", f"the Nodes Catalog is unavailable: {exc}", None
    row, candidates = _resolve_catalog_dir_name(dir_name, rows)
    if row is None and candidates:
        return agents_tool_rounds._refuse_params(
            f"package {dir_name!r} names more than one major in the Nodes Catalog — "
            f"propose exactly one of: {', '.join(candidates)}"
        )
    if row is None:
        return agents_tool_rounds._refuse_params(
            f"package {dir_name!r} is not in the Nodes Catalog — "
            f"{_package_install_miss_hint(loop_ctx.get('granted'))}"
        )
    dir_name = row["dirName"]  # the canonical dirName is what gets pinned
    if row["builtin"]:
        return agents_tool_rounds._refuse_params(
            f"package {row['name']!r} is built-in — always present, never proposed; "
            "tell the user it is already available"
        )
    if row["installed"]:
        return agents_tool_rounds._refuse_params(
            f"package {row['name']!r} is already installed in this project — "
            "tell the user instead of proposing"
        )
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", "no saved project spec is available", None
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
        f"proposal {proposal_id} created to install package {row['name']!r}; it awaits "
        "the user's explicit review through the package install dialog — do NOT "
        "assume it was installed",
        part,
    )


def _mint_package_draft_apply(
    user_key: str, project_id: str, loop_ctx: dict, req: dict
) -> tuple[str, str, dict | None]:
    """The dev/89 authoring lane: validate the typed build request, run the
    isolated build service (resolve → compile → preview → package — all
    staged, content-addressed, digest-idempotent), and mint the reviewed
    package-draft proposal from its provenance.

    A build failure is a refusal carrying the findings — the model revises
    the draft; nothing dangles. The proposal persists only bounded
    provenance (digests, diff, findings, preview digests, requested nodes)
    — the artifact itself stays in private staging until Apply promotes the
    exact reviewed digest.
    """
    from utk_curio.backend.app.packages.builder import models as build_models
    from utk_curio.backend.app.packages.builder import pipeline as build_pipeline

    params = req.get("params") or {}
    try:
        request = build_models.parse_build_request(params)
    except (build_models.BuildRequestError, ValueError) as exc:
        return "refused", f"invalid build request: {exc}", None
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", "no saved project spec is available", None
    try:
        job = build_pipeline.run_build(user_key, request)
    except Exception as exc:  # noqa: BLE001 — a broken build service is data
        return "refused", f"the package build service failed to start: {exc}", None
    if job.phase != "ready":
        result = job.result
        details = ""
        if result is not None:
            details = "; ".join(list(result.warnings)[:2] + list(result.policy_findings)[:3])
        if not details:
            details = "; ".join(e["message"] for e in job.events[-2:])
        return "refused", (
            f"the package build did not complete (phase {job.phase}): {details} "
            "— revise the draft and request package.draft.apply again"
        ), None

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
    agents_store._store_proposal(
        user_key,
        project_id,
        spec,
        loop_ctx,
        {
            "proposalId": proposal_id,
            "tool": "package.draft.apply",
            "mode": request.mode,
            "target": request.target,
            "draftCard": draft_card,  # mirror copy — listing symmetry (dev/96)
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
        },
        part,
    )
    return (
        "proposed",
        f"proposal {proposal_id} created: {summary.lower()} (artifact "
        f"{result.artifact_digest[:12]}…). It awaits the user's explicit review "
        "of the diff, dependencies, and preview — do NOT claim the package or "
        "its nodes exist until the user applies it",
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
        return "refused", "proposals need a persistent conversation; this attachment has none", None
    tool = req.get("tool")
    if tool == "node.content.write":
        return _mint_node_content_write(user_key, project_id, loop_ctx, req)
    if tool == "node.create":
        return _mint_node_create(user_key, project_id, loop_ctx, req)
    if tool == "node.template.create":
        return _mint_node_template_create(user_key, project_id, loop_ctx, req)
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
    return "refused", f"no proposal flow exists for tool {tool!r}", None


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
            "your dataflowPlan was invalid — fix exactly these problems and "
            f"resend the complete corrected request:\n{listed}",
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


def _mint_node_content_write(
    user_key: str, project_id: str, loop_ctx: dict, req: dict
) -> tuple[str, str, dict | None]:
    """The dev/41 mutation: replace one existing node's content, digest-pinned."""

    params = req.get("params") or {}
    node_id = params.get("nodeId")
    if not isinstance(node_id, str) or not node_id:
        target = loop_ctx.get("target")
        node_id = (
            target.get("targetId")
            if isinstance(target, dict) and target.get("kind") == "node"
            else None
        )
    if not node_id:
        return "refused", "no nodeId given and this agent is not attached to a node", None
    proposed = content.extract_node_content(params.get("content"))
    if not proposed:
        return "refused", "params.content must be a non-empty string", None
    if len(proposed) > content.PROPOSAL_CONTENT_MAX_CHARS:
        return "refused", "params.content exceeds the proposal size bound", None
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", "no saved project spec is available", None
    nodes = (spec.get("dataflow") or {}).get("nodes") or []
    node = next((n for n in nodes if isinstance(n, dict) and n.get("id") == node_id), None)
    if node is None:
        return "refused", f"node {node_id!r} not found in the saved spec", None
    # dev/114 (DEC-072): the gate, keyed on the EXISTING node's type — the
    # dev/73 runtime review mint inherits it (a refusal is its honest text).
    from utk_curio.backend.app.packages import service as packages_services

    entry, _err = packages_services.resolve_template(user_key, project_id, node.get("type"))
    verdict, refusal = agents_grounding._gate_generated_content(
        user_key, project_id, loop_ctx,
        code=proposed, engine=(entry or {}).get("engine"),
        node_type=node.get("type"), params=params,
        base=loop_ctx.get("_grounding_base"),
    )
    if refusal:
        return agents_tool_rounds._refuse_params(refusal)
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
        f"proposal {proposal_id} created for node {node_id!r}; it awaits the user's "
        "explicit review — do NOT assume it was applied",
        part,
    )


def _node_create_widgets(entry: dict, raw: object) -> tuple[list, list[str]]:
    """#662: the widgets a created node declares, or why they are refused: a
    widget is placed by a node's code or spec, so only such a node holds one."""
    widgets, problems = widget_grammar.parse_widgets(raw, "params.widgets")
    if problems:
        return [], problems
    if widgets and entry.get("contentKind") not in ("code", "grammar"):
        return [], [f"params.widgets: a {entry.get('label') or entry.get('id')} node cannot hold widgets; "
                    "a widget is placed in a node's code or spec"]
    return widgets, []


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
    if not proposed:
        return agents_tool_rounds._refuse_params("params.content must be a non-empty string")
    if len(proposed) > content.PROPOSAL_CONTENT_MAX_CHARS:
        return agents_tool_rounds._refuse_params("params.content exceeds the proposal size bound")
    # dev/114 (DEC-072): the source-grounding gate — BEFORE any store write.
    # A same-run node.create after the runtime minted dataset candidates is
    # refused too: the user reviews and confirms a source first (DEC-006).
    if loop_ctx.get("_candidates_pending_review"):
        return agents_tool_rounds._refuse_params(agents_grounding._CANDIDATES_PENDING_TEXT)
    verdict, refusal = agents_grounding._gate_generated_content(
        user_key, project_id, loop_ctx,
        code=proposed, engine=entry.get("engine"), node_type=entry["id"], params=params,
    )
    if refusal:
        return agents_tool_rounds._refuse_params(refusal)
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
        appearance = node_appearance.normalize_appearance(raw_appearance)
    except node_appearance.AppearanceError as exc:
        return agents_tool_rounds._refuse_params(f"params.appearance: {exc}")
    widgets, widget_errors = _node_create_widgets(entry, params.get("widgets"))
    if widget_errors:
        return agents_tool_rounds._refuse_params("; ".join(widget_errors))
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", "no saved project spec is available", None
    proposal_id = uuid.uuid4().hex
    summary = f"Create a new {entry['label']} node" + (f" · {title}" if title else "")
    if widgets:
        summary += " · widgets " + ", ".join(w["name"] for w in widgets)
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
    if verdict.source:
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
    agents_store._store_proposal(user_key, project_id, spec, loop_ctx, proposal, part)
    loop_ctx["_note_creates"] = loop_ctx.get("_note_creates", 0) + 1  # A13 index
    return (
        "proposed",
        f"proposal {proposal_id} created for a new {entry['label']} node; it awaits "
        "the user's explicit review — do NOT assume it was applied",
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
            f"specialist {coord} is not installed and this attachment has no "
            "conversation to carry an install proposal — ask the user to install it",
            None,
        )
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", "no saved project spec is available", None
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
        f"specialist {coord} is not installed in this project; an Install proposal "
        f"({proposal_id}) awaits the user's explicit review — do NOT assume it was "
        "installed or that the delegate ran",
        part,
    )
