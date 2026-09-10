"""The centralized evaluation service (memo dev/123, ``DEC-079``).

One service owns fixtures, runs, results and scoring; the UI renders state and
calls it. A run goes through the product's own entry points and nothing else:

    projects.services.save_project        # an ISOLATED project
    datasets …install_dataset             # the fixture's declared datasets
    packages_services.install_to_project  # the fixture's declared packages
    agents.services.install_in_project    # the agent + its REQUIRED closure
    agents.services.attach_agent          # a canvas attachment
    agents.services.run_attachment        # the prompt, through the real runtime
    agents.services.apply_proposal        # the same apply a click uses
    agents.services.solve_attachment      # the real Solve, verified

Nothing is reimplemented, no permission is bypassed and no review gate is
skipped. Applying without a click is an automated approval, so every apply
passes :func:`authorization.assert_may_auto_apply` first and is recorded.

The reference dataflow is read **here**, in the scoring phase, after the model
has finished. It never enters a prompt, a run context or a client payload.
"""

from __future__ import annotations

import json
import time
from typing import Iterable, Mapping

from utk_curio.backend.app.agents.evaluation import attempt as attempt_mod
from utk_curio.backend.app.agents.evaluation import authorization as auth_mod
from utk_curio.backend.app.agents.evaluation import policy as policy_mod
from utk_curio.backend.app.agents.evaluation import records as records_mod
from utk_curio.backend.app.agents.evaluation import review as review_mod
from utk_curio.backend.app.agents.evaluation.canonical import TemplateFacts
from utk_curio.backend.app.agents.evaluation.compare import Universe
from utk_curio.backend.app.agents.evaluation.fixtures import fixture_paths, load_fixture
from utk_curio.backend.app.agents.evaluation.report import digest_of

DFB_COORD = "agent.dataflow-builder@1.0.0"

#: A run's wall-clock ceiling. Generous, because a real model plus a real Solve
#: is minutes, and bounded, because an unbounded run is a hung panel.
RUN_DEADLINE_S = 45 * 60


