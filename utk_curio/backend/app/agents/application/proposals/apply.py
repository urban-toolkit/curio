"""An agent's changes to the dataflow, landed; and the installs a person reviews, applied or dismissed.

An agent's change to the dataflow lands at once (``changes.py``): ``land_content``,
``land_settings`` and ``land_node`` here, ``plans._land_dataflow_plan`` for a plan.
An install changes the account, so it waits for the person who asked: a package,
a package draft, a dataset, a Discovery download, an agent in the dataflow. Its
Apply (``apply_proposal``) and its Dismiss are the person's.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import copy
import uuid

from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.repositories import project_agents
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.agents.application import catalog as agents_catalog
from utk_curio.backend.app.agents.application import dataset_resolution as agents_dataset_resolution
from utk_curio.backend.app.agents.application import lifecycle as agents_lifecycle
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application.proposals import acquire as agents_acquire
from utk_curio.backend.app.agents.application.proposals import changes as agents_changes
from utk_curio.backend.app.agents.application.proposals import mint as agents_mint
from utk_curio.backend.app.agents.application.proposals import plans as agents_plans
from utk_curio.backend.app.agents.application.proposals import store as agents_store
from utk_curio.backend.app.agents.domain import agent_text
from utk_curio.backend.app.agents.domain import node_settings
from utk_curio.backend.app.agents.infrastructure import testing_provider
from utk_curio.backend.app.collaboration import dataflow_docs
from utk_curio.backend.app.collaboration import history


# ── an install, reviewed (memo dev/41) ───────────────────────────────────────
def apply_proposal(
    user_key: str, project_id: str, attachment_id: str, proposal_id: str
) -> dict:
    """Apply a pending install the person reviewed: the one path that runs an
    install an agent asked for.

    Explicit, authenticated, revision-safe (`REQ-REVIEW-001`/`DEC-006`): what
    it installs is checked again against the catalog and the dataflow now;
    drift marks the proposal ``stale`` and returns 409 instead of applying.
    Success runs the install's own flow, logs a result-card turn (docs/08:
    results are logged as chat turns), and consumes no quota (deterministic,
    no provider work). No model/tool/user *text* can reach this path, only
    this endpoint."""
    spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    # DEC-080 (dev/126): a plan apply attaches the plan-node agents, so the
    # closure is completed BEFORE the apply reads the lockfile it consults.
    if agents_lifecycle._repair_required_closure(
        user_key, project_id, record.get("coord", ""), attachment_id=attachment_id
    ):
        spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
        record = agents_spec_reads._record_or_404(spec, attachment_id)
    # dev/90 A16: settle the same-reply queue first, then address the
    # proposal by id in EITHER pending home — active slot or queue.
    attachments.reconcile_proposal_queue(spec, attachment_id)
    proposal = attachments.find_proposal(spec, attachment_id, proposal_id)
    if proposal is None:
        raise AgentServiceError(f"proposal {proposal_id!r} not found", 404)
    status = proposal.get("status")
    if status != "pending":
        raise AgentServiceError(f"this proposal is {status!r} and can no longer be applied", 409)
    session_id = record.get("sessionId")
    tool = proposal.get("tool")
    if tool == "project.install":
        return _apply_project_install(
            user_key, project_id, attachment_id, proposal_id, spec, proposal, session_id
        )
    if tool == "dataset.install":
        return _apply_dataset_install(
            user_key, project_id, attachment_id, proposal_id, spec, proposal, session_id
        )
    if tool == "discovery.acquire":
        return agents_acquire._apply_discovery_acquire(
            user_key, project_id, attachment_id, proposal_id, spec, proposal, session_id
        )
    if tool == "package.install":
        return _apply_package_install(
            user_key, project_id, attachment_id, proposal_id, spec, proposal, session_id
        )
    if tool == "package.draft.apply":
        return _apply_package_draft(
            user_key, project_id, attachment_id, proposal_id, spec, proposal, session_id
        )
    raise AgentServiceError(f"no apply flow exists for tool {tool!r}", 409)


def _node_in(spec: dict, node_id: object) -> dict | None:
    nodes = (spec.get("dataflow") or {}).get("nodes") or []
    return next((n for n in nodes if isinstance(n, dict) and n.get("id") == node_id), None)


def _resolve_plan_ledger(spec: dict, node_id: str):
    """When *node_id* is a node of a plan, the code an agent writes into it
    resolves the plan's ledger: its row approved, its run solved, and the
    plan ready once nothing is left pending (dev/67-6, dev/71). The ledger
    may live on the agent that planned it while the code comes from the
    node's own (dev/72): found wherever it is. Returns what puts the ledger
    back, for a write that is refused."""
    session: dict = {}
    ref = None
    for ledger_record in attachments.list_attachments(spec):
        ledger_session = ledger_record.get("builderSession") or {}
        candidate_ref = next(
            (r for r, nid in (ledger_session.get("nodeIds") or {}).items() if nid == node_id),
            None,
        )
        if candidate_ref is not None:
            session = ledger_session
            ref = candidate_ref
            break
    before = copy.deepcopy(session)
    if ref is not None:
        (session.get("nodeStates") or {})[ref] = "approved"
        runs = session.get("nodeRuns")
        if isinstance(runs, dict) and node_id in runs:
            runs[node_id] = "solved"
        if session.get("phase") in ("applied", "simulating") and isinstance(runs, dict):
            if not any(st in ("pending", "failed") for st in runs.values()):
                session["phase"] = "ready"

    def restore() -> None:
        session.clear()
        session.update(before)

    return restore


def _writer(user_key: str, spec: dict, loop_ctx: dict) -> str | None:
    """The name of the agent a change is by, as its manifest names it: the
    agent of the attachment that made it. The canvas names the change's
    entry in a node's history after it."""
    return _writer_name(user_key, spec, loop_ctx.get("attachment_id"))


