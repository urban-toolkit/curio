"""Apply and dismiss: the review-before-apply gate dispatching each proposal kind to its writer (memo dev/41).

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import hashlib
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
from utk_curio.backend.app.agents.application.proposals import mint as agents_mint
from utk_curio.backend.app.agents.application.proposals import plans as agents_plans
from utk_curio.backend.app.agents.application.proposals import store as agents_store
from utk_curio.backend.app.agents.application.turns import roster as agents_roster
from utk_curio.backend.app.projects import storage as projects_storage


# ── review-before-apply (memo dev/41) ────────────────────────────────────────
def apply_proposal(
    user_key: str, project_id: str, attachment_id: str, proposal_id: str
) -> dict:
    """Apply a pending proposal — the ONLY path that executes a mutate tool.

    Explicit, authenticated, revision-safe (`REQ-REVIEW-001`/`DEC-006`): the
    pinned revision basis is re-checked against current state (content digest
    for ``node.content.write``; template availability for ``node.create``);
    drift marks the proposal ``stale`` and returns 409 instead of applying.
    Success executes the domain-owned write under the project's spec write
    path, logs a result-card turn (docs/08 — results are logged as chat
    turns), and consumes no quota (deterministic, no provider work). No
    model/tool/user *text* can reach this path — only this endpoint."""
    spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    # DEC-080 (dev/126): a plan apply attaches the plan-node agents, so the
    # closure is completed BEFORE the apply reads the lockfile it consults.
    if agents_lifecycle._repair_required_closure(
        user_key, project_id, record.get("coord", ""), attachment_id=attachment_id
    ):
        spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
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
    tool = proposal.get("tool", "node.content.write")
    if tool == "node.create":
        return _apply_node_create(
            user_key, project_id, attachment_id, proposal_id, spec, proposal, session_id
        )
    if tool == "node.content.write":
        return _apply_node_content_write(
            user_key, project_id, attachment_id, proposal_id, spec, proposal, session_id
        )
    if tool == "project.install":
        return _apply_project_install(
            user_key, project_id, attachment_id, proposal_id, spec, proposal, session_id
        )
    if tool == "node.template.create":
        return _apply_node_template_create(
            user_key, project_id, attachment_id, proposal_id, spec, proposal, session_id
        )
    if tool == "dataset.install":
        return _apply_dataset_install(
            user_key, project_id, attachment_id, proposal_id, spec, proposal, session_id
        )
    if tool == "datalake.acquire":
        return agents_acquire._apply_datalake_acquire(
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
    if tool == "dataflow.plan.write":
        return agents_plans._apply_dataflow_plan(
            user_key, project_id, attachment_id, proposal_id, spec, proposal, session_id
        )
    raise AgentServiceError(f"no apply flow exists for tool {tool!r}", 409)


def _apply_node_content_write(
    user_key: str,
    project_id: str,
    attachment_id: str,
    proposal_id: str,
    spec: dict,
    proposal: dict,
    session_id: object,
) -> dict:
    """The dev/41 apply: one node's content, digest-checked, nothing else."""

    node_id = proposal.get("nodeId")
    nodes = (spec.get("dataflow") or {}).get("nodes") or []
    node = next((n for n in nodes if isinstance(n, dict) and n.get("id") == node_id), None)
    current = (node.get("content") if node is not None else None) or ""
    basis = hashlib.sha256(current.encode("utf-8")).hexdigest()
    if node is None or basis != proposal.get("contentSha256"):
        raise agents_store._mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            "the node changed since this was proposed — ask the agent to propose again",
        )
    # The domain-owned mutation (ADR-AG-007): one node's content, nothing else.
    node["content"] = proposal.get("content", "")
    proposal["status"] = "applied"
    # dev/67-6: when this node is a plan node, applying its content resolves
    # the Simulation Mode ledger — the row is approved, the run solved.
    # dev/72: the proposal may live on the NODE's agent while the ledger
    # lives on the BUILDER — find the ledger wherever it is.
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
    if ref is not None:
        (session.get("nodeStates") or {})[ref] = "approved"
        runs = session.get("nodeRuns")
        if isinstance(runs, dict) and node_id in runs:
            runs[node_id] = "solved"
        # dev/71: the structure may have completed before the content did —
        # the last approval flips the phase to ready.
        if session.get("phase") in ("applied", "simulating") and isinstance(runs, dict):
            if not any(st in ("pending", "failed") for st in runs.values()):
                session["phase"] = "ready"
    projects_storage.write_spec(user_key, project_id, spec)
    agents_store._log_applied_turn(
        user_key, project_id, session_id, attachment_id, proposal_id,
        f"Applied: node content updated ({node_id}).",
        "Applied: node content updated",
        [f"node {node_id}", f"proposal {proposal_id[:8]}"],
    )
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": "applied",
        "mutationApplied": True,
        # The frontend canvas bridge (dev/48 §3.3) applies this to the LIVE
        # node too, so the next canvas save can't clobber the mutation.
        "appliedContent": {"nodeId": node_id, "content": proposal.get("content", "")},
    }