class EvaluationServiceError(Exception):
    """Carries the HTTP status the routes answer with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# ── readiness: is a model configured, and where did it come from ────────────

def readiness(user) -> dict:
    """Whether an evaluation can run at all, and which model would answer.

    The correction's *"actionable blocked state when no LLM is configured"*
    needs one more distinction than "configured or not": a model can come from
    the account's own AI Settings **or** from the deployment's own start flags
    (``curio.py start --llm-provider/--llm-base-url/--llm-model``, and
    ``--guest-llm-api-key`` for the shared guest). Both are real
    configurations, so a panel that only looked at the user row would tell an
    operator who configured the model on the command line that they had not
    configured it.
    """
    from utk_curio.backend import config as backend_config
    from utk_curio.backend.app.agents.provider_config import (
        ProviderConfigError,
        resolve_provider_config,
    )
    from utk_curio.backend.app.agents.evaluation.training_host import host_of

    deployment = {
        "apiType": backend_config.DEFAULT_LLM_API_TYPE or "",
        "baseUrlHost": host_of(backend_config.DEFAULT_LLM_BASE_URL or ""),
        "model": backend_config.DEFAULT_LLM_MODEL or "",
        "hasApiKey": bool(backend_config.DEFAULT_LLM_API_KEY),
    }
    account = {
        "apiType": getattr(user, "llm_api_type", None) or "",
        "baseUrlHost": host_of(getattr(user, "llm_base_url", None) or ""),
        "model": getattr(user, "llm_model", None) or "",
        "hasApiKey": bool(getattr(user, "llm_api_key", None)),
    }
    try:
        config = resolve_provider_config(user, require_model=True)
    except ProviderConfigError as exc:
        return {
            "configured": False,
            "reason": str(exc),
            "source": "none",
            "provider": {"apiType": "", "baseUrlHost": "", "model": ""},
            "account": account,
            "deployment": deployment,
        }
    # Which of the two supplied the model the run will actually use. The
    # resolved config is the truth; these two only explain where it came from.
    source = "account" if account["model"] and account["model"] == config.model else (
        "deployment" if deployment["model"] and deployment["model"] == config.model
        else "account"
    )
    return {
        "configured": True,
        "reason": "",
        "source": source,
        "provider": {
            "apiType": config.api_type or "",
            "baseUrlHost": host_of(config.base_url),
            "model": config.model or "",
        },
        "account": account,
        "deployment": deployment,
    }


def _provider_config(user):
    from utk_curio.backend.app.agents.provider_config import (
        ProviderConfigError,
        resolve_provider_config,
    )

    try:
        return resolve_provider_config(user, require_model=True)
    except ProviderConfigError as exc:
        raise EvaluationServiceError(
            f"{exc} Configure a provider and model in AI Settings, or start "
            "Curio with --llm-provider/--llm-base-url/--llm-model.",
            400,
        ) from exc


# ── fixtures ────────────────────────────────────────────────────────────────

def list_fixtures() -> dict:
    """Every prompt fixture, with what a person needs in order to choose one.

    Includes the prompt itself: the panel shows what will be sent before it is
    sent, and it is also where the prompt gets reviewed (:mod:`.review`).
    """
    out: list = []
    for path in fixture_paths():
        fixture = load_fixture(path)
        out.append({
            "fixtureId": fixture.fixture_id,
            "prompt": fixture.prompt,
            "context": fixture.context,
            "tier": fixture.tier,
            "needs": list(fixture.needs),
            "split": fixture.split,
            "reviewStatus": fixture.review_status,
            "reviewedBy": (fixture.data.get("review") or {}).get("reviewedBy"),
            "reviewedAt": (fixture.data.get("review") or {}).get("reviewedAt"),
            "source": str(fixture.data.get("source", {}).get("path") or ""),
            "required": fixture.required,
            "expectedNodes": len(fixture.expected.get("nodes") or []),
            "expectedEdges": len(fixture.expected.get("edges") or []),
            "skip": fixture.capability.get("skip") or [],
        })
    return {"fixtures": out}


def set_review(fixture_id: str, *, status: str, user) -> dict:
    """Record a prompt review from the panel (the owner's ask, dev/123)."""
    try:
        return review_mod.set_review(fixture_id, status=status, user=user).as_dict()
    except review_mod.ReviewRefused as refusal:
        raise EvaluationServiceError(refusal.message, refusal.status) from refusal


def _fixture_or_refuse(fixture_id: str):
    for path in fixture_paths():
        fixture = load_fixture(path)
        if fixture.fixture_id == fixture_id:
            return fixture
    raise EvaluationServiceError(f"no prompt fixture {fixture_id!r}", 404)


# ── the run ─────────────────────────────────────────────────────────────────

def start(user, user_key: str, fixture_id: str) -> dict:
    """Validate, create the record, and hand the run to a detached job."""
    from utk_curio.backend.app.agents import agent_jobs

    existing = records_mod.in_flight(user_key)
    if existing is not None:
        existing = records_mod.reconcile(user_key, existing)
        if existing.running:
            raise EvaluationServiceError(
                f"an evaluation is already running ({existing.run_id}); wait for "
                "it or cancel it before starting another",
                409,
            )

    fixture = _fixture_or_refuse(fixture_id)
    config = _provider_config(user)

    record = records_mod.EvaluationRecord(
        run_id=records_mod.new_run_id(),
        fixture_id=fixture.fixture_id,
        review_status=fixture.review_status,
        provider={
            "apiType": config.api_type or "",
            "baseUrlHost": _host_of(config.base_url),
            "model": config.model or "",
        },
        digests={
            "fixtureSha256": fixture.fixture_sha256(),
            "promptSha256": fixture.prompt_sha256(),
            "agentInstructionSha256": _instruction_digest(),
            "rosterDigest": "",
        },
    )
    record.append("phase", phase="preparing")
    records_mod.write(user_key, record)

    try:
        agent_jobs.check_can_start(user_key, record.run_id)
    except agent_jobs.JobRefused as refusal:
        raise EvaluationServiceError(str(refusal), refusal.status) from refusal

    agent_jobs.start_job(
        user_key=user_key,
        project_id="",
        attachment_id=record.run_id,   # the run is its own correlation key
        kind="evaluation-run",
        job_id=record.run_id,
        events=_run_events(user, user_key, record.run_id, fixture, config),
    )
    return record.as_dict()


def _run_events(user, user_key: str, run_id: str, fixture, config):
    """The run, as a generator of ``(kind, payload)`` events.

    A generator because that is what ``agent_jobs`` drives: every phase is an
    event a subscriber sees live and a record keeps, and a raised exception
    becomes a terminal error rather than a lost job.

    **It runs inside a request context carrying this user**, and that is not
    incidental. Several production paths read ``g.user`` when one is available
    and degrade when it is not — most consequentially the grounding gate's
    catalog read (``services._catalog_grounding_refs``), which answers "no
    catalog" outside a request and therefore refuses every
    ``curio_dataset_path`` loader as an ungrounded source. Solve's own workers
    avoid that by building their grounding base in the request thread; a
    service that drives the same paths from a job thread has no request thread
    to borrow, so it supplies one. The alternative — threading an explicit user
    through dev/114's gate — would change product code to accommodate the
    harness, which is the wrong way round.
    """
    from flask import current_app, g, has_request_context

    if has_request_context():
        yield from _run_phases(user, user_key, run_id, fixture, config, started_at=None)
        return
    app = current_app._get_current_object()
    with app.test_request_context():
        g.user = user
        yield from _run_phases(user, user_key, run_id, fixture, config, started_at=None)


def _run_phases(user, user_key: str, run_id: str, fixture, config, *, started_at=None):
    """The phases themselves (see :func:`_run_events` for why the context)."""
    started = time.monotonic()
    record = records_mod.read(user_key, run_id)

    def _save():
        record.latency_ms = int((time.monotonic() - started) * 1000)
        records_mod.write(user_key, record)

    def _phase(phase: str, **detail):
        record.enter(phase, **detail)
        _save()
        return ("phase", {"runId": run_id, "phase": phase, **detail})

    def _cancelled() -> bool:
        """Did somebody ask this run to stop?

        The request arrives as a sentinel file written by another request, so
        observing it is also when the run records it — the run is the only
        writer of its own record (see ``records.cancel_path``).
        """
        if not records_mod.cancel_requested(user_key, run_id):
            return False
        if not record.cancel_requested:
            record.cancel_requested = True
            record.append("cancel-requested")
            records_mod.clear_cancel(user_key, run_id)
            _save()
        return True

    def _over_deadline() -> bool:
        return (time.monotonic() - started) > RUN_DEADLINE_S

    try:
        # ── project ──────────────────────────────────────────────────────
        yield _phase("project")
        project_id = _create_isolated_project(user, user_key, run_id, fixture)
        record.project_id = project_id
        _save()
        yield ("project", {"runId": run_id, "projectId": project_id})

        if _cancelled():
            yield _phase("cancelled", stoppedIn="project")
            return

        # ── provisioning ─────────────────────────────────────────────────
        yield _phase("provisioning")
        for note in _provision(user, user_key, project_id, fixture):
            record.append("note", detail=note)
            _save()
            yield ("note", {"runId": run_id, "detail": note})

        if _cancelled():
            yield _phase("cancelled", stoppedIn="provisioning")
            return

        # ── installing ───────────────────────────────────────────────────
        yield _phase("installing")
        attachment_id, installed = _install_and_attach(user_key, project_id)
        record.attachment_id = attachment_id
        record.append("note", detail=f"installed {', '.join(installed)}")
        _save()

        if _cancelled():
            yield _phase("cancelled", stoppedIn="installing")
            return

        # ── prompting ────────────────────────────────────────────────────
        yield _phase("prompting", model=config.model)
        from utk_curio.backend.app.agents import services as agents_services

        turn = agents_services.run_attachment(
            user_key, project_id, attachment_id, fixture.prompt, config,
            run_context=fixture.context or None,
        )
        usage = turn.get("usage") or {}
        record.usage = {
            "inputTokens": int(usage.get("inputTokens") or 0),
            "outputTokens": int(usage.get("outputTokens") or 0),
        }
        proposals = [
            part for part in (turn.get("content") or [])
            if isinstance(part, Mapping) and part.get("type") == "proposal"
        ]
        _save()
        yield ("replied", {
            "runId": run_id,
            "proposals": [str(p.get("tool")) for p in proposals],
        })

        # ── reviewing ────────────────────────────────────────────────────
        yield _phase("reviewing")
        applied_plan = _review_and_apply(
            user_key, project_id, attachment_id, run_id, record, proposals, fixture
        )
        _save()

        if _cancelled():
            yield _phase("cancelled", stoppedIn="reviewing")
            return

        # ── solving ──────────────────────────────────────────────────────
        solve_results: dict = {}
        timed_out = False
        if applied_plan:
            yield _phase("solving")
            solve_results, timed_out = _solve(
                user_key, project_id, attachment_id, config
            )
            _save()

        # ── scoring ──────────────────────────────────────────────────────
        yield _phase("scoring")
        scored = _score(
            user, user_key, project_id, fixture,
            solve_results=solve_results,
            refused=not proposals,
            timed_out=timed_out or _over_deadline(),
        )
        record.score = scored.score.as_dict()
        record.comparison = scored.as_dict()
        record.digests["rosterDigest"] = _roster_digest(user_key, project_id)
        _save()

        yield _phase("done", total=record.score["total"])
        yield ("done", {"runId": run_id, "score": record.score})
    except Exception as error:  # noqa: BLE001 - a run reports, never crashes
        detail = f"{type(error).__name__}: {error}"
        record.fail(record.phase, detail)
        _save()
        yield ("error", {"runId": run_id, "detail": detail})


# ── the phases, each through a production entry point ───────────────────────

def _create_isolated_project(user, user_key: str, run_id: str, fixture) -> str:
    """A NEW project, marked as this run's. The caller's project is untouched:
    nothing here reads or writes any other project."""
    from utk_curio.backend.app.projects.schemas import ProjectCreate
    from utk_curio.backend.app.projects.services import save_project

    marker = auth_mod.new_marker(run_id, fixture.fixture_id)
    spec = auth_mod.mark_spec(
        {"dataflow": {"nodes": [], "edges": [], "packages": []}}, marker
    )
    detail = save_project(
        user,
        ProjectCreate(
            name=f"Evaluation · {fixture.fixture_id} · {run_id[-8:]}",
            spec=spec,
            description=(
                f"An evaluation run of the {fixture.fixture_id} prompt. Created "
                "by Evaluation mode; safe to delete."
            ),
        ),
    )
    return detail.id


def _provision(user, user_key: str, project_id: str, fixture) -> list:
    """Install the fixture's declared dependencies through the real services."""
    notes: list = []
    from utk_curio.backend.app.datasets.application.catalog_service import (
        DatasetCatalogService,
    )
    from utk_curio.backend.app.packages import services as packages_services

    for dataset_id in fixture.required.get("datasets") or ():
        try:
            DatasetCatalogService(user).install_dataset(project_id, dataset_id)
        except Exception as exc:  # noqa: BLE001 - a missing dataset is a finding
            notes.append(f"could not install dataset {dataset_id}: {exc}")
    for dir_name in fixture.required.get("packages") or ():
        try:
            packages_services.install_to_project(user_key, project_id, dir_name)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"could not enlist package {dir_name}: {exc}")
    return notes