def land_content(user_key: str, project_id: str, loop_ctx: dict, spec: dict, proposal: dict, part: dict):
    """``node.content.write``, landed: one node's code, nothing else, as the
    agent's change. Refused when the node took other code after the mint read
    it, the check a person's put-back has: the node keeps its code."""
    attachment_id = loop_ctx.get("attachment_id")
    node_id = proposal["nodeId"]
    node = _node_in(spec, node_id)
    before = node.get("content") or ""
    node["content"] = proposal.get("content", "")
    restore = _resolve_plan_ledger(spec, node_id)
    change = agents_changes.new_change("node.content.write", proposal["summary"], nodeId=node_id,
                                       before=before, content=node["content"])
    agents_changes.keep(spec, attachment_id, change)

    def _changed_meanwhile(_refused: tuple) -> None:
        restore()
        agents_changes.forget(spec, attachment_id, change["changeId"])

    written = dataflow_docs.write(user_key, project_id, spec, agents_changes.actor(user_key, spec, loop_ctx, "apply"),
                                  on_refused=_changed_meanwhile)
    if written.refused:
        return "refused", agent_text.message("change.changed-meanwhile", node_id=repr(node_id)), None
    writer = _writer(user_key, spec, loop_ctx)
    agents_changes.landed(loop_ctx, change, {
        "kind": "node-content-applied", "nodeId": node_id, "content": node["content"],
        **({"agent": writer} if writer else {}),
    })
    # A change minted before #506 carries no name; its id is all there is.
    lines = [proposal.get("nodeName") or f"node {node_id}"]
    return (agents_changes.LANDED, agent_text.message("change.content-written", node_id=repr(node_id)),
            agents_changes.card(part, change, lines))


def _applied_by(user_key: str, spec: dict, attachment_id: str) -> dataflow_docs.Actor:
    """Who an applied install's change is by: the agent of the attachment
    that asked for it, asked by the account that applied it."""
    return agents_spec_reads._agent_actor(user_key, spec, attachment_id, "apply")


