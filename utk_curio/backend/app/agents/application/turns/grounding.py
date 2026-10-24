"""Grounding context and gates for generated content: catalog refs, session evidence, source resolvers, dataset paths, secrets, egress budgets, remedies.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import logging

from utk_curio.backend.app.agents.application import dataflow_block as agents_dataflow_block
from utk_curio.backend.app.agents.application import delegation
from utk_curio.backend.app.agents.application import source_grounding
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application import tools
from utk_curio.backend.app.agents.application import verify
from utk_curio.backend.app.agents.infrastructure import egress
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.agents.repositories import project_agents
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.agents.application import catalog as agents_catalog
from utk_curio.backend.app.agents.application import dataset_resolution as agents_dataset_resolution
from utk_curio.backend.app.agents.application.proposals import acquire as agents_acquire
from utk_curio.backend.app.agents.application.proposals import mint as agents_mint
from utk_curio.backend.app.agents.application.solve import budgets as agents_budgets
from utk_curio.backend.app.agents.application.turns import roster as agents_roster
from utk_curio.backend.app.agents.domain import document_validation
from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code
from utk_curio.backend.app.execution import workflow_spec
from utk_curio.backend.app.projects import storage as projects_storage
from utk_curio.backend.app.agents.domain import agent_text

log = logging.getLogger(__name__)


def _resolve_catalog_execution_paths(project_id: str, dataset_ids: list) -> dict:
    """dev/115: ``{datasetId: absolutePath}`` for every id a Solve batch may
    load — resolved ONCE in the request thread the way ``/processPythonCode``
    does (contained paths only); fail-open to ``{}``."""
    ids = [str(i) for i in dataset_ids if i][:64]
    if not ids:
        return {}
    try:
        from flask import g, has_request_context

        from utk_curio.backend.app.datasets.application.catalog_service import (
            DatasetCatalogService,
        )

        user = getattr(g, "user", None) if has_request_context() else None
        return dict(
            DatasetCatalogService(user).resolve_execution_paths(ids, dataflow_id=project_id) or {}
        )
    except Exception:
        log.warning("Could not resolve catalog execution paths for project %s",
                    project_id, exc_info=True)
        return {}


def _dataset_path_topup(project_id: str, user_obj, mapping: dict, ids: list) -> dict:
    """Resolve dataset ids the eager mapping does not have, as *user_obj*.

    dev/131 F4, closed by dev/132: the sandbox path mapping is resolved when a
    Solve starts (dev/115's rule — the job thread holds no request context), so
    a dataset that appeared DURING the session — the user importing the file a
    portal row's steps described, or installing one from the catalog — had no
    path inside the running job and its node stayed pending until the next
    Solve. The acting user is what the resolution actually needs, and a job can
    hold that from its start; the top-up caches into the same mapping, so one
    new id costs one lookup per session.
    """
    missing = [i for i in ids if i and i not in mapping]
    if not missing or user_obj is None:
        return mapping
    try:
        from utk_curio.backend.app.datasets.application.catalog_service import (
            DatasetCatalogService,
        )

        resolved = DatasetCatalogService(user_obj).resolve_execution_paths(
            missing, dataflow_id=project_id
        ) or {}
    except Exception:  # noqa: BLE001 — an unresolvable id fails loudly IN the sandbox
        log.warning("Could not top up catalog paths for project %s", project_id,
                    exc_info=True)
        return mapping
    for dataset_id, path in resolved.items():
        mapping[str(dataset_id)] = path
    return mapping


def _dataset_ids_in(codes: list) -> list[str]:
    """Every Data Catalog id these codes reference, through
    ``curio_data_path("<id>")`` or ``curio_load_collection("<id>")``: the ids
    Play maps (``code_refs.dataset_ids_in_code``), since a collection's loader
    reads its index through the same path map (#597)."""
    out: list[str] = []
    for code in codes:
        for dataset_id in dataset_ids_in_code(code):
            if dataset_id not in out:
                out.append(dataset_id)
    return out


def _session_dataset_paths(project_id: str, user_obj, mapping: dict, codes: list) -> dict:
    """The paths *codes* need — from the eager mapping, topped up for anything
    that arrived since the session started (dev/131 F4)."""
    ids = _dataset_ids_in(codes)
    if ids:
        _dataset_path_topup(project_id, user_obj, mapping, ids)
    return _filter_dataset_paths(mapping, codes)


def _filter_dataset_paths(mapping: dict, codes: list) -> dict:
    """The subset of a precomputed mapping that *codes* reference — pure, so a
    worker thread can call it."""
    if not mapping:
        return {}
    out: dict = {}
    for code in codes:
        for dataset_id in dataset_ids_in_code(code):
            if dataset_id in mapping:
                out[dataset_id] = mapping[dataset_id]
    return out


def _exec_dataset_paths(project_id: str, *codes: str) -> dict:
    """dev/115: the ``{datasetId: absolutePath}`` mapping the sandbox needs for
    every ``curio_data_path("<id>")`` and ``curio_load_collection("<id>")`` call
    in *codes* — resolved the way ``/processPythonCode`` resolves it
    (``resolve_execution_paths``, contained paths only). Fail-open to ``{}``:
    an unmapped id raises a clear per-id error inside the sandbox, which the
    correction loop then sees. Needs the request context (``g.user``); a Solve
    batch precomputes it in the request thread and hands the mapping to its
    workers."""
    ids = _dataset_ids_in(list(codes))[:32]
    if not ids:
        return {}
    try:
        from flask import g, has_request_context

        from utk_curio.backend.app.datasets.application.catalog_service import (
            DatasetCatalogService,
        )

        user = getattr(g, "user", None) if has_request_context() else None
        resolved = DatasetCatalogService(user).resolve_execution_paths(
            ids, dataflow_id=project_id
        )
        return dict(resolved or {})
    except Exception:  # resolution must never fail a validation run
        log.warning(
            "Could not resolve dataset paths for a validation run (project %s)",
            project_id, exc_info=True,
        )
        return {}


def _ungrounded_remedy(attachment_id: str | None = None, *, name: str | None = None) -> str:
    """The ONE sentence an ``ungrounded-source`` failure ends with (dev/126).

    Discovery is initiated at the node, so the sentence names the agent that
    finds the node's datasets: *name*, as its manifest gives it, or the shipped
    card that declares ``dataset.discover``; and with *attachment_id*, the
    node's own attachment of it."""
    finder = name or agents_spec_reads._shipped_name_declaring("dataset.discover") or "an agent that finds datasets"
    if attachment_id:
        return f"; open {finder} on this node to pick a source, or give the path"
    return f"; resolve the source with {finder} (attach it to this node) or give the path"


def _source_missing_remedy(remedy: dict | None) -> str:
    """The sentence a ``source-missing`` failure ends with (dev/116), written
    to be appended as it is (:func:`_then_sentence`): it starts with a capital
    and ends with its full stop."""
    if isinstance(remedy, dict) and remedy.get("kind") == "connection-key" and remedy.get("host"):
        return f"Add a connection key for {remedy['host']} (API Settings, API keys), then Solve again."
    if isinstance(remedy, dict) and remedy.get("kind") == "use-connection-key" and remedy.get("host"):
        name = f' "{remedy["name"]}"' if remedy.get("name") else ""
        return f"A connection key{name} is saved for {remedy['host']}. Solve again so the builder uses it."
    return "Provide what it names (a key, a path or a URL), then Solve again."


def _then_sentence(text: str, sentence: str) -> str:
    """*text*, then *sentence*: *text* ends its own sentence first, with a
    full stop unless it already has one."""
    text = text.rstrip()
    if not text:
        return sentence
    return f"{text}{'' if text.endswith(('.', '!', '?', '…')) else '.'} {sentence}"


def _catalog_rows_for_discovery(user_key: str, project_id: str) -> list[dict]:
    """The project's Data Catalog rows, resolved WHILE A REQUEST CONTEXT EXISTS.

    dev/126, learned from dev/123's field finding: ``catalog.search`` rides the
    request context (the datasets domain is user-object keyed), and a detached
    Solve job has none — so the rows are listed at the entry point and handed
    to the discovery delegate, exactly as dev/115 already resolves the
    execution paths eagerly. Empty on failure: the delegate is then TOLD the
    catalog was unavailable rather than left to imagine it.

    Every row of the listing: the delegate is shown the first of them
    (``delegates._dataset_discover_inputs``), and its candidates, like a
    selection, are checked against all of them (:func:`_grounded_catalog_rows`).
    """
    try:
        return tools._catalog_listing_rows(user_key, project_id, {})
    except Exception:  # noqa: BLE001
        log.warning("Data Catalog listing unavailable for project %s", project_id,
                    exc_info=True)
        return []


def _node_grounded_literal(node: dict, ctx, *, extra_texts=()) -> str | None:
    """The literal that ALREADY grounds this node's source, or None (dev/126).

    Deliberately narrow. Only human-authored text counts — the node's own goal,
    the dataflow's mission and the user's message — never the node's current
    content: a path the model wrote is what the DEC-072 gate exists to refuse,
    and letting it stand in here would ground a node on its own hallucination.
    A batch's grounding context is shared by every target node, so the scan is
    over THIS node's texts rather than over the context's own path set.
    """
    if ctx is None:
        return None
    texts = [str(node.get("goal") or ""), *[str(t or "") for t in extra_texts]]
    joined = " ".join(texts)
    for path in sorted(source_grounding.user_paths(texts)):
        return path
    for dataset_id in sorted(getattr(ctx, "catalog_ids", None) or {}):
        if dataset_id and dataset_id in joined:
            return f'curio_data_path("{dataset_id}")'
    for url in sorted(getattr(ctx, "verified_urls", None) or {}):
        if url and url in joined:
            return url
    if source_grounding.synthetic_requested(texts):
        return "synthetic data (the goal asks for it)"
    return None


def _project_grounded_literal(ctx) -> str | None:
    """Project-wide grounding: the Data Catalog the content child is handed.

    dev/126: the catalog IS a grounded source (``DEC-072``) — the child gets
    its rows and the gate accepts the row it loads — so a project that holds
    datasets grounds a FIRST attempt without a review gate. It is not evidence
    about this node, so it ranks below a pending candidates card, and when the
    catalog turns out not to cover the node the ROUND says so and discovery is
    initiated on that evidence instead of on a guess.
    """
    catalog = getattr(ctx, "catalog_ids", None) or {}
    if catalog:
        return f"the project's Data Catalog ({len(catalog)} dataset(s))"
    return None


def _source_resolver(
    user_key: str,
    project_id: str,
    *,
    coord: str,
    attachment_id: str | None,
    execution_id: str,
    config: ProviderConfig,
    manifest=None,
    extra_texts=(),
    catalog_rows: list | None = None,
):
    """dev/126: the callable the content loop consults BEFORE generating for a
    data-loading node — the one place resolution initiates discovery.

    Same policy on all three resolution paths (the Solve batch, the per-node
    Solve, Simulation Mode's validate): a node whose source is already
    grounded proceeds and the skip is recorded; an unresolved one gets ONE
    ``dataset.discover`` delegation whose candidates await the user in that
    node's own Dataset Finder chat; a node already awaiting the user spends
    nothing at all.
    """
    parent_manifest = manifest if manifest is not None else agents_catalog._resolve_definition(user_key, coord)

    def _resolve(node: dict, grounding_ctx, *, stage: str = "pre") -> dict:
        """``stage="pre"``: before round 0, when nothing in the project could
        ground this node's source. ``stage="post"``: after a round failed FOR
        its source — the gate refused the literal the builder wrote, or the
        builder declined — which is evidence no heuristic can override."""
        from utk_curio.backend.app.projects import storage as projects_storage

        node_id = str(node.get("id") or "")
        spec = projects_storage.read_spec(user_key, project_id)
        literal = (
            _node_grounded_literal(node, grounding_ctx, extra_texts=extra_texts)
            if stage == "pre" else None
        )
        project_literal = (
            _project_grounded_literal(grounding_ctx) if stage == "pre" else None
        )
        state = agents_dataset_resolution.node_source_state(
            spec, node_id, grounded_literal=literal, project_literal=project_literal,
            user_key=user_key,
        )
        if state["state"] == agents_dataset_resolution.STATE_RESOLVED:
            skip_literal = literal or project_literal
            if skip_literal and state.get("attachmentId"):
                with projects_storage.spec_write_lock(user_key, project_id):
                    fresh = projects_storage.read_spec(user_key, project_id)
                    if fresh is not None and agents_dataset_resolution.mark_skipped(
                        fresh, state["attachmentId"], literal=skip_literal
                    ):
                        projects_storage.write_spec(user_key, project_id, fresh)
            return {
                "state": "resolved",
                "detail": state["detail"] or (skip_literal or ""),
                "confirmedSource": agents_dataset_resolution.confirmed_source(
                    spec, node_id, user_key=user_key,
                ),
            }
        if state["state"] != agents_dataset_resolution.STATE_UNRESOLVED:
            # Candidates (or a reviewed install) already await the user: say so
            # without spending a model call on a second identical card.
            return {"state": "awaiting", "detail": state["detail"],
                    "attachmentId": state["attachmentId"]}
        started = agents_dataset_resolution.initiate(
            user_key, project_id, node,
            config=config,
            parent_manifest=parent_manifest,
            parent_coord=coord,
            parent_execution_id=execution_id,
            parent_attachment_id=attachment_id,
            mission=" — ".join(
                t for t in [str(node.get("goal") or ""), *[str(x or "") for x in extra_texts]]
                if t
            )[:2000],
            catalog_rows=catalog_rows,
        )
        if started["status"] == "awaiting":
            return {"state": "awaiting", "detail": started["detail"],
                    "attachmentId": started.get("attachmentId")}
        # Discovery ran and found nothing usable, or the specialist could not
        # run at all. "Awaiting your selection" would be a lie — there is
        # nothing to select — so the node keeps its own honest outcome and the
        # discovery attempt rides along as the reason it stays unresolved.
        return {"state": "unresolved", "detail": started["detail"],
                "attachmentId": started.get("attachmentId"),
                "discovery": started["status"]}

    return _resolve


def _verify_candidate_parts(parts: list, loop_ctx: dict | None = None) -> None:
    """dev/67-4 (DEC-053): the Dataset Finder stops laundering — external
    candidate rows are verified DETERMINISTICALLY before they reach the user.
    URL-bearing rows are probed through the egress policy (first 4 — the
    run-budget shape; provider refinements like Socrata add dataset
    name/columns on top of the generic gate, which covers ANY dataset API);
    URL-less rows are loudly UNVERIFIED. The evidence rides the row into the
    card and the Node Builder handoff."""
    # One budget for the whole pass, spent per real HTTP request rather than
    # per row. The old counter ticked once per candidate while a single row
    # could issue a dozen requests (a Socrata probe fetched twice, and every
    # fetch follows up to MAX_REDIRECTS hops), so the documented bound of
    # MAX_CALLS_PER_RUN bore no relation to what actually went out.
    # dev/114: the budget is the RUN's when a loop context rides along — the
    # grounding gate's mint-time probes and this pass spend the same four
    # requests — and every verified row is remembered so a same-run
    # confirmation grounds its URL without re-spending.
    budget = (
        _run_egress_budget(loop_ctx)
        if loop_ctx is not None
        else egress.CallBudget(agents_budgets._RUN_EGRESS_CALLS)
    )
    roster = agents_roster._LazyRoster()
    for part in parts:
        if not isinstance(part, dict) or part.get("type") != "datasetCandidates":
            continue
        lanes = part.get("lanes") or {}
        for row in lanes.get("external") or []:
            if not isinstance(row, dict):
                continue
            url = row.get("url")
            if not url:
                row["verification"] = verify.verify_external_source(None)
            elif budget.exhausted:
                row["verification"] = {
                    "status": "unverified",
                    "detail": "the egress budget was spent before this row, so it was not checked",
                }
            else:
                row["verification"] = verify.verify_external_source(url, budget=budget)
                if loop_ctx is not None and row["verification"].get("status") == "verified":
                    loop_ctx.setdefault("_verified_urls", {})[url] = row["verification"]
            agents_mint._mint_row_access(row)
            agents_acquire._mint_row_acquirable(row, roster, budget)


def _grounded_catalog_rows(rows: list, listing: list) -> tuple[list, int]:
    """The catalog-lane candidate *rows* whose ``datasetId`` the Data Catalog
    *listing* holds, and how many it dropped. A kept row says installed or not
    as the listing does, never as the reply did, and is named as the listing
    names it when the reply named it nothing."""
    listed = {str(r.get("id")): r for r in listing or [] if isinstance(r, dict) and r.get("id")}
    kept = []
    for row in rows:
        found = listed.get(str(row.get("datasetId"))) if isinstance(row, dict) else None
        if found is None:
            continue
        row["installed"] = bool(found.get("installed"))
        row.setdefault("name", found.get("name"))
        row.setdefault("sourceType", "catalog")
        kept.append(row)
    return kept, len(rows) - len(kept)


#: What a reply's candidates card becomes when none of its rows is left: the
#: user reads why, in place of a card with nothing to select.
_NO_CANDIDATES_CARD = {
    "type": "card",
    "kind": "error",
    "title": "No dataset candidates",
    "lines": ["None of the datasets this reply proposed is in your Data Catalog."],
}


def _ground_catalog_lanes(parts: list, listing) -> None:
    """A run's own candidates cards, checked as a delegated card is
    (``delegates._mint_candidates_from_delegate``): a catalog row stays only
    when the Data Catalog listing holds its dataset, and says installed or not
    as the listing does (:func:`_grounded_catalog_rows`). A card left with no
    row is replaced by :data:`_NO_CANDIDATES_CARD`. *listing* returns the
    listing's rows; it is called once, and only when a card holds a catalog
    row."""
    rows = None
    for index, part in enumerate(parts):
        if not isinstance(part, dict) or part.get("type") != "datasetCandidates":
            continue
        lanes = part.get("lanes") or {}
        if not lanes.get("catalog"):
            continue
        if rows is None:
            rows = listing()
        lanes["catalog"], _dropped = _grounded_catalog_rows(lanes["catalog"], rows)
        if not any(lanes.get(lane) for lane in ("catalog", "external")):
            parts[index] = {**_NO_CANDIDATES_CARD, "lines": list(_NO_CANDIDATES_CARD["lines"])}


def _run_egress_budget(loop_ctx: dict) -> "egress.CallBudget":
    """dev/114: ONE egress budget per run (or per Solve batch) — created lazily
    on the loop context, shared by candidate verification and the grounding
    gate's probes, so ``MAX_CALLS_PER_RUN`` means the run's total."""
    budget = loop_ctx.get("_egress_budget")
    if budget is None:
        budget = egress.CallBudget(int(loop_ctx.get("_egress_limit") or agents_budgets._RUN_EGRESS_CALLS))
        loop_ctx["_egress_budget"] = budget
    return budget


def _catalog_listing_items(project_id: str) -> list | None:
    """The datasets the datasets domain lists for this project, the SAME
    listing ``catalog.search`` serves, read as the request's account; None,
    logged, when the catalog cannot be read."""
    try:
        from flask import g, has_request_context

        from utk_curio.backend.app.datasets.application.catalog_service import (
            DatasetCatalogService,
        )

        user = getattr(g, "user", None) if has_request_context() else None
        listing = DatasetCatalogService(user).list_catalog(dataflow_id=project_id)
    except Exception:  # a broken catalog is data, never a run error
        log.warning(
            "Could not read the Data Catalog for source grounding (project %s): "
            "catalog paths are treated as unknown this run", project_id, exc_info=True,
        )
        return None
    return [item for item in (listing or {}).get("items") or [] if isinstance(item, dict)]


def _catalog_grounding_refs(project_id: str, items: list | None = None) -> tuple[dict, dict]:
    """dev/114: ``(by_path, by_id)``, the datasets the datasets domain lists
    for this project, the SAME listing ``catalog.search`` serves, so a row the
    tool showed is grounded by construction: by resolved path (the historical
    literal form) and by id (the portable ``curio_data_path("<id>")`` call
    the loader recipe emits, resolved by the sandbox at run time). A failing
    catalog read degrades to empty maps (logged): the gate still refuses
    ungrounded sources, honestly, rather than inventing a neighborhood.
    *items*, the listing when the caller read it already, spares a second
    read (:func:`_catalog_listing_items`)."""
    if items is None:
        items = _catalog_listing_items(project_id)
    by_path: dict = {}
    by_id: dict = {}
    for item in items or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        path = item.get("path")
        ref = source_grounding.CatalogRef(
            dataset_id=str(item.get("id")),
            title=str(item.get("title") or item.get("id") or ""),
            format=str(item.get("format") or ""),
            path=path if isinstance(path, str) else "",
        )
        by_id[ref.dataset_id] = ref
        if isinstance(path, str) and path.strip():
            by_path[path] = ref
    return by_path, by_id


def _session_grounding_evidence(
    user_key: str, project_id: str, loop_ctx: dict
) -> tuple[list[str], dict]:
    """dev/114: what this conversation already established — the user's own
    texts (the current message first) and every candidate row the runtime
    verified (persisted turns + this run's ``_verified_urls``)."""
    texts: list[str] = []
    verified: dict = {}
    message = loop_ctx.get("message")
    if isinstance(message, str) and message.strip():
        texts.append(message)
    session_id = loop_ctx.get("session_id")
    if isinstance(session_id, str):
        try:
            turns = sessions.read_turns(user_key, project_id, session_id)
        except Exception:
            turns = []
        for turn in turns:
            if turn.get("role") == "user" and isinstance(turn.get("text"), str):
                texts.append(turn["text"])
            for part in turn.get("content") or []:
                if not isinstance(part, dict) or part.get("type") != "datasetCandidates":
                    continue
                for row in ((part.get("lanes") or {}).get("external") or []):
                    if not isinstance(row, dict):
                        continue
                    evidence = row.get("verification")
                    if (
                        isinstance(row.get("url"), str)
                        and isinstance(evidence, dict)
                        and evidence.get("status") == "verified"
                    ):
                        verified[row["url"]] = evidence
    for url, evidence in (loop_ctx.get("_verified_urls") or {}).items():
        verified[url] = evidence
    return texts, verified


def _grounding_context(
    user_key: str,
    project_id: str,
    loop_ctx: dict,
    *,
    node_type: object,
    params: dict | None = None,
    extra_texts: tuple = (),
    base: dict | None = None,
    is_data_loading: bool | None = None,
    request_texts: tuple = (),
    requested_ids=(),
    code_engine: str | None = None,
    chips: dict | None = None,
) -> "source_grounding.GroundingContext":
    """dev/114 (DEC-072): everything the gate needs for ONE mint — catalog
    paths, the conversation's evidence, the run-budgeted prober, and the
    grant-aware corrective routes. ``base`` (a Solve batch's precomputed
    catalog paths / texts / verified map) replaces the per-mint reads.

    #411: the datasets the content must read are ``_requested_dataset_ids``
    plus ``requested_ids`` (the catalog rows the user confirmed for a Solve
    node).

    *code_engine* is the engine the node's code runs in
    (``source_grounding.code_engine``), None for content that is no code: the
    gate holds the code's calls to it, and a Python node's imports to the
    modules a run hands it. *chips* are what a run resolves the node's chips
    with (:func:`_chip_context`), None where there is no dataflow."""
    from utk_curio.backend.app.packages import service as packages_services

    if is_data_loading is None:
        is_data_loading = bool(node_type) and source_grounding.loads_dataset(
            node_type, packages_services.roster_templates(user_key, project_id),
        )
    base_of = base if base is not None else {}
    if base is not None:
        catalog_paths = base.get("catalog_paths") or {}
        catalog_ids = base.get("catalog_ids") or {}
        texts = list(base.get("texts") or [])
        verified = dict(base.get("verified") or {})
        secrets = dict(base["secrets"]) if "secrets" in base else _connection_key_refs(user_key)
    else:
        catalog_paths, catalog_ids = _catalog_grounding_refs(project_id)
        texts, verified = _session_grounding_evidence(user_key, project_id, loop_ctx)
        secrets = _connection_key_refs(user_key)
    models = dict(base_of["models"]) if "models" in base_of else _model_refs(user_key)
    reachable, package_modules = None, None
    if code_engine == "python" and node_type:
        package_modules = (
            base_of["package_modules"] if "package_modules" in base_of else _package_modules(user_key, project_id)
        )
        reachable = _reachable_modules(user_key, node_type, project_id)
    texts.extend(t for t in extra_texts if isinstance(t, str) and t.strip())
    budget = _run_egress_budget(loop_ctx)
    cache: dict = loop_ctx.setdefault("_probe_cache", {})

    def _probe(url: str, *, headers=None, params=None) -> dict:
        keyed = bool(headers or params)
        if not keyed and url in cache:
            return cache[url]
        if budget.exhausted:
            return {
                "status": "unverified",
                "detail": agent_text.message("grounding.probe-budget-spent"),
            }
        if keyed:
            # dev/116: a probe carrying a connection key is evidence for ONE
            # correction — never cached under the bare URL, never a verified
            # source (the caller redacts the outcome).
            return verify.verify_external_source(url, budget=budget, headers=headers, params=params)
        result = verify.verify_external_source(url, budget=budget)
        cache[url] = result
        if result.get("status") == "verified":
            loop_ctx.setdefault("_verified_urls", {})[url] = result
            # The context's own map too: a URL the gate verified THIS run is
            # evidence the next correction round is handed (dev/115 field fix,
            # 2026-09-08 — the current content's Census URL passed the gate by
            # probe, the correction saw an empty ``verifiedUrls`` and the
            # content builder rightly declined to write code).
            verified[url] = result
        return result

    hints: list[str] = []
    if "catalog.search" in (loop_ctx.get("granted") or []):
        hints.append(agent_text.message("grounding.hint-catalog-search"))
    if _delegates_discovery(user_key, project_id, loop_ctx.get("manifest")):
        hints.append(
            agent_text.message("grounding.hint-discover")
        )
    elif verified:
        hints.append(agent_text.message("grounding.hint-verified-url"))
    hints.append(
        agent_text.message("grounding.hint-synthetic")
    )
    if secrets:
        hints.append(
            agent_text.message(
                "grounding.hint-connection-key",
                use_lines="; ".join(
                ref.use_line for ref in list(secrets.values())[:6]
            ),
            )
        )
    secret_values = _exec_secrets_resolver(user_key)
    return source_grounding.GroundingContext(
        catalog_paths=catalog_paths,
        catalog_ids=catalog_ids,
        user_paths=source_grounding.user_paths(texts),
        verified_urls=verified,
        synthetic_requested=source_grounding.synthetic_requested(texts, params),
        is_data_loading=is_data_loading,
        probe=_probe,
        hints=hints,
        secrets=secrets,
        secret_values=lambda names: secret_values(
            [f'curio_secret("{n}")' for n in names]
        ),
        requested_dataset_ids=(
            _requested_dataset_ids(loop_ctx, request_texts, catalog_ids) | set(requested_ids)
        ),
        code_engine=code_engine,
        models=models,
        reachable_modules=reachable,
        package_modules=package_modules,
        chips=chips,
    )


def _delegates_discovery(user_key: str, project_id: str, manifest) -> bool:
    """Whether *manifest*'s agent asks another for datasets: its delegation
    paragraph offers ``dataset.discover`` (``delegation.offered_capability_entries``,
    the list the run is given)."""
    if not getattr(manifest, "delegates_to", None):
        return False
    try:
        spec = projects_storage.read_spec(user_key, project_id) or {}
        installed = set(project_agents.project_agents(spec))
        return any(
            capability == "dataset.discover"
            for capability, _name in delegation.offered_capability_entries(user_key, installed, manifest)
        )
    except Exception:  # noqa: BLE001 - an unreadable definition delegates nothing
        return False


def _requested_dataset_ids(loop_ctx: dict, request_texts: tuple, catalog_ids: dict) -> set[str]:
    """#411: the catalog ids named in the message this run answers, or in
    ``request_texts`` (a Solve node's own goal). #867: a message that names
    none, such as "go ahead", acts on the user's previous message, so the ids
    that one names are requested. An id in an older turn, the dataflow's task
    or another node's goal restricts nothing."""
    named = source_grounding.named_dataset_ids([loop_ctx.get("message"), *request_texts], catalog_ids)
    if named:
        return named
    return source_grounding.named_dataset_ids([loop_ctx.get("previous_message")], catalog_ids)


def _gate_generated_content(
    user_key: str,
    project_id: str,
    loop_ctx: dict,
    *,
    code: str,
    engine: object,
    node_type: object,
    params: dict | None = None,
    extra_texts: tuple = (),
    base: dict | None = None,
    is_data_loading: bool | None = None,
    request_texts: tuple = (),
    requested_ids=(),
    chips: dict | None = None,
    node_id: str | None = None,
    widgets: list | None = None,
) -> tuple["source_grounding.GroundingVerdict", str | None]:
    """The ONE call every agent-authored-content boundary makes (dev/114):
    ``(verdict, refusal_text | None)``. The refusal is model-correctable
    (DEC-067) and names only routes this run can take. *engine* is the one
    the node's code runs in (``source_grounding.code_engine``), None for
    content that is no code, which is read as a document; *chips*, what a
    run resolves the node's chips with (:func:`_chip_context`). Content whose
    sources are grounded and that is a chart's or a map's document is then
    checked as Solve checks one (:func:`_document_refusal`), for *node_id*'s
    saved node, or for the node a proposal creates with the *widgets* it
    declares: its refusal comes with a verdict that is ``ok``."""
    code_engine = engine if isinstance(engine, str) and engine else None
    ctx = _grounding_context(
        user_key, project_id, loop_ctx, node_type=node_type, params=params,
        extra_texts=extra_texts, base=base, is_data_loading=is_data_loading,
        request_texts=request_texts, requested_ids=requested_ids, code_engine=code_engine, chips=chips,
    )
    verdict = source_grounding.check_grounding(code, code_engine or "python", ctx)
    if not verdict.ok:
        return verdict, source_grounding.refusal_text(verdict, ctx)
    return verdict, _document_refusal(user_key, project_id, node_type, code, node_id=node_id, widgets=widgets)


#: The id the node a proposal creates goes by while its document is checked.
_PROPOSED_NODE_ID = "__proposed__"


def _document_refusal(
    user_key: str, project_id: str, node_type: object, code: object, *,
    node_id: str | None = None, widgets: list | None = None,
) -> str | None:
    """Why a chart's or a map's document an agent wrote does not validate, as
    Solve's document check says it (``document_validation``), or None; None
    for any other content. Its fields are not held to columns: a proposal's
    run is never handed its inputs' columns (DEC-063)."""
    if not isinstance(node_type, str) or not node_type or not isinstance(code, str):
        return None
    from utk_curio.backend.app.packages import service as packages_services

    try:
        templates = {t["id"]: t for t in packages_services.available_templates(user_key, project_id)}
    except Exception:  # noqa: BLE001 - an unreadable roster falls to the offline tables
        templates = {}
    grammar_id = workflow_spec.grammar_id_of(node_type, templates)
    grammar = document_validation.grammar_of(node_type, grammar_id)
    if grammar is None:
        return None
    row = templates.get(node_type.split("@", 1)[0]) or {}
    verdict = document_validation.validate(
        node_type, _proposed_document(user_key, project_id, node_type, code, node_id, widgets, templates, grammar),
        grammar_id=grammar_id, content_kind=row.get("contentKind"),
    )
    if verdict["status"] != document_validation.STATUS_INVALID:
        return None
    return document_validation.refusal_text(node_type, verdict, grammar_id=grammar_id)


def _proposed_document(user_key, project_id, node_type, code, node_id, widgets, templates, grammar) -> str:
    """*code* with its references resolved as far as the dataflow knows them,
    as the canvas resolves them before it draws: the node's widgets, the
    shared tags, its wired inputs and their boxes. The node is *node_id*'s
    saved one, or the one a proposal creates, with the *widgets* it declares.
    A reference nothing resolves yet, such as the input chip of a circle no
    edge reaches, is left as written, and the validator reads it as Solve
    reads one of a node the saved dataflow does not hold."""
    spec_doc = projects_storage.read_spec(user_key, project_id) or {}
    dataflow = spec_doc.get("dataflow") if isinstance(spec_doc.get("dataflow"), dict) else {}
    nodes = [n for n in dataflow.get("nodes") or [] if isinstance(n, dict)]
    if node_id is None:
        node_id = _PROPOSED_NODE_ID
        nodes.append({"id": node_id, "type": node_type, "content": code,
                      "metadata": {"widgets": list(widgets or [])}})
    labels = {template_id: row.get("label") or "" for template_id, row in templates.items() if isinstance(row, dict)}
    try:
        spec = workflow_spec.parse_workflow_dict({**spec_doc, "dataflow": {**dataflow, "nodes": nodes}}, labels=labels)
    except Exception:  # noqa: BLE001 - a dataflow that cannot be read resolves nothing
        return code
    node = next((n for n in spec.nodes if n.id == node_id), None)
    if node is None:
        return code
    resolved, _unresolved_yet = spec.node_code_and_problems(node, "json", code, grammar)
    return resolved


def _loader_calls(kind: str) -> str:
    """The calls the gate reads a Data Catalog item of *kind* (``dataset`` or
    ``collection``) from, as the functions page gives them:
    ``curio_load_data("<id>") or curio_data_path("<id>")``."""
    names = [
        name for name, function in source_grounding.page_functions().items()
        if source_grounding.catalog_kind(function) == kind
    ]
    return " or ".join(f'{name}("<id>")' for name in names)


def _chip_context(spec: dict | None, node_id: object = None, widgets=None) -> dict | None:
    """What a run resolves a node's chips with, as ``WorkflowSpec.node_code``
    gives it: the node's widgets, its wired circles, each with the scenario
    label its rows carry, the dataflow's shared tags and the node's selection
    tags. *widgets* are those of a node the dataflow does not hold yet, as
    node.create proposes it. None without a dataflow."""
    from utk_curio.backend.app.execution import workflow_spec

    if not isinstance(spec, dict):
        return None
    try:
        flow = workflow_spec.parse_workflow_dict(spec)
        node = next((n for n in flow.nodes if n.id == node_id), None) if node_id else None
        labels = flow.input_scenarios(node.id) if node is not None else {}
        return {
            "widgets": list(widgets or []) if node is None else node.widgets,
            "inputs": [
                {"slot": slot, **({"scenario": labels[slot]} if slot in labels else {})}
                for slot in (flow.input_slots(node.id) if node is not None else [])
            ],
            "shared": flow.shared_widgets(),
            "selections": node.selections if node is not None else [],
        }
    except Exception:  # noqa: BLE001 - a dataflow that cannot be read resolves no chip
        log.warning("Could not read the dataflow to resolve chips for source grounding", exc_info=True)
        return None


def _source_grounding_inputs(ctx: "source_grounding.GroundingContext") -> dict:
    """dev/114: the grounding a tool-less content delegate is HANDED (the
    DEC-063 pattern — evidence as inputs): the catalog datasets with their
    real paths, the paths the user typed, the URLs already verified, and the
    rule. Bounded; plain data."""
    datasets = [
        {
            "datasetId": ref.dataset_id,
            "title": ref.title,
            "format": ref.format,
            "use": f'dataset_path = curio_data_path("{ref.dataset_id}")',
            **({"path": ref.path} if ref.path else {}),
        }
        for ref in list(ctx.catalog_ids.values())[:24]
    ]
    secrets = [
        {
            "name": ref.name,
            "host": ref.host,
            "delivery": ref.delivery,
            "use": ref.use_line,
        }
        for ref in list((ctx.secrets or {}).values())[:24]
    ]
    return {
        "catalogDatasets": datasets,
        "userPaths": sorted(ctx.user_paths)[:24],
        "verifiedUrls": sorted(ctx.verified_urls)[:24],
        "availableSecrets": secrets,
        "syntheticRequested": bool(ctx.synthetic_requested),
        "rule": agent_text.message(
            "grounding.source-rule", dataset_calls=_loader_calls('dataset'),
            collection_calls=_loader_calls('collection'),
            keyed_host=" " + agent_text.message("grounding.source-rule-keyed-host")
                if secrets else
                " " + agent_text.message("grounding.source-rule-no-key"),
            synthetic=" " + agent_text.message("grounding.source-rule-synthetic")
                if ctx.synthetic_requested else "",
        ),
    }


def _model_refs(user_key: str) -> dict[str, tuple[int, ...]]:
    """The models this account has added, ``{model id: (major, ...)}``: the
    model packages its store holds, which ``models.search`` lists and a
    node's ``curio_load_model`` runs. A store that cannot be read holds
    none, so the gate refuses every model, as it does every key."""
    from utk_curio.backend.app.packages import service as packages_services

    try:
        held = packages_services.held_model_packages(user_key)
    except Exception:  # noqa: BLE001 - an unreadable store adds no model
        log.warning("Could not read the models of %s for source grounding", user_key, exc_info=True)
        return {}
    models: dict[str, set[int]] = {}
    for item in held:
        if item.folder.name == item.manifest.dir_name:
            models.setdefault(item.manifest.package_id, set()).add(item.manifest.major)
    return {model_id: tuple(sorted(majors)) for model_id, majors in models.items()}


def _package_modules(user_key: str, project_id: str) -> dict:
    """Every module a package ships, by name, with the nodes that import it
    (``packages.module_index``). It never raises: what it cannot read adds
    nothing, so the gate judges no import of it."""
    from utk_curio.backend.app.packages import service as packages_services

    return packages_services.module_index(user_key, project_id)


def _reachable_modules(user_key: str, node_type: object, project_id: str) -> frozenset[str]:
    """The modules a run hands a node of *node_type* (``packages.modules_for_node``,
    the run's own reader): those of its package and of the packages it
    depends on. A built-in node gets none."""
    from utk_curio.backend.app.packages import service as packages_services

    found = packages_services.modules_for_node(user_key, node_type, project_id)
    sources = found if isinstance(found, list) else [found] if isinstance(found, dict) else []
    return frozenset(name for source in sources for name in source.get("names") or ())


def _connection_key_refs(user_key: str) -> dict:
    """dev/116: the user's saved connection keys as ``SecretRef``s (names,
    hosts, delivery — never values). Read in the request thread; a missing or
    unreadable store is simply no keys."""
    from utk_curio.backend.app.users.connection_keys import default_store

    try:
        return {
            ref.name: source_grounding.SecretRef(ref.name, ref.host, ref.delivery)
            for ref in default_store().list(user_key)
        }
    except Exception:
        return {}


def _exec_secrets_resolver(user_key: str):
    """dev/116: ``codes -> {name: value}`` for the ``curio_secret("<name>")``
    calls in *codes* — the ONE reader of values on the agent path. The user
    key is captured here (request thread); the store needs no request context,
    so a job thread may call the closure per round (dev/115 lesson 1)."""
    from utk_curio.backend.app.users.connection_keys import default_store, secret_names

    def _resolve(codes) -> dict:
        names: list[str] = []
        for code in codes or ():
            for name in secret_names(code):
                if name not in names:
                    names.append(name)
        if not names:
            return {}
        try:
            return default_store().resolve(user_key, names)
        except Exception:
            return {}

    return _resolve


def _solve_grounding_base(
    user_key: str, project_id: str, spec: dict | None, nodes_by_id: dict, targets: list
) -> dict:
    """dev/114: ONE grounding base per Solve batch, built in the request
    thread (workers hold no request context): catalog paths, the mission and
    plan texts (the human-authored intents), the session-free verified
    map (empty: Solve has no candidates transcript of its own), and the
    account's keys, models and the modules its packages ship."""
    dataflow = (spec or {}).get("dataflow") or {}
    texts = [str(dataflow.get("task") or ""), str(dataflow.get("name") or "")]
    for node_id in targets:
        node = nodes_by_id.get(node_id) or {}
        texts.append(str(node.get("goal") or ""))
    items = _catalog_listing_items(project_id)
    by_path, by_id = _catalog_grounding_refs(project_id, items or [])
    return {
        "catalog_paths": by_path,
        "catalog_ids": by_id,
        "texts": [t for t in texts if t.strip()],
        "verified": {},
        "secrets": _connection_key_refs(user_key),
        "models": _model_refs(user_key),
        "package_modules": _package_modules(user_key, project_id),
        # The dataflow's datasets with their lines, for the dataflow block
        # each node's content-mode runs are given, from the same listing.
        "dataflow_datasets": agents_dataflow_block.datasets_in(items),
    }
