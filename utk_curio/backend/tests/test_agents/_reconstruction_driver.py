"""In-process driver for the reconstruction harness (memo dev/121).

A transport, not a runtime: it drives the SAME endpoints a browser drives --
create a project, install and attach the Dataflow Builder, send one turn, apply
what came back, Solve, read the persisted spec -- through the Flask test client,
with the provider and the sandbox replaced the way every agent test replaces
them (``services.run_chat_completion`` and ``runner._http_exec``).

It lives under ``tests/`` on purpose. The evaluation library itself
(``app/agents/evaluation``) takes values and returns values; anything that
knows about clients, tokens or monkeypatching belongs out here, so the
``app/agents`` boundary holds and the comparator stays testable without a
stack.

The user policy is fixed and written down, because a harness whose "user" makes
different choices from run to run measures nothing:

1. Send the fixture's prompt once. Never rephrase.
2. Apply a plan proposal whole -- no per-node edits.
3. Apply a dataset, package or project install proposal ONLY when the fixture
   required that resource; anything else is left pending and recorded.
4. Add no correction rounds of our own; the runtime's bound is the bound.
5. Solve every pending node once, with verification on.
6. Read the persisted spec, canonicalize, compare, score.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[4]

DFB_COORD = "agent.dataflow-builder@1.0.0"
RESEARCHER_COORD = "agent.researcher@1.0.0"
DATASET_FINDER_COORD = "agent.dataset-finder@1.0.0"


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@dataclass
class TurnResult:
    """One agent turn: what it said, and what it proposed."""

    reply: str = ""
    parts: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    status_code: int = 200

    @property
    def proposals(self) -> list:
        return [p for p in self.parts if p.get("type") == "proposal"]

    def proposal_of(self, tool: str) -> dict | None:
        for part in self.proposals:
            if part.get("tool") == tool:
                return part
        return None

    @property
    def plan_proposal(self) -> dict | None:
        return self.proposal_of("dataflow.plan.write")

    @property
    def refused(self) -> bool:
        return not self.proposals


@dataclass
class SolveResult:
    status_code: int = 200
    payload: dict = field(default_factory=dict)

    @property
    def results(self) -> dict:
        return self.payload.get("results") or {}


class InProcessDriver:
    """Drives one reconstruction attempt against the in-process backend."""

    def __init__(self, client, user, token, monkeypatch):
        self.client = client
        self.user = user
        self.token = token
        self.monkeypatch = monkeypatch
        self.project_id: str | None = None
        self.attachment_id: str | None = None
        self.calls: list = []
        self.exec_payloads: list = []
        self.applied: list = []
        self.left_pending: list = []
        self._no_pip_report = None

    # ── identity ───────────────────────────────────────────────────────────
    @property
    def user_key(self) -> str:
        from utk_curio.backend.app.projects.services import _user_dir_key

        return _user_dir_key(self.user)

    # ── setup ──────────────────────────────────────────────────────────────
    def use_scripted_provider(self) -> None:
        """Point the account's provider at the in-process test provider, the
        way a live run points it at a real endpoint."""
        self.client.patch(
            "/api/auth/me",
            json={"llmApiType": "testing", "llmModel": "scripted"},
            headers=auth(self.token),
        )

    def stub_pip(self, *, import_errors: Mapping | None = None) -> None:
        """Keep pip out of the deterministic suite.

        A real package install may fetch wheels for the libraries its manifest
        declares (``rasterio``, ``torch``), which is minutes of network in a
        test that is measuring a graph. The install SERVICE still runs -- the
        catalog copy, the store, the lockfile, the ``importErrors`` field -- so
        the dependency route is exercised; only the subprocess is stubbed, and
        the browser and live tiers install for real.
        """
        from utk_curio.backend.app.packages import pip_runner

        report = pip_runner.InstallReport(installed=[], skipped=[])
        self._no_pip_report = report
        self.monkeypatch.setattr(
            pip_runner, "install_python_deps", lambda deps, **kw: report
        )
        failures = dict(import_errors or {})
        self.monkeypatch.setattr(
            pip_runner, "import_failures", lambda deps, **kw: dict(failures)
        )

    def create_project(self, name: str = "reconstruction") -> str:
        body = {
            "name": name,
            "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}},
            "outputs": [],
        }
        response = self.client.post("/api/projects", json=body, headers=auth(self.token))
        assert response.status_code in (200, 201), response.get_json()
        self.project_id = response.get_json()["id"]
        return self.project_id

    def install_and_attach_second(self, coord: str) -> str:
        """A second attachment on the same project.

        The install lanes live with the agents that own them -- ``dataset.install``
        with the Dataset Finder, ``package.install`` with the Researcher (dev/93's
        middle rung) -- so a resolution test drives the same two-agent flow a
        person does, rather than pretending the Dataflow Builder holds tools it
        was never granted.
        """
        response = self.client.post(
            f"/api/agents/projects/{self.project_id}/install",
            json={"coord": coord},
            headers=auth(self.token),
        )
        assert response.status_code in (200, 201), response.get_json()
        attached = self.client.post(
            f"/api/agents/projects/{self.project_id}/attachments",
            json={"coord": coord, "target": {"kind": "canvas"}},
            headers=auth(self.token),
        )
        assert attached.status_code in (200, 201), attached.get_json()
        return attached.get_json()["attachmentId"]

    def with_attachment(self, attachment_id: str):
        """Run the next calls against another attachment (a context manager
        would hide which attachment a line talks to; this reads plainly)."""
        previous = self.attachment_id
        self.attachment_id = attachment_id
        return previous

    def install_and_attach(self, coord: str = DFB_COORD) -> str:
        response = self.client.post(
            f"/api/agents/projects/{self.project_id}/install",
            json={"coord": coord},
            headers=auth(self.token),
        )
        assert response.status_code in (200, 201), response.get_json()
        attached = self.client.post(
            f"/api/agents/projects/{self.project_id}/attachments",
            json={"coord": coord, "target": {"kind": "canvas"}},
            headers=auth(self.token),
        )
        assert attached.status_code in (200, 201), attached.get_json()
        self.attachment_id = attached.get_json()["attachmentId"]
        return self.attachment_id

    # ── provisioning (production services only) ────────────────────────────
    def install_datasets(self, dataset_ids: Iterable) -> list:
        from utk_curio.backend.app.datasets.application.catalog_service import (
            DatasetCatalogService,
        )

        installed = []
        for dataset_id in dataset_ids:
            DatasetCatalogService(self.user).install_dataset(self.project_id, dataset_id)
            installed.append(dataset_id)
        return installed

    def install_packages_to_project(self, dir_names: Iterable) -> list:
        from utk_curio.backend.app.packages import services as packages_services

        out = []
        for dir_name in dir_names:
            out.append(packages_services.install_to_project(
                self.user_key, self.project_id, dir_name
            ))
        return out

    def install_packages_to_account_only(self, dir_names: Iterable) -> list:
        """The account install without the project enlist -- the state the
        roster describes as *installed but NOT enlisted*, which is what makes
        the reuse ladder's middle rung reachable (dev/93)."""
        responses = []
        for dir_name in dir_names:
            response = self.client.post(
                "/api/packages/catalog/install",
                json={"dirName": dir_name},
                headers=auth(self.token),
            )
            assert response.status_code in (200, 201), response.get_json()
            responses.append(response.get_json())
        return responses

    def catalog_dataset_ids(self) -> set:
        from utk_curio.backend.app.datasets.application.catalog_service import (
            DatasetCatalogService,
        )

        listing = DatasetCatalogService(self.user).list_catalog(dataflow_id=self.project_id)
        return {
            str(item.get("id"))
            for item in (listing.get("items") or [])
            if isinstance(item, dict) and item.get("id")
        }

    def installed_dataset_ids(self) -> set:
        from utk_curio.backend.app.datasets.application.catalog_service import (
            DatasetCatalogService,
        )

        listing = DatasetCatalogService(self.user).list_catalog(dataflow_id=self.project_id)
        return {
            str(item.get("id"))
            for item in (listing.get("items") or [])
            if isinstance(item, dict) and item.get("installed")
        }

    def roster(self) -> list:
        from utk_curio.backend.app.packages import services as packages_services

        return packages_services.available_templates(self.user_key, self.project_id)

    def roster_ids(self) -> set:
        return {str(row["id"]) for row in self.roster()}

    def catalog_package_dir_names(self) -> set:
        return {
            path.name
            for path in (REPO_ROOT / "packages").iterdir()
            if (path / "manifest.json").exists()
        }

    # ── the model and the sandbox ──────────────────────────────────────────
    def script(self, responder: Callable) -> None:
        """Install a scripted provider that answers per call.

        A responder rather than a list: Solve asks for one node's content per
        call, in wave order, so a positional script cannot know which node it
        is answering. The responder reads the request it was given -- exactly
        what a model does.
        """
        from utk_curio.backend.app.agents import services as services_mod

        calls = self.calls

        def _fake_run(config, messages, **kwargs):
            if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
                return "Reconstruction"
            calls.append(messages)
            return responder(messages, len(calls) - 1)

        self.monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion", _fake_run
        )

    def fake_sandbox(self, kind_for: Callable | None = None) -> None:
        """Every execution succeeds, reporting the kind the caller chooses.

        The deterministic suite is not testing the sandbox -- ``test_execution``
        and the browser matrix do that. It is testing that verified content
        reaches the persisted spec.
        """
        payloads = self.exec_payloads

        def _exec(endpoint, payload):
            payloads.append(payload)
            kind = kind_for(payload) if kind_for else "dataframe"
            return {
                "stdout": [],
                "stderr": "",
                "output": {"path": f"art-{len(payloads)}", "dataType": kind},
            }

        self.monkeypatch.setattr(
            "utk_curio.backend.app.execution.runner._http_exec", _exec
        )

    # ── the turn, the review, the run ──────────────────────────────────────
    def run_turn(self, message: str, context: str | None = None) -> TurnResult:
        body = {"message": message}
        if context:
            body["context"] = context
        response = self.client.post(
            f"/api/agents/projects/{self.project_id}/attachments/{self.attachment_id}/run",
            json=body,
            headers=auth(self.token),
        )
        payload = response.get_json() or {}
        return TurnResult(
            reply=payload.get("reply") or "",
            parts=list(payload.get("content") or []),
            usage=payload.get("usage") or {},
            status_code=response.status_code,
        )

    def apply(self, proposal: Mapping) -> dict:
        proposal_id = proposal.get("proposalId")
        response = self.client.post(
            f"/api/agents/projects/{self.project_id}/attachments/"
            f"{self.attachment_id}/proposals/{proposal_id}/apply",
            json={},
            headers=auth(self.token),
        )
        payload = response.get_json() or {}
        payload["_statusCode"] = response.status_code
        if response.status_code == 200:
            self.applied.append(proposal.get("tool"))
        return payload

    def apply_under_policy(self, turn: TurnResult, *, required: Mapping) -> list:
        """Rule 2 and rule 3 of the user policy, and nothing more."""
        applied = []
        wanted_datasets = {str(d) for d in required.get("datasets") or ()}
        wanted_packages = {str(p) for p in required.get("packages") or ()}
        for proposal in turn.proposals:
            tool = proposal.get("tool")
            # What a proposal targets is in its PINS -- the revision-safety
            # basis the apply endpoint re-checks (``make_proposal_part``), not a
            # params echo. Reading a params key that does not exist is how the
            # first cut of this policy silently declined every install it was
            # offered.
            pins = proposal.get("pins") or {}
            if tool == "dataflow.plan.write":
                applied.append(("plan", self.apply(proposal)))
            elif tool == "dataset.install":
                target = str(pins.get("datasetId") or "")
                if target and target in wanted_datasets:
                    applied.append(("dataset.install", self.apply(proposal)))
                else:
                    self.left_pending.append(("dataset.install", target))
            elif tool == "package.install":
                target = str(pins.get("dirName") or "")
                if target and target in wanted_packages:
                    applied.append(("package.install", self.apply(proposal)))
                else:
                    self.left_pending.append(("package.install", target))
            elif tool == "project.install":
                applied.append(("project.install", self.apply(proposal)))
            else:
                self.left_pending.append((tool, ""))
        return applied

    def solve(self, node_ids: Iterable | None = None, *, verify: bool = True) -> SolveResult:
        body: dict = {"verify": verify}
        if node_ids is not None:
            body["nodeIds"] = list(node_ids)
        response = self.client.post(
            f"/api/agents/projects/{self.project_id}/attachments/{self.attachment_id}/solve",
            json=body,
            headers=auth(self.token),
        )
        return SolveResult(status_code=response.status_code, payload=response.get_json() or {})

    # ── what landed ────────────────────────────────────────────────────────
    def read_spec(self) -> dict:
        from utk_curio.backend.app.projects import storage as projects_storage

        return projects_storage.read_spec(self.user_key, self.project_id) or {}

    def session_turns(self) -> list:
        response = self.client.get(
            f"/api/agents/projects/{self.project_id}/attachments/"
            f"{self.attachment_id}/session",
            headers=auth(self.token),
        )
        return list((response.get_json() or {}).get("turns") or [])

    def system_prompt(self, call: int = 0) -> str:
        return self.calls[call][0]["content"] if len(self.calls) > call else ""

    # ── reading a request the way a model would ────────────────────────────
    @staticmethod
    def delegate_inputs(messages: Iterable) -> dict:
        """The inputs a delegated content request carries.

        A per-node content request arrives as ``[delegated task from ...]``
        followed by a JSON object holding ``nodeType``, ``intent``,
        ``nodeContext`` and (for a planned node) ``planSiblings``. A responder
        must key on THIS node's ``intent`` -- the sibling list names every
        other node in the plan, so matching anywhere in the message answers the
        wrong question. That mistake cost the first cut of this driver a
        grounding refusal it could not explain.
        """
        conversation = list(messages)
        if not conversation:
            return {}
        text = str(conversation[-1].get("content") or "")
        start = text.find("{")
        if start < 0:
            return {}
        try:
            parsed, _ = json.JSONDecoder().raw_decode(text[start:])
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def prompts_sent(self) -> str:
        """Every byte the provider was handed this run -- what a leak test
        reads to prove the answer key never travelled."""
        return json.dumps(self.calls)