def _writer_name(user_key: str, spec: dict, attachment_id: str) -> str | None:
    """The name of the agent of *attachment_id*, as its manifest names it, or
    None. The canvas names the entry of a node it made after it."""
    return agents_spec_reads._agent_name(
        user_key, str((attachments.get_attachment(spec, attachment_id) or {}).get("coord") or ""),
    )


def _created_for_canvas(created: dict, writer: str | None) -> dict:
    """A node an agent created, as the canvas bridge takes it: a copy, naming
    the agent that wrote it, whose history the canvas starts named after it.
    The spec's node carries no name."""
    return {**created, "agent": writer} if writer else dict(created)


def land_settings(user_key: str, project_id: str, loop_ctx: dict, spec: dict, proposal: dict, part: dict):
    """``node.settings.write``, landed: the settings it names, each written
    into the saved node as the node stores it once picked, as the agent's
    change, with a point of the history of its own. The canvas makes the same
    change through the node's own setters."""
    attachment_id = loop_ctx.get("attachment_id")
    node_id = proposal["nodeId"]
    settings = proposal.get("settings") or {}
    node = _node_in(spec, node_id)
    undo_steps = agents_changes.settings_undone(node, settings)
    agents_changes.write_settings(node, settings)
    change = agents_changes.new_change(
        "node.settings.write", proposal["summary"], nodeId=node_id, settings=settings, undo=undo_steps,
        basisAfter=agents_changes.settings_basis(node, settings),
    )
    agents_changes.keep(spec, attachment_id, change)
    dataflow_docs.write(user_key, project_id, spec, agents_changes.actor(user_key, spec, loop_ctx, "apply"),
                        point={"kind": history.AGENT, "what": ""})
    agents_changes.landed(loop_ctx, change, {"kind": "node-settings-applied", "nodeId": node_id, "settings": settings})
    lines = [proposal.get("nodeName") or f"node {node_id}", *(proposal.get("settingLines") or [])]
    return (agents_changes.LANDED, agent_text.message("change.settings-written", node_id=repr(node_id)),
            agents_changes.card(part, change, lines))


def _apply_dataset_install(
    user_key: str,
    project_id: str,
    attachment_id: str,
    proposal_id: str,
    spec: dict,
    proposal: dict,
    session_id: object,
) -> dict:
    """The dev/50 apply: the EXISTING dataset-only install flow (duplicate
    collapse, authorization, OSM groups — all the domain service's own
    semantics). A dataset gone from the catalog between mint and apply is
    the drift analogue: 409 + ``stale``. No agent is ever installed here."""
    from flask import g

    from utk_curio.backend.app.datasets.application.catalog_service import (
        DatasetCatalogService,
    )

    dataset_id = proposal.get("datasetId", "")
    item, err = agents_mint._resolve_catalog_dataset(project_id, dataset_id)
    if item is None:
        raise agents_store._mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"the dataset is no longer available ({err}) — ask the agent to search again",
        )
    try:
        DatasetCatalogService(getattr(g, "user", None)).install_dataset(
            project_id, dataset_id
        )
    except Exception as exc:
        raise agents_store._mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"the dataset could not be installed: {exc}",
        ) from exc
    # The install wrote the spec (dataset refs); re-read so the proposal
    # mirror update below does not clobber the new entries.
    spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
    proposal = attachments.find_proposal(spec, attachment_id, proposal_id) or proposal
    proposal["status"] = "applied"
    # dev/126: a node that was waiting for exactly this dataset is resolved by
    # this install — the reviewed lane is what "awaiting-install" waited for.

    resolved_nodes = agents_dataset_resolution.mark_dataset_installed(spec, dataset_id)
    dataflow_docs.write(user_key, project_id, spec, _applied_by(user_key, spec, attachment_id))
    name = str(item.get("title") or dataset_id)
    agents_store._log_applied_turn(
        user_key, project_id, session_id, attachment_id, proposal_id,
        f"Applied: dataset installed ({name}).",
        "Applied: dataset installed",
        [name, dataset_id,
         *([f"{len(resolved_nodes)} node(s) waiting for it can now be solved"]
           if resolved_nodes else []),
         f"proposal {proposal_id[:8]}"],
    )
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": "applied",
        "mutationApplied": True,
        "installedDataset": {"id": dataset_id, "name": name},
    }