def _install_and_attach(user_key: str, project_id: str) -> tuple:
    """The normal install flow, closure included (``DEC-068``)."""
    from utk_curio.backend.app.agents import services as agents_services

    installed = agents_services.install_in_project(user_key, project_id, DFB_COORD)
    # ``install_in_project`` answers ``{"agents": <the lockfile>, "installed":
    # [coords newly added]}``; the lockfile's rows are coordinate strings, so
    # the closure it wrote is read from ``installed`` rather than re-derived.
    coords = [str(coord) for coord in (installed.get("installed") or [])] or [DFB_COORD]
    attached = agents_services.attach_agent(
        user_key, project_id, DFB_COORD, {"kind": "canvas"}
    )
    return attached["attachmentId"], coords


def _review_and_apply(
    user_key: str,
    project_id: str,
    attachment_id: str,
    run_id: str,
    record,
    proposals: Iterable,
    fixture,
) -> bool:
    """Decide with the shared policy, authorize, then apply through the real
    endpoint. Returns whether a plan was applied."""
    from utk_curio.backend.app.agents import services as agents_services
    from utk_curio.backend.app.projects import storage as projects_storage

    policy = policy_mod.UserPolicy.for_fixture(fixture)
    applied_plan = False
    for proposal in proposals:
        decision = policy.decide(proposal)
        if decision.pending:
            record.pending.append(decision.as_dict())
            record.append(
                "left-pending", tool=decision.tool, target=decision.target,
                reason=decision.reason,
            )
            continue
        spec = projects_storage.read_spec(user_key, project_id) or {}
        try:
            auth_mod.assert_may_auto_apply(spec, run_id=run_id, proposal=proposal)
        except auth_mod.AutoApplyRefused as refusal:
            record.append(
                "refused", tool=decision.tool, target=decision.target,
                reason=str(refusal),
            )
            continue
        proposal_id = str(proposal.get("proposalId") or "")
        try:
            result = agents_services.apply_proposal(
                user_key, project_id, attachment_id, proposal_id
            )
        except Exception as exc:  # noqa: BLE001 - an apply that fails is a finding
            record.failures.append({
                "phase": "reviewing",
                "detail": f"applying {decision.tool} failed: {exc}",
            })
            continue
        record.applied.append({
            **decision.as_dict(),
            "proposalId": proposal_id,
            "status": str(result.get("status") or ""),
        })
        record.append(
            "auto-applied", tool=decision.tool, target=decision.target,
            proposalId=proposal_id, runId=run_id,
        )
        if decision.tool == "dataflow.plan.write":
            applied_plan = True
    return applied_plan