def _apply_node_template_create(
    user_key: str,
    project_id: str,
    attachment_id: str,
    proposal_id: str,
    spec: dict,
    proposal: dict,
    session_id: object,
) -> dict:
    """The dev/48 §3.2b apply: ONE explicit review covering both stated
    effects — register the template through the EXISTING package factory
    (atomic staging; store + project lockfile), then insert the first node.
    Template first, node only on success: a factory failure 409s with the
    verbatim error and nothing is half-registered."""
    from utk_curio.backend.app.packages import service as packages_services

    template = proposal.get("template") or {}
    try:
        created_template = packages_services.create_template_package(
            user_key, project_id, template
        )
    except packages_services.PackageServiceError as exc:
        raise agents_store._mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"the node type could not be registered: {exc}",
        ) from exc
    # The factory path wrote the spec (lockfile); re-read before inserting the
    # node so we don't clobber the new package entry.
    spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
    proposal = attachments.find_proposal(spec, attachment_id, proposal_id) or proposal
    created = _insert_node(spec, created_template["id"], template.get("content", ""), None)
    proposal["status"] = "applied"
    projects_storage.write_spec(user_key, project_id, spec)
    label = created_template["label"]
    agents_store._log_applied_turn(
        user_key, project_id, session_id, attachment_id, proposal_id,
        f"Applied: node type registered and node created ({created['id']}).",
        "Applied: custom node type created",
        [
            f"{label} · {created_template['id']}",
            f"node {created['id']}",
            f"proposal {proposal_id[:8]}",
        ],
    )
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": "applied",
        "mutationApplied": True,
        "createdTemplate": created_template,
        "createdNode": dict(created),
    }


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
    spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
    proposal = attachments.find_proposal(spec, attachment_id, proposal_id) or proposal
    proposal["status"] = "applied"
    # dev/126: a node that was waiting for exactly this dataset is resolved by
    # this install — the reviewed lane is what "awaiting-install" waited for.

    resolved_nodes = agents_dataset_resolution.mark_dataset_installed(spec, dataset_id)
    projects_storage.write_spec(user_key, project_id, spec)
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
    spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
    proposal = attachments.find_proposal(spec, attachment_id, proposal_id) or proposal
    proposal["status"] = "applied"
    projects_storage.write_spec(user_key, project_id, spec)
    name = str(proposal.get("packageName") or dir_name)
    # dev/105 A3: the findings that rode the request become the A16 sequence
    # of node.create cards BELOW this one — minted pending, applied one at a
    # time by the frontend walk so each note lands before the next card.
    follow_ups, note_parts, notes_line = _queue_enlisted_notes(
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
        # dev/105 A4: the lockfile CHANGED — the frontend must refresh its
        # package registry + project-packages store BEFORE the follow-up notes
        # paint, or they render "Loading node…" for a type it does not hold.
        "requiresRegistryRefresh": True,
        # dev/105 A3: ordered — the frontend applies them one after another.
        "followUpProposals": follow_ups,
    }