def _apply_package_install(
    user_key: str,
    project_id: str,
    attachment_id: str,
    proposal_id: str,
    spec: dict,
    proposal: dict,
    session_id: object,
) -> dict:
    """The dev/84 apply: the EXISTING package install flow (user-store copy +
    dep provisioning + per-project lockfile — all the packages service's own
    semantics under its spec lock). The frontend shows the package install
    dialog BEFORE posting this apply; the dialog is the review surface, this
    endpoint is the authority — conflicts and catalog absence are re-checked
    here regardless and are the drift analogue: 409 + ``stale``."""
    from utk_curio.backend.app.packages import service as packages_services

    dir_name = proposal.get("dirName", "")
    try:
        report = packages_services.agent_resolve_report(user_key, [dir_name])
    except packages_services.PackageServiceError as exc:
        raise agents_store._mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"the package is no longer installable ({exc}) — ask the agent to search again",
        ) from exc
    if report["conflicts"]:
        named = ", ".join(sorted({c["package"] for c in report["conflicts"]}))
        raise agents_store._mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"installing would conflict with this project's packages ({named}) — "
            "resolve the conflict in the Nodes Catalog first",
        )
    try:
        install = packages_services.install_to_project(user_key, project_id, dir_name)
    except Exception as exc:
        raise agents_store._mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"the package could not be installed: {exc}",
        ) from exc
    # pip counts matching metadata as satisfaction, so a wheel whose native
    # extension cannot load installs without complaint. The install already
    # asks whether the libraries import; keeping the answer here is what stops
    # the applied turn saying "package installed" over a package whose first
    # run raises. NOT a stale/refusal: the package is installed and the repair
    # (a matching GDAL, a conda-forge build) is the user's, so this is the last
    # place the failure is still attached to the package that brought it in.
    broken_line = _broken_library_line(install.get("importErrors"))
    # The install wrote the spec (the package lockfile); re-read so the
    # proposal mirror update below does not clobber the new entry.
    spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
    proposal = attachments.find_proposal(spec, attachment_id, proposal_id) or proposal
    proposal["status"] = "applied"
    dataflow_docs.write(user_key, project_id, spec, _applied_by(user_key, spec, attachment_id))
    name = str(proposal.get("packageName") or dir_name)
    # dev/105 A3: the findings that rode the request become notes of the
    # enlisted package, each the agent's change, their cards below this one.
    created, note_parts, notes_line = _enlisted_notes(
        user_key, project_id, spec, attachment_id, session_id, dir_name,
        proposal.get("notes") or [],
    )
    agents_store._log_applied_turn(
        user_key, project_id, session_id, attachment_id, proposal_id,
        f"Applied: package installed ({name}).{broken_line}{notes_line}",
        "Applied: package installed",
        [name, dir_name, f"proposal {proposal_id[:8]}"],
        extra_parts=note_parts,
    )
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": "applied",
        "mutationApplied": True,
        "installedPackage": {"dirName": dir_name, "name": name},
        **({"importErrors": install["importErrors"]}
           if install.get("importErrors") else {}),
        # dev/105 A4: the lockfile CHANGED: the frontend refreshes its package
        # registry and project-packages store BEFORE it paints the notes, or
        # they render "Loading node..." for a type it does not hold.
        "requiresRegistryRefresh": True,
        # The notes, in row order, for a canvas no doc binds.
        "createdNodes": created,
    }