def _solve(user_key: str, project_id: str, attachment_id: str, config) -> tuple:
    """The real Solve, verified."""
    from utk_curio.backend.app.agents import services as agents_services

    try:
        result = agents_services.solve_attachment(
            user_key, project_id, attachment_id, config, verify=True
        )
    except Exception as exc:  # noqa: BLE001 - a Solve failure is a finding
        return {}, False
    return dict(result.get("results") or {}), bool(result.get("notAttempted"))


def _score(
    user,
    user_key: str,
    project_id: str,
    fixture,
    *,
    solve_results: Mapping,
    refused: bool,
    timed_out: bool,
):
    """Compare the persisted dataflow with the reference — server-side.

    The reference is read here, after the model has finished, and only the
    comparison is stored. It never enters a prompt, a run context or a client
    payload.
    """
    from utk_curio.backend.app.projects import storage as projects_storage

    spec = projects_storage.read_spec(user_key, project_id) or {}
    example = json.loads(fixture.source_path.read_text(encoding="utf-8"))
    return attempt_mod.score_attempt(
        fixture,
        actual_spec=spec,
        templates=template_index(),
        example=example,
        universe=_universe(user, user_key, project_id, fixture),
        solve_results=solve_results,
        refused=refused,
        timed_out=timed_out,
    )