def oracle_responder(plan_reply: str, contents: Mapping) -> Callable:
    """A scripted provider that plays the oracle.

    Call 0 is the planning turn and gets the plan tail. Every later call is a
    per-node content request, answered with the code for the node its OWN
    intent names -- so the reply depends on what was asked, exactly as a
    model's would.
    """
    refs = sorted(contents, key=len, reverse=True)

    def responder(messages, index):
        if index == 0:
            return plan_reply
        inputs = InProcessDriver.delegate_inputs(messages)
        intent = str(inputs.get("intent") or "")
        for ref in refs:
            if ref in intent:
                return contents[ref]
        # No node matched: return something obviously inert rather than a
        # plausible guess, so a mis-scripted run fails loudly.
        return "# the harness had no content for this node\nreturn None"

    return responder


# ── one whole attempt, the way every tier runs it ──────────────────────────

@dataclass
class Attempt:
    """What one reconstruction attempt produced."""

    fixture_id: str
    turn: TurnResult | None = None
    solve: SolveResult | None = None
    spec: dict = field(default_factory=dict)
    scored = None                       # AttemptScore, once scored
    unrepresentable: str | None = None  # the declared need, when the oracle refused
    applied: list = field(default_factory=list)
    driver: object = None

    @property
    def score(self):
        return self.scored.score if self.scored else None