def _broken_library_line(import_errors, dependency_error=None) -> str:
    """`` rasterio cannot be imported (...).`` for the applied turn, or ``""``.

    One sentence, appended to the turn the user reads after Apply. The wording
    matches the frontend's ``dependencyFailureNotice`` deliberately: the same
    failure should not read as a different problem depending on whether a
    button or an agent reached it. That includes its order: pip's own failure
    leads, because the probe after it only restates it as "not installed".
    """
    if dependency_error:
        return (
            f" But its libraries could not be installed: {dependency_error}."
            " Nodes needing them will fail until they are installed."
        )
    if not import_errors:
        return ""
    named = "; ".join(
        f"{lib} cannot be imported ({reason})"
        for lib, reason in sorted(import_errors.items())
    )
    return f" But {named}. Nodes needing it will fail until it is repaired."


def _enlisted_notes(
    user_key: str,
    project_id: str,
    spec: dict,
    attachment_id: str,
    session_id: object,
    dir_name: str,
    notes: list,
) -> tuple[list[dict], list[dict], str]:
    """dev/105 A3: the enlisted package's notes, in row order, each landed
    through the ordinary ``node.create`` mint (so titles and the A13 colors
    are exactly its) as the agent's change. Returns ``(the nodes for the
    canvas, their change cards, log suffix)``. Honest degradation: no rows,
    no presentation template, or a row the mint refuses is SAID in the
    suffix, never silent."""
    if not notes:
        return [], [], " No notes rode this request: ask the Researcher to create them."
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.service import ManifestError, is_note_template
    from utk_curio.backend.app.packages.repositories.store import user_packages_dir

    try:
        manifest = load_package_manifest(user_packages_dir(user_key) / dir_name)
    except (ManifestError, OSError) as exc:
        return [], [], f" Notes skipped: the package manifest is unreadable ({exc})."
    template = next((t for t in manifest.templates if is_note_template(t)), None)
    if template is None:
        return [], [], (
            f" Notes skipped: {manifest.package_id} has no presentation (note) "
            "template: ask the Researcher to author one."
        )
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    loop_ctx = {
        "attachment_id": attachment_id,
        "session_id": session_id if isinstance(session_id, str) else None,
        # The A13 default keys on the attached agent's capability, as in a run.
        "manifest": agents_catalog._resolve_definition(user_key, record.get("coord", "")),
    }
    node_type = f"{manifest.package_id}/{template.template_id}"
    parts: list[dict] = []
    skipped: list[str] = []
    for row in notes:
        req = {"params": {
            "nodeType": node_type,
            "content": row["content"],
            **({"title": row["title"]} if row.get("title") else {}),
            **({"appearance": row["appearance"]} if row.get("appearance") else {}),
        }}
        status, text, part = agents_mint._mint_node_create(user_key, project_id, loop_ctx, req)
        if status == agents_changes.LANDED and part is not None:
            parts.append(part)
        else:
            skipped.append(f"{row.get('title') or 'Note'}: {text}")
    created = [landed["canvas"]["node"] for landed in agents_changes.take_landed(loop_ctx)]
    line = f" {len(parts)} note{'s' if len(parts) != 1 else ''} added below." if parts else ""
    if skipped:
        line += " Skipped: " + "; ".join(skipped) + "."
    return created, parts, line