def template_index() -> dict:
    """Manifest facts for every template in the committed catalog.

    The same derivation the deterministic tiers and the CLI use, read through
    the packages domain's own reader so a row here is the row a live run's
    roster carries (``DEC-062``).
    """
    from utk_curio.backend.app.packages.services import _catalog_manifests

    index: dict = {}
    for manifest in _catalog_manifests().values():
        for template in manifest.templates:
            index[f"{manifest.package_id}/{template.template_id}"] = TemplateFacts(
                template_id=template.template_id,
                category=getattr(template, "category", "computation"),
                engine=getattr(template, "engine", "python"),
                editor=getattr(template, "editor", "code"),
                has_code=bool(getattr(template, "has_code", False)),
                has_grammar=bool(getattr(template, "has_grammar", False)),
                behavior=getattr(template, "behavior", None),
                backend_handler=getattr(template, "backend_handler", None),
            )
    return index


def _universe(user, user_key: str, project_id: str, fixture) -> Universe:
    from utk_curio.backend.app.datasets.application.catalog_service import (
        DatasetCatalogService,
    )
    from utk_curio.backend.app.packages.services import available_templates

    try:
        roster = {str(row["id"]) for row in available_templates(user_key, project_id)}
    except Exception:  # noqa: BLE001
        roster = set(template_index())
    try:
        listing = DatasetCatalogService(user).list_catalog(dataflow_id=project_id)
        dataset_ids = {
            str(item.get("id")) for item in (listing.get("items") or [])
            if isinstance(item, Mapping) and item.get("id")
        }
    except Exception:  # noqa: BLE001
        dataset_ids = set()
    return Universe(
        templates=frozenset(roster),
        dataset_ids=frozenset(dataset_ids),
        package_dir_names=frozenset(),
        allowed_paths=frozenset(fixture.required.get("paths") or ()),
    )