def oracle_attempt(
    fixture,
    driver: InProcessDriver,
    *,
    templates: Mapping,
    example: Mapping,
    provision_datasets: bool = True,
    provision_packages: bool = True,
    account_only_packages: Iterable = (),
    responder: Callable | None = None,
    solve: bool = True,
    import_errors: Mapping | None = None,
) -> Attempt:
    """Drive one fixture through the production path with oracle replies.

    The reachability proof of memo dev/121 section 3.5: everything here is the
    real thing except the provider (scripted) and the sandbox (faked), so a
    score below 1.0 for an expressible fixture is a defect in the harness or in
    the runtime, never noise.
    """
    from utk_curio.backend.app.agents.evaluation import attempt as attempt_mod
    from utk_curio.backend.app.agents.evaluation import oracle
    from utk_curio.backend.app.agents.evaluation.canonical import canonical_graph_from_spec
    from utk_curio.backend.app.agents.evaluation.compare import Universe

    driver.use_scripted_provider()
    driver.stub_pip(import_errors=import_errors)
    driver.create_project()
    driver.install_and_attach()

    if provision_datasets:
        driver.install_datasets(fixture.required["datasets"])
    if account_only_packages:
        driver.install_packages_to_account_only(account_only_packages)
    if provision_packages:
        driver.install_packages_to_project(
            [p for p in fixture.required["packages"] if p not in set(account_only_packages)]
        )

    expected_graph = canonical_graph_from_spec(example, templates=templates)
    hints = oracle.source_hints_for(
        fixture.expected,
        example=example,
        origins=expected_graph.origins,
        paths=fixture.required.get("paths") or (),
    )
    try:
        plan = oracle.plan_for(
            fixture.expected,
            intents=fixture.intents,
            source_hints=hints,
            synthetic_refs=oracle.synthetic_refs_for(
                fixture.expected, example=example, origins=expected_graph.origins
            ),
        )
    except oracle.Unrepresentable as gap:
        return Attempt(fixture_id=fixture.fixture_id, unrepresentable=gap.need, driver=driver)

    contents = oracle.content_replies(
        fixture.expected, example=example, origins=expected_graph.origins,
        only_executable=False,
    )
    kinds = {
        str(intent.get("ref")): str(intent.get("outputKind"))
        for intent in fixture.intents
        if intent.get("outputKind")
    }
    code_to_kind = {
        contents[ref]: kind for ref, kind in kinds.items() if ref in contents
    }

    def kind_for(payload):
        code = str(payload.get("code") or payload.get("content") or "")
        if code in code_to_kind:
            return code_to_kind[code]
        # A fake sandbox still has to answer plausibly: the runtime checks the
        # produced type against the DOWNSTREAM node's declared input ports, so
        # answering "dataframe" for code that plainly returns a GeoDataFrame
        # makes the runtime refuse a node the real sandbox would accept.
        lowered = code.lower()
        if "rasterio" in lowered or "raster" in lowered:
            return "raster"
        if "geopandas" in lowered or "geodataframe" in lowered or "gpd." in lowered:
            return "geodataframe"
        return "dataframe"

    driver.script(responder or oracle_responder(plan.as_reply(), contents))
    driver.fake_sandbox(kind_for=kind_for)

    turn = driver.run_turn(fixture.prompt, fixture.context)
    applied = driver.apply_under_policy(turn, required=fixture.required)
    solve_result = driver.solve() if solve else None
    spec = driver.read_spec()

    universe = Universe(
        templates=frozenset(driver.roster_ids()),
        dataset_ids=frozenset(driver.catalog_dataset_ids()),
        package_dir_names=frozenset(driver.catalog_package_dir_names()),
        allowed_paths=frozenset(fixture.required.get("paths") or ()),
    )
    scored = attempt_mod.score_attempt(
        fixture,
        actual_spec=spec,
        templates=templates,
        example=example,
        universe=universe,
        solve_results=(solve_result.results if solve_result else {}),
        refused=turn.refused,
    )
    result = Attempt(
        fixture_id=fixture.fixture_id,
        turn=turn,
        solve=solve_result,
        spec=spec,
        applied=applied,
        driver=driver,
    )
    result.scored = scored
    return result