def _apply_package_draft(
    user_key: str,
    project_id: str,
    attachment_id: str,
    proposal_id: str,
    spec: dict,
    proposal: dict,
    session_id: object,
) -> dict:
    """The dev/89 apply: promote the EXACT reviewed artifact digest through
    the promotion coordinator (verify-on-read, stale/collision protection,
    backup + journal, lockfile after install), then insert the requested
    nodes server-side with their normalized appearance.

    Ordering (dev/89 §3.10): install → lockfile → nodes in the SPEC; the
    apply response carries ``requiresRegistryRefresh`` so the frontend
    refreshes the package/behavior/template registries BEFORE painting the
    created nodes on the live canvas (registry-before-canvas). The backend
    confirms the promotion journal once the spec write lands — the spec is
    the source of truth the registries load from. A node-insertion failure
    compensates through the coordinator's rollback, and the outcome
    (rolled-back vs rollback-failed) rides the stale message honestly.
    """
    from utk_curio.backend.app.packages.builder import promotion as build_promotion
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.service import ManifestError
    from utk_curio.backend.app.packages.service import (
        PackageId,
        package_dir as _package_dir,
    )

    target = str(proposal.get("target") or "")
    artifact_digest = str(proposal.get("artifactDigest") or "")
    base_digest = proposal.get("baseDigest")
    try:
        journal = build_promotion.promote(
            user_key,
            target=target,
            artifact_digest=artifact_digest,
            base_digest=base_digest if isinstance(base_digest, str) else None,
            project_id=project_id,
        )
    except build_promotion.PromotionError as exc:
        raise agents_store._mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"the reviewed build can no longer be applied: {exc} — ask the "
            "agent to rebuild the draft",
        ) from exc

    # The promotion wrote the spec (project lockfile); re-read so the node
    # insertions and proposal mirror below never clobber it.
    spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
    proposal = attachments.find_proposal(spec, attachment_id, proposal_id) or proposal

    try:
        installed_manifest = load_package_manifest(_package_dir(user_key, target))
        installed_templates = {t.template_id for t in installed_manifest.templates}
        coord = PackageId.parse_dir(target)
        created_nodes: list[dict] = []
        for node in proposal.get("requestedNodes") or []:
            template_id = str(node.get("templateId") or "")
            if template_id not in installed_templates:
                raise AgentServiceError(
                    f"requested node targets template {template_id!r}, which the "
                    f"installed package does not declare", 409,
                )
            created = _insert_node(
                spec,
                coord.canonical(template_id),
                str(node.get("content") or ""),
                node.get("goal"),
                appearance=node.get("appearance"),
                title=node.get("title"),
            )
            created_nodes.append(created)
        proposal["status"] = "applied"
        dataflow_docs.write(user_key, project_id, spec, _applied_by(user_key, spec, attachment_id))
    except Exception as exc:
        rolled = build_promotion.rollback(
            user_key, artifact_digest, f"node insertion failed: {exc}")
        # The dataflow without the nodes inserted above, and its proposal: the
        # stale mark lands on the proposal of the spec it writes.
        unchanged = agents_spec_reads._live_spec_or_404(user_key, project_id)
        raise agents_store._mark_stale(
            user_key, project_id, proposal_id, unchanged,
            attachments.find_proposal(unchanged, attachment_id, proposal_id) or proposal,
            session_id,
            f"the package installed but its nodes could not be created ({exc}); "
            f"the prior state was {rolled['rollback']['status']} — ask the agent "
            "to rebuild",
        ) from exc

    # Activation from the backend's view: the spec (which the registries load
    # from) now carries the lockfile entry and the nodes. The frontend still
    # refreshes its registries before painting (requiresRegistryRefresh).
    build_promotion.confirm_registry_ready(user_key, artifact_digest)
    build_promotion.confirm_nodes_created(user_key, artifact_digest)

    name = str(proposal.get("packageName") or target)
    # dev/92 B-2: the restart signal rides the result turn AND the payload —
    # pip actually changed shared libraries under the running server; nodes
    # keep the previously loaded versions until Curio restarts.
    restart = journal.get("restartRecommended")
    restart_line = ""
    if isinstance(restart, dict) and restart.get("libs"):
        restart_line = (
            " Restart Curio to pick up "
            + ", ".join(str(lib) for lib in restart["libs"])
            + " — running nodes keep the previously loaded versions until then."
        )
    # A declared library that installed but cannot be imported. Said here
    # because this turn is what claims the package was installed: pip counts
    # metadata as satisfaction, so without this the user reads "built and
    # installed" and meets the failure later as a node's ImportError.
    broken_imports = journal.get("importErrors")
    if isinstance(broken_imports, dict) and broken_imports:
        restart_line += (
            " Warning: "
            + "; ".join(
                f"{lib} installed but cannot be imported ({reason})"
                for lib, reason in sorted(broken_imports.items())
            )
            + " — nodes needing it will fail until it is repaired."
        )
    agents_store._log_applied_turn(
        user_key, project_id, session_id, attachment_id, proposal_id,
        f"Applied: package {name} built and installed"
        + (f"; {len(created_nodes)} node(s) created." if created_nodes else ".")
        + restart_line,
        "Applied: package draft installed",
        [name, target, f"proposal {proposal_id[:8]}"],
    )
    writer = _writer_name(user_key, spec, attachment_id)
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": "applied",
        "mutationApplied": True,
        "installedPackage": {"dirName": target, "name": name,
                             "replaced": bool(journal.get("backupHeld"))},
        # Consumed by the frontend canvas bridge — registry refresh happens
        # BEFORE these nodes are painted (dev/89 registry-before-canvas).
        "createdNodes": [_created_for_canvas(node, writer) for node in created_nodes],
        "requiresRegistryRefresh": True,
        **({"restartRecommended": restart} if isinstance(restart, dict)
           and restart.get("libs") else {}),
    }


