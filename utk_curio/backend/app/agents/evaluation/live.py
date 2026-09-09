"""The live-model evaluation driver (memo dev/121, ``DEC-077``).

Talks to a RUNNING Curio over HTTP, as a browser does: create a project,
install and attach the Dataflow Builder, send one fixture prompt, apply what
the fixed user policy allows, Solve, read the persisted dataflow, score it with
the same library every other tier uses, and write a report.

Three rules this module exists to hold.

*It is never a gate.* The output is a report. Nothing in Curio passes or fails
because of it, and ``report.json`` says so in a field.

*It is opt-in.* Nothing runs without ``CURIO_EVAL_LIVE=1`` in the environment,
the same visible-opt-in posture as the browser matrix's ``CURIO_E2E_EXTERNAL``.

*It never reads a key.* Provider and model are whatever the evaluation account
already saved in AI Settings. This module records the provider type, the base
URL's HOST and the model name -- never a credential -- and every transcript
byte it writes goes through :func:`report.scrub` first.

The transport is deliberately dumb (``urllib``): a harness that needs a
dependency to talk to the product would be one more thing to keep working.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from utk_curio.backend.app.agents.evaluation import attempt as attempt_mod
from utk_curio.backend.app.agents.evaluation.compare import Universe
from utk_curio.backend.app.agents.evaluation.report import (
    AttemptRecord,
    Digests,
    ProviderRecord,
    RunReport,
    digest_of,
)

LIVE_ENV_FLAG = "CURIO_EVAL_LIVE"
EXTERNAL_ENV_FLAG = "CURIO_EVAL_EXTERNAL"
BUDGET_ENV = "CURIO_EVAL_FIXTURE_BUDGET_S"
DEFAULT_FIXTURE_BUDGET_S = 900

DFB_COORD = "agent.dataflow-builder@1.0.0"


class LiveEvalRefused(Exception):
    """The run must not start: not opted in, or no provider configured."""


def require_opt_in(env: Mapping | None = None) -> None:
    """Refuse to run unless the operator asked for it, by name."""
    environ = env if env is not None else os.environ
    if str(environ.get(LIVE_ENV_FLAG) or "").strip() not in ("1", "true", "yes"):
        raise LiveEvalRefused(
            f"live evaluation is opt-in: export {LIVE_ENV_FLAG}=1 to run it. It "
            "calls the account's configured model once per fixture and produces "
            "an evaluation report, never a pass/fail gate."
        )


def fixture_budget_s(env: Mapping | None = None) -> int:
    environ = env if env is not None else os.environ
    try:
        value = int(str(environ.get(BUDGET_ENV) or DEFAULT_FIXTURE_BUDGET_S))
    except ValueError:
        return DEFAULT_FIXTURE_BUDGET_S
    return max(30, value)


@dataclass
class HttpClient:
    """The smallest client that can drive the product's own routes."""

    base_url: str
    token: str
    timeout: float = 120.0

    def request(self, path: str, *, method: str = "GET", payload: Mapping | None = None):
        url = f"{self.base_url.rstrip('/')}{path}"
        data = None
        headers = {"Authorization": f"Bearer {self.token}"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                return response.status, (json.loads(body) if body else {})
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = {"error": body[:500]}
            return error.code, parsed
        except urllib.error.URLError as error:
            # An unreachable backend is an answer too: the caller turns it into
            # a refusal naming the address, not a traceback out of urllib.
            raise LiveEvalRefused(
                f"could not reach {self.base_url} ({error.reason}); is the stack "
                "running, and is --backend-url right?"
            ) from None
        except TimeoutError:
            raise LiveEvalRefused(
                f"{method} {path} timed out after {self.timeout:.0f}s"
            ) from None

    def json(self, path: str, *, method: str = "GET", payload: Mapping | None = None):
        status, body = self.request(path, method=method, payload=payload)
        if status >= 400:
            raise LiveEvalRefused(f"{method} {path} -> {status}: {body}")
        return body


@dataclass
class LiveRun:
    """One live evaluation run over a set of fixtures."""

    client: HttpClient
    templates: Mapping
    report: RunReport
    attempts_per_fixture: int = 1
    include_external: bool = False
    tiers: tuple = ("T0", "T1", "T2", "T3")
    notes: list = field(default_factory=list)

    # ── provider identity, never the key ───────────────────────────────────
    def provider_record(self) -> ProviderRecord:
        me = self.client.json("/api/auth/me")
        base_url = str(me.get("llmBaseUrl") or "")
        host = urllib.parse.urlparse(base_url).netloc if base_url else ""
        api_type = str(me.get("llmApiType") or "")
        model = str(me.get("llmModel") or "")
        if not api_type and not model:
            raise LiveEvalRefused(
                "the evaluation account has no provider or model configured; set "
                "them in AI Settings first. Nothing is guessed and no key is read "
                "by this tool."
            )
        return ProviderRecord(api_type=api_type, base_url_host=host, model=model)

    # ── one attempt ────────────────────────────────────────────────────────
    def skip_reasons(self, fixture) -> list:
        active = set(fixture.needs)
        if not self.include_external:
            active.add(f"!{EXTERNAL_ENV_FLAG}")
        return fixture.skips_for(scope="execution", active=active)

    def run_fixture(self, fixture, *, example: Mapping, attempt: int = 1) -> AttemptRecord:
        record = AttemptRecord(
            fixture_id=fixture.fixture_id,
            attempt=attempt,
            tier=fixture.tier,
            needs=fixture.needs,
            review_status=fixture.review_status,
            skipped=self.skip_reasons(fixture),
        )
        started = time.monotonic()
        try:
            project_id = self._create_project(fixture)
            attachment_id = self._install_and_attach(project_id)
            self._provision(project_id, fixture)
            turn = self.client.json(
                f"/api/agents/projects/{project_id}/attachments/{attachment_id}/run",
                method="POST",
                payload={"message": fixture.prompt, **(
                    {"context": fixture.context} if fixture.context else {}
                )},
            )
            record.transcript = self._transcript(project_id, attachment_id)
            record.usage = {
                "inputTokens": int((turn.get("usage") or {}).get("inputTokens") or 0),
                "outputTokens": int((turn.get("usage") or {}).get("outputTokens") or 0),
            }
            proposals = [
                part for part in (turn.get("content") or [])
                if isinstance(part, Mapping) and part.get("type") == "proposal"
            ]
            record.proposals = [dict(p) for p in proposals]
            applied = self._apply_under_policy(
                project_id, attachment_id, proposals, fixture
            )
            solve_results: dict = {}
            timed_out = False
            if any(tool == "dataflow.plan.write" for tool, _ in applied):
                solve_results, timed_out = self._solve(project_id, attachment_id)
            spec = self.client.json(f"/api/projects/{project_id}")["spec"]
            record.generated_spec = spec
            record.digests = Digests(
                fixture_sha256=fixture.fixture_sha256(),
                prompt_sha256=fixture.prompt_sha256(),
                agent_instruction_sha256=self._instruction_digest(),
                roster_digest=digest_of(self._roster_ids(project_id)),
            )
            scored = attempt_mod.score_attempt(
                fixture,
                actual_spec=spec,
                templates=self.templates,
                example=example,
                universe=self._universe(project_id, fixture),
                solve_results=solve_results,
                refused=not proposals,
                timed_out=timed_out,
            )
            record.score = scored.score
            record.comparison = scored.as_dict()
        except LiveEvalRefused as refusal:
            record.error = str(refusal)
        except Exception as error:  # a harness fault is a harness fault
            record.error = f"{type(error).__name__}: {error}"
        record.latency_ms = int((time.monotonic() - started) * 1000)
        return record

    def run(self, fixtures: Iterable, *, examples: Mapping) -> RunReport:
        self.report.provider = self.provider_record()
        for fixture in fixtures:
            if fixture.tier not in self.tiers:
                continue
            for attempt in range(1, self.attempts_per_fixture + 1):
                self.report.add(
                    self.run_fixture(
                        fixture, example=examples[fixture.fixture_id], attempt=attempt
                    )
                )
        for note in self.notes:
            self.report.notes.append(note)
        return self.report

    # ── the steps ──────────────────────────────────────────────────────────
    def _create_project(self, fixture) -> str:
        body = {
            "name": f"eval {fixture.fixture_id}",
            "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}},
            "outputs": [],
        }
        return self.client.json("/api/projects", method="POST", payload=body)["id"]

    def _install_and_attach(self, project_id: str) -> str:
        base = f"/api/agents/projects/{project_id}"
        self.client.json(f"{base}/install", method="POST", payload={"coord": DFB_COORD})
        attached = self.client.json(
            f"{base}/attachments", method="POST",
            payload={"coord": DFB_COORD, "target": {"kind": "canvas"}},
        )
        return attached["attachmentId"]

    def _provision(self, project_id: str, fixture) -> None:
        for dataset_id in fixture.required["datasets"]:
            status, body = self.client.request(
                f"/api/datasets/dataflows/{project_id}/datasets/install",
                method="POST", payload={"datasetId": dataset_id},
            )
            if status >= 400:
                self.notes.append(
                    f"{fixture.fixture_id}: could not install {dataset_id} ({status})"
                )
        for dir_name in fixture.required["packages"]:
            status, body = self.client.request(
                f"/api/packages/projects/{project_id}/install",
                method="POST", payload={"dirName": dir_name},
            )
            if status >= 400:
                self.notes.append(
                    f"{fixture.fixture_id}: could not enlist {dir_name} ({status})"
                )

    def _apply_under_policy(
        self, project_id: str, attachment_id: str, proposals: Iterable, fixture
    ) -> list:
        """The same fixed policy the deterministic driver plays: a plan is
        applied whole, an install only for a resource the fixture required, and
        anything else is left pending and recorded."""
        wanted_datasets = set(fixture.required["datasets"])
        wanted_packages = set(fixture.required["packages"])
        base = f"/api/agents/projects/{project_id}/attachments/{attachment_id}"
        applied: list = []
        for proposal in proposals:
            tool = str(proposal.get("tool") or "")
            pins = proposal.get("pins") or {}
            target = ""
            if tool == "dataset.install":
                target = str(pins.get("datasetId") or "")
                if target not in wanted_datasets:
                    self.notes.append(
                        f"{fixture.fixture_id}: left a dataset.install for "
                        f"{target or '?'} pending (not required by the fixture)"
                    )
                    continue
            elif tool == "package.install":
                target = str(pins.get("dirName") or "")
                if target not in wanted_packages:
                    self.notes.append(
                        f"{fixture.fixture_id}: left a package.install for "
                        f"{target or '?'} pending (not required by the fixture)"
                    )
                    continue
            elif tool not in ("dataflow.plan.write", "project.install"):
                self.notes.append(f"{fixture.fixture_id}: left a {tool} pending")
                continue
            status, body = self.client.request(
                f"{base}/proposals/{proposal.get('proposalId')}/apply",
                method="POST", payload={},
            )
            applied.append((tool, status))
            if status >= 400:
                self.notes.append(
                    f"{fixture.fixture_id}: applying {tool} failed ({status})"
                )
        return applied

    def _solve(self, project_id: str, attachment_id: str) -> tuple:
        """Solve every pending node once, bounded by the fixture budget.

        The route runs the batch as a detached job; this waits on the response
        and, if the wait is cut short, reports a timeout rather than a failure.
        """
        base = f"/api/agents/projects/{project_id}/attachments/{attachment_id}"
        deadline = time.monotonic() + fixture_budget_s()
        status, body = self.client.request(
            f"{base}/solve", method="POST", payload={"verify": True}
        )
        if status >= 400:
            self.notes.append(f"solve returned {status}: {str(body)[:200]}")
            return {}, False
        results = dict(body.get("results") or {})
        return results, time.monotonic() > deadline

    def _transcript(self, project_id: str, attachment_id: str) -> list:
        status, body = self.client.request(
            f"/api/agents/projects/{project_id}/attachments/{attachment_id}/session"
        )
        if status >= 400:
            return []
        return list(body.get("turns") or [])

    def _roster_ids(self, project_id: str) -> list:
        status, body = self.client.request(f"/api/packages/projects/{project_id}")
        if status >= 400:
            return []
        rows = body.get("templates") or body.get("packages") or []
        out: list = []
        for row in rows:
            if isinstance(row, Mapping) and row.get("id"):
                out.append(str(row["id"]))
        return out

    def _universe(self, project_id: str, fixture) -> Universe:
        status, body = self.client.request(
            f"/api/datasets/catalog?dataflowId={urllib.parse.quote(project_id)}"
        )
        dataset_ids = set()
        if status < 400:
            for item in (body.get("items") or []):
                if isinstance(item, Mapping) and item.get("id"):
                    dataset_ids.add(str(item["id"]))
        roster = set(self._roster_ids(project_id)) or set(self.templates)
        return Universe(
            templates=frozenset(roster),
            dataset_ids=frozenset(dataset_ids),
            package_dir_names=frozenset(),
            allowed_paths=frozenset(fixture.required.get("paths") or ()),
        )

    def _instruction_digest(self) -> str:
        """The Dataflow Builder's own instruction bytes, by digest.

        The same prompt against a changed instruction is a different run, and
        dev/95 already pins these bytes -- so a report that omitted this could
        not be compared with the next one.
        """
        try:
            from utk_curio.backend.app.agents import builtin

            text = builtin.read_instruction_text(DFB_COORD) or ""
        except Exception:
            return ""
        return digest_of([text])