def _roster_digest(user_key: str, project_id: str) -> str:
    from utk_curio.backend.app.packages.services import available_templates

    try:
        return digest_of(
            str(row["id"]) for row in available_templates(user_key, project_id)
        )
    except Exception:  # noqa: BLE001
        return ""


def _instruction_digest() -> str:
    from utk_curio.backend.app.agents import builtin

    try:
        return digest_of([builtin.read_instruction_text(DFB_COORD) or ""])
    except Exception:  # noqa: BLE001
        return ""


def _host_of(base_url: str) -> str:
    from utk_curio.backend.app.agents.evaluation.training_host import host_of

    return host_of(base_url)


# ── reading runs ────────────────────────────────────────────────────────────

def status(user_key: str, run_id: str) -> dict:
    try:
        record = records_mod.read(user_key, run_id)
    except records_mod.EvaluationRecordError as exc:
        raise EvaluationServiceError(str(exc), 400) from exc
    if record is None:
        raise EvaluationServiceError(f"no evaluation run {run_id}", 404)
    return records_mod.reconcile(user_key, record).as_dict()


def listing(user_key: str) -> dict:
    records = [
        records_mod.reconcile(user_key, record)
        for record in records_mod.list_records(user_key)
    ]
    running = next((r for r in records if r.running), None)
    return {
        "runs": [record.as_dict() for record in records],
        "inFlight": running.run_id if running else None,
    }


def cancel(user_key: str, run_id: str) -> dict:
    """Ask the run to stop. It stops at the next phase boundary — a fetch in
    flight cannot be aborted, the same contract Solve's own cancel has."""
    try:
        record = records_mod.request_cancel(user_key, run_id)
    except records_mod.EvaluationRecordError as exc:
        raise EvaluationServiceError(str(exc), 404) from exc
    return record.as_dict()