def _apply_project_install(
    user_key: str,
    project_id: str,
    attachment_id: str,
    proposal_id: str,
    spec: dict,
    proposal: dict,
    session_id: object,
) -> dict:
    """The dev/48 missing-specialist apply: the reviewed ``Install in
    project`` (`REQ-ORCH-001`). Reuses the existing install service — one
    project template, nothing imported/attached/run/published/granted.
    Already-installed re-applies are idempotent success, not an error."""
    coord = proposal.get("coord", "")
    already = coord in set(project_agents.project_agents(spec))
    if not already:
        try:
            # The existing reviewed-install service (spec re-read + written
            # inside; our in-hand spec is only used for the mirror below).
            agents_lifecycle.install_in_project(user_key, project_id, coord)
        except AgentServiceError as exc:
            raise agents_store._mark_stale(
                user_key, project_id, proposal_id, spec, proposal, session_id,
                f"the install could not be applied: {exc}",
            ) from exc
        # The install wrote the spec; re-read so the mirror update below
        # does not clobber the new template entry.
        spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
        proposal = attachments.find_proposal(spec, attachment_id, proposal_id) or proposal
    proposal["status"] = "applied"
    dataflow_docs.write(user_key, project_id, spec, _applied_by(user_key, spec, attachment_id))
    agents_store._log_applied_turn(
        user_key, project_id, session_id, attachment_id, proposal_id,
        f"Applied: {coord} installed in this project.",
        "Applied: agent installed",
        [coord, f"proposal {proposal_id[:8]}"],
    )
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": "applied",
        "mutationApplied": True,
        "installedCoord": coord,
    }


# Placement for server-minted nodes (dev/48): a gutter right of the current
# extent, aligned with the rightmost node's row.
_NODE_PLACEMENT_DEFAULT = (80.0, 80.0)