def _broken_library_line(import_errors) -> str:
    """`` rasterio cannot be imported (...).`` for the applied turn, or ``""``.

    One sentence, appended to the turn the user reads after Apply. The wording
    matches the frontend's ``dependencyFailureNotice`` deliberately: the same
    failure should not read as a different problem depending on whether a
    button or an agent reached it.
    """
    if not import_errors:
        return ""
    named = "; ".join(
        f"{lib} cannot be imported ({reason})"
        for lib, reason in sorted(import_errors.items())
    )
    return f" But {named}. Nodes needing it will fail until it is repaired."


def _queue_enlisted_notes(
    user_key: str,
    project_id: str,
    spec: dict,
    attachment_id: str,
    session_id: object,
    dir_name: str,
    notes: list,
) -> tuple[list[str], list[dict], str]:
    """dev/105 A3: mint the enlisted package's notes as ONE pending A16
    sequence of ``node.create`` proposals (row order) — through the ordinary
    mint, so titles and the A13 colors are exactly the commit-6 path — and
    return ``(proposal ids, proposal parts, log suffix)``. Nothing is
    inserted into the graph here; each card is applied by the frontend walk,
    one at a time. Honest degradation: no rows, no presentation template, or
    a row that fails to mint is SAID in the suffix, never silent."""
    if not notes:
        return [], [], " No notes rode this request — ask the Researcher to create them."
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.service import ManifestError
    from utk_curio.backend.app.packages.repositories.store import user_packages_dir

    try:
        manifest = load_package_manifest(user_packages_dir(user_key) / dir_name)
    except (ManifestError, OSError) as exc:
        return [], [], f" Notes skipped: the package manifest is unreadable ({exc})."
    template = next(
        (t for t in manifest.templates if t.behavior and t.editor == "none"), None
    )
    if template is None:
        return [], [], (
            f" Notes skipped: {manifest.package_id} has no presentation (note) "
            "template — ask the Researcher to author one."
        )
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    loop_ctx = {
        "attachment_id": attachment_id,
        "session_id": session_id if isinstance(session_id, str) else None,
        # The A13 default keys on the attached agent's capability, as in a run.
        "manifest": agents_catalog._resolve_definition(user_key, record.get("coord", "")),
    }
    node_type = f"{manifest.package_id}/{template.template_id}"
    ids: list[str] = []
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
        if status == "proposed" and part is not None:
            ids.append(part["proposalId"])
            parts.append(part)
        else:
            skipped.append(f"{row.get('title') or 'Note'}: {text}")
    line = f" {len(ids)} note{'s' if len(ids) != 1 else ''} queued below." if ids else ""
    if skipped:
        line += " Skipped — " + "; ".join(skipped) + "."
    return ids, parts, line


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
    spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
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
        projects_storage.write_spec(user_key, project_id, spec)
    except Exception as exc:
        rolled = build_promotion.rollback(
            user_key, artifact_digest, f"node insertion failed: {exc}")
        raise agents_store._mark_stale(
            user_key, project_id, proposal_id,
            agents_spec_reads._read_spec_or_404(user_key, project_id),
            attachments.find_proposal(spec, attachment_id, proposal_id) or proposal,
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
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": "applied",
        "mutationApplied": True,
        "installedPackage": {"dirName": target, "name": name,
                             "replaced": bool(journal.get("backupHeld"))},
        # Consumed by the frontend canvas bridge — registry refresh happens
        # BEFORE these nodes are painted (dev/89 registry-before-canvas).
        "createdNodes": created_nodes,
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
        spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
        proposal = attachments.find_proposal(spec, attachment_id, proposal_id) or proposal
    proposal["status"] = "applied"
    projects_storage.write_spec(user_key, project_id, spec)
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


# Placement for server-minted nodes (dev/48): right of the current extent,
# aligned with the rightmost node's row. Offsets match typical node width.
_NODE_PLACEMENT_X_OFFSET = 420


_NODE_PLACEMENT_DEFAULT = (80.0, 80.0)


def _insert_node(
    spec: dict,
    node_type: str,
    node_content: str,
    goal: str | None,
    *,
    appearance: dict | None = None,
    title: str | None = None,
) -> dict:
    """Append one server-minted node to the spec's dataflow (dev/48): fresh
    uuid id (collision-impossible, never from any param), placed right of the
    current node extent. The caller writes the spec.

    ``appearance`` (dev/89, additive) is already normalized by the shared
    node-appearance utility and persists at the canonical
    ``metadata.appearance.backgroundColor`` shape; callers that omit it stay
    byte-for-byte identical.
    """
    dataflow = spec.setdefault("dataflow", {})
    nodes = dataflow.setdefault("nodes", [])
    xs = [
        (n.get("x"), n.get("y"))
        for n in nodes
        if isinstance(n, dict) and isinstance(n.get("x"), (int, float))
    ]
    if xs:
        max_x, at_y = max(xs, key=lambda p: p[0])
        x = float(max_x) + _NODE_PLACEMENT_X_OFFSET
        y = float(at_y) if isinstance(at_y, (int, float)) else _NODE_PLACEMENT_DEFAULT[1]
    else:
        x, y = _NODE_PLACEMENT_DEFAULT
    created = {"id": str(uuid.uuid4()), "type": node_type, "content": node_content, "x": x, "y": y}
    if goal:
        created["goal"] = goal
    if title:
        created["title"] = title
    if appearance:
        created["metadata"] = {"appearance": dict(appearance)}
    nodes.append(created)
    return created


def _apply_node_create(
    user_key: str,
    project_id: str,
    attachment_id: str,
    proposal_id: str,
    spec: dict,
    proposal: dict,
    session_id: object,
) -> dict:
    """The dev/48 apply: insert ONE new node of a re-validated template.

    The node id is server-minted HERE (collision-impossible, never from any
    param); the template is re-validated against the packages registry — a
    package uninstalled between mint and apply is the creation analogue of
    dev/41's digest drift (409 + ``stale``)."""
    node_type = proposal.get("nodeType")
    entry, err = agents_roster._available_template(user_key, project_id, node_type)
    if entry is None:
        raise agents_store._mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"the node type is no longer available ({err}) — ask the agent to propose again",
        )
    created = _insert_node(
        spec, node_type, proposal.get("content", ""), proposal.get("goal"),
        appearance=proposal.get("appearance"),  # dev/89: typed round-trip
        title=proposal.get("title"),  # dev/105 A2: the header the note renders
    )
    proposal["status"] = "applied"
    projects_storage.write_spec(user_key, project_id, spec)
    agents_store._log_applied_turn(
        user_key, project_id, session_id, attachment_id, proposal_id,
        f"Applied: node created ({created['id']}).",
        "Applied: node created",
        [f"{entry['label']} · {node_type}", f"node {created['id']}", f"proposal {proposal_id[:8]}"],
    )
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": "applied",
        "mutationApplied": True,
        # Consumed by the frontend canvas bridge (dev/48 §3.3) — the apply
        # response is the only carrier of the created node.
        "createdNode": dict(created),
    }


def dismiss_proposal(
    user_key: str, project_id: str, attachment_id: str, proposal_id: str
) -> dict:
    """Dismiss a pending proposal (keeps its outcome visible on the card)."""
    spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
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
    # A dismissed plan review returns the builder session to its prior phase
    # (dev/52 DR-2): applied when an earlier plan landed, else idle.
    if proposal.get("tool") == "dataflow.plan.write":
        session = record.get("builderSession") or {}
        session["phase"] = "applied" if session.get("appliedPlanId") else "idle"
        session.pop("planProposalId", None)
        record["builderSession"] = session
    projects_storage.write_spec(user_key, project_id, spec)
    session_id = record.get("sessionId")
    if isinstance(session_id, str):
        sessions.update_proposal_status(
            user_key, project_id, session_id, proposal_id, "dismissed"
        )
    return {"attachmentId": attachment_id, "proposalId": proposal_id, "status": "dismissed"}