def _insert_node(
    spec: dict,
    node_type: str,
    node_content: str,
    goal: str | None,
    *,
    appearance: dict | None = None,
    title: str | None = None,
    widgets: list | None = None,
    settings: dict | None = None,
) -> dict:
    """Append one server-minted node to the spec's dataflow (dev/48): fresh
    uuid id (collision-impossible, never from any param; a test run may
    script it), placed right of the current node extent. The caller writes
    the spec.

    ``appearance`` (dev/89, additive) is already normalized by the shared
    node-appearance utility and persists at the canonical
    ``metadata.appearance.backgroundColor`` shape; callers that omit it stay
    byte-for-byte identical. ``widgets`` (#662), checked at mint, persist at
    ``metadata.widgets`` the same way, and the node's ``settings``, by key
    (``node_settings``: a Spatial Join's operation and output, a Data Pool's
    modes, a Simple View's image column), each at ``metadata.<key>``.
    """
    dataflow = spec.setdefault("dataflow", {})
    nodes = dataflow.setdefault("nodes", [])
    placed = [n for n in nodes if isinstance(n, dict) and isinstance(n.get("x"), (int, float))]
    if placed:
        rightmost = max(placed, key=lambda n: agents_plans._right_edge([n]))
        x = agents_plans._right_edge([rightmost]) + agents_plans._NODE_H_GUTTER
        at_y = rightmost.get("y")
        y = float(at_y) if isinstance(at_y, (int, float)) else _NODE_PLACEMENT_DEFAULT[1]
    else:
        x, y = _NODE_PLACEMENT_DEFAULT
    # A test run may script the id (testing_provider.push_node_ids); one already
    # on the canvas is never reused.
    node_id = testing_provider.next_node_id()
    if not node_id or any(isinstance(n, dict) and n.get("id") == node_id for n in nodes):
        node_id = str(uuid.uuid4())
    created = {"id": node_id, "type": node_type, "content": node_content, "x": x, "y": y}
    if goal:
        created["goal"] = goal
    if title:
        created["title"] = title
    if appearance:
        created["metadata"] = {"appearance": dict(appearance)}
    if widgets:
        created.setdefault("metadata", {})["widgets"] = [dict(w) for w in widgets]
    for key, setting in (settings or {}).items():
        created.setdefault("metadata", {})[key] = dict(setting)
    nodes.append(created)
    return created


def land_node(user_key: str, project_id: str, loop_ctx: dict, spec: dict, proposal: dict, part: dict):
    """``node.create``, landed: ONE new node of the template the mint checked,
    its id server-minted here (never from a param), as the agent's change."""
    attachment_id = loop_ctx.get("attachment_id")
    node_type = proposal["nodeType"]
    created = _insert_node(
        spec, node_type, proposal.get("content", ""), proposal.get("goal"),
        appearance=proposal.get("appearance"),  # dev/89: typed round-trip
        title=proposal.get("title"),  # dev/105 A2: the header the note renders
        widgets=proposal.get("widgets"),  # #662: what its code's references name
        settings=node_settings.of(proposal),  # a join's operation, a pool's modes, a view's image column
    )
    change = agents_changes.new_change(
        "node.create", proposal["summary"], nodeId=created["id"],
        created=[{"id": created["id"], "type": node_type, "content": created.get("content") or ""}],
    )
    agents_changes.keep(spec, attachment_id, change)
    dataflow_docs.write(user_key, project_id, spec, agents_changes.actor(user_key, spec, loop_ctx, "apply"))
    agents_changes.landed(loop_ctx, change, {
        "kind": "node-created", "node": _created_for_canvas(created, _writer(user_key, spec, loop_ctx)),
    })
    label = proposal.get("label") or node_type
    lines = [f"{label} · {node_type}", f"node {created['id']}"]
    return (agents_changes.LANDED,
            agent_text.message("change.node-added", node_id=repr(created["id"]), label=label),
            agents_changes.card(part, change, lines))


def dismiss_proposal(
    user_key: str, project_id: str, attachment_id: str, proposal_id: str
) -> dict:
    """Dismiss a pending install (keeps its outcome visible on the card)."""
    spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    # dev/90 A16: a queued same-reply sibling is dismissible by id too.
    attachments.reconcile_proposal_queue(spec, attachment_id)
    proposal = attachments.find_proposal(spec, attachment_id, proposal_id)
    if proposal is None:
        raise AgentServiceError(f"proposal {proposal_id!r} not found", 404)
    if proposal.get("status") != "pending":
        raise AgentServiceError(
            f"this proposal is {proposal.get('status')!r} and can no longer be dismissed", 409
        )
    proposal["status"] = "dismissed"
    attachments.reconcile_proposal_queue(spec, attachment_id)
    dataflow_docs.write(user_key, project_id, spec, agents_spec_reads._person(user_key, "dismiss"))
    session_id = record.get("sessionId")
    if isinstance(session_id, str):
        sessions.update_proposal_status(
            user_key, project_id, session_id, proposal_id, "dismissed"
        )
    return {"attachmentId": attachment_id, "proposalId": proposal_id, "status": "dismissed"}
