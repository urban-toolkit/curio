"""Playwright: reconstruction as a person sees it (memo dev/121).

The deterministic suite (``tests/test_agents/test_example_reconstruction.py``)
proves the server rebuilds an example from its prompt. It cannot see the four
things a person actually judges, so this module covers exactly those and no
more -- it is representative by design, not a second matrix:

1. **The palettes.** A dataset installed through the catalog service shows up as
   a draggable row, and a package's templates appear under their package, so
   "provisioned" means provisioned in the UI and not only in a lockfile.
2. **The plan's card.** The plan lands with the reply, whole, and its card
   names what it built and offers its Undo.
3. **Solve progress and reconnection.** The strip reports the run, and a reload
   mid-run re-attaches to the same job instead of losing it.
4. **The output.** The plan's nodes render on the canvas and carry the content
   Solve wrote.

Marked ``examples`` (the suite's opt-in marker for tests that need the shipped
example corpus) and driven by the scripted provider, so no model is called.

Run::

    pytest utk_curio/backend/tests/test_frontend/test_example_reconstruction_e2e.py \
        --with-examples -v
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

from utk_curio.backend.app.agents.evaluation import attempt as attempt_mod
from utk_curio.backend.app.agents.evaluation import oracle
from utk_curio.backend.app.agents.evaluation.canonical import (
    TemplateFacts,
    canonical_graph_from_spec,
)
from utk_curio.backend.app.agents.evaluation.compare import Universe
from utk_curio.backend.app.agents.evaluation.fixtures import (
    FIXTURE_ROOT,
    load_fixture,
)

from .utils import (
    api_json,
    canvas_nodes,
    dismiss_toasts,
    install_session_cookie,
    leave_agent_badge,
    open_tools_palette,
    read_node_code,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    script_agent_replies,
    stub_db_user,
    use_scripted_llm,
)

pytestmark = pytest.mark.examples

SCREENSHOT_STEM = "example-reconstruction"
USERNAME = "reconstruction_e2e_user"
DFB_COORD = "agent.curio.dataflow-builder@1"
DFB_NAME = "Dataflow Builder"

#: One curated fixture, chosen because it is the smallest that still has
#: everything the browser has to show: a catalog dataset, a fan-out into two
#: branches, executable python nodes and two grammar views.
FIXTURE = load_fixture(FIXTURE_ROOT / "01-vega-lite-chained-transforms.prompt.json")


#: ``<repo>/utk_curio/backend/tests/test_frontend/<this file>`` -> ``<repo>``
_REPO_ROOT = Path(__file__).resolve().parents[4]


def _templates() -> dict:
    """Manifest facts from the checkout, as everywhere else in the harness."""
    index: dict = {}
    for manifest_path in sorted((_REPO_ROOT / "packages").glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        package_id = str(manifest.get("id") or "")
        for template in manifest.get("templates") or []:
            index[f"{package_id}/{template['id']}"] = TemplateFacts(
                template_id=str(template["id"]),
                category=str(template.get("category") or "computation"),
                engine=str(template.get("engine") or "python"),
                editor=str(template.get("editor") or "code"),
                has_code=bool(template.get("hasCode")),
                has_grammar=bool(template.get("hasGrammar")),
                behavior=template.get("behavior"),
                backend_handler=template.get("backendHandler"),
            )
    return index


TEMPLATES = _templates()


def _example() -> dict:
    return json.loads(FIXTURE.source_path.read_text(encoding="utf-8"))


def _empty_spec() -> dict:
    return {
        "dataflow": {
            "name": "Reconstruction",
            "task": "",
            "nodes": [],
            "edges": [],
            "packages": [],
        }
    }


@pytest.fixture(scope="class")
def reconstruction_session(workflow_page, frontend_server, current_server):
    """One authenticated browser session for the class.

    Motion is reduced before the first navigation: the chat panel and the
    canvas both animate, and a visible-but-moving element makes ``click`` time
    out with nothing useful to say (the dev/108 lesson).
    """
    workflow_page.emulate_media(reduced_motion="reduce")
    login = stub_db_user(
        current_server, username=USERNAME, name="Reconstruction E2E",
    )
    install_session_cookie(workflow_page, frontend_server, login["token"])
    use_scripted_llm(current_server, login["token"])
    return {
        "page": workflow_page,
        "frontend": frontend_server,
        "backend": current_server,
        "token": login["token"],
        "username": USERNAME,
    }


def _new_project(session, name: str) -> str:
    project = api_json(
        f"{session['backend']}/api/testing/stub-project", session["token"],
        method="POST",
        payload={"username": session["username"], "name": name, "spec": _empty_spec()},
    )
    return project["id"]


def _provision(session, project_id: str) -> None:
    """Install the fixture's declared dependencies through the real services --
    the same endpoints the Data Catalog drawer and the package drawer call."""
    backend, token = session["backend"], session["token"]
    for dataset_id in FIXTURE.required["datasets"]:
        api_json(
            f"{backend}/api/dataflows/{project_id}/datasets/install",
            token, method="POST", payload={"datasetId": dataset_id},
        )
    for dir_name in FIXTURE.required["packages"]:
        api_json(
            f"{backend}/api/packages/projects/{project_id}/install",
            token, method="POST", payload={"dirName": dir_name},
        )


def _attach_builder(session, project_id: str) -> str:
    backend, token = session["backend"], session["token"]
    base = f"{backend}/api/agents/projects/{project_id}"
    api_json(f"{base}/install", token, method="POST", payload={"coord": DFB_COORD})
    attachment = api_json(
        f"{base}/attachments", token, method="POST",
        payload={"coord": DFB_COORD, "target": {"kind": "canvas"}},
    )
    return attachment["attachmentId"]


def _script_the_oracle(session, *, solve_content: bool = True) -> dict:
    """Script the plan and, optionally, one content reply per node.

    The plan is the first queued reply. Content replies are keyed by each
    node's ref, which its delegated ``intent`` names: Solve asks per node, in
    wave order and interleaved with dataset discovery, so a position in the
    queue cannot know which node it answers. The plan is what this module is
    about; a Solve that fills nodes with the example's own code is scripted
    only so the browser has something real to render.
    """
    example = _example()
    graph = canonical_graph_from_spec(example, templates=TEMPLATES)
    plan = oracle.plan_for(
        FIXTURE.expected,
        intents=FIXTURE.intents,
        source_hints=oracle.source_hints_for(
            FIXTURE.expected, example=example, origins=graph.origins,
            paths=FIXTURE.required.get("paths") or (),
        ),
        synthetic_refs=oracle.synthetic_refs_for(
            FIXTURE.expected, example=example, origins=graph.origins
        ),
    )
    contents = oracle.content_replies(
        FIXTURE.expected, example=example, origins=graph.origins,
        only_executable=False,
    )
    script_agent_replies(
        session["backend"], plan.as_reply(),
        by_intent=dict(contents) if solve_content else None,
    )
    return {"plan": plan, "contents": contents, "example": example}


def _open_chat(page):
    opener = page.get_by_role(
        "button", name=re.compile(rf"^Open chat with {re.escape(DFB_NAME)}")
    ).first
    expect(opener).to_be_visible(timeout=20000)
    opener.click()
    panel = page.get_by_role(
        "dialog", name=re.compile(rf"^Chat with {re.escape(DFB_NAME)}")
    )
    expect(panel).to_be_visible(timeout=20000)
    return panel


def _send(panel, message: str) -> None:
    panel.get_by_role("textbox", name="Message this agent").fill(message)
    panel.get_by_role("button", name="Send", exact=True).click()


def _saved_spec(session, project_id: str) -> dict:
    return api_json(
        f"{session['backend']}/api/projects/{project_id}", session["token"]
    )["spec"]


@pytest.mark.catalog_calendar  # the palette row says how old the dataset is
class TestPaletteShowsWhatWasProvisioned:
    """Mode 1 of the brief, in the UI: a dependency installed through the
    existing services must be visible where a person would reach for it."""

    def test_an_installed_dataset_becomes_a_draggable_palette_row(
        self, reconstruction_session
    ):
        require_project_page()
        require_user_auth()
        session = reconstruction_session
        page = session["page"]
        project_id = _new_project(session, "Reconstruction palette")
        _provision(session, project_id)

        page.goto(f"{session['frontend']}/dataflow/{project_id}")
        page.wait_for_load_state("domcontentloaded")
        dismiss_toasts(page)

        dataset_id = FIXTURE.required["datasets"][0]
        open_tools_palette(page, "datasets")
        row = page.locator(f'#datasets-palette [data-dataset-id="{dataset_id}"]')
        expect(row).to_have_count(1, timeout=45000)
        save_workflow_test_screenshot(
            page, SCREENSHOT_STEM, test_name="dataset_palette_row",
            fit_reactflow=False,
        )

    def test_a_package_contributes_its_templates_to_the_palette(
        self, reconstruction_session
    ):
        """Enlisting a package must put its templates in the palette, because
        that -- not the lockfile -- is where a person looks for them.
        ``curio.example-ui@1`` because it declares no python dependencies: any
        other package runs pip inside the request (see test_node_catalog.py)."""
        require_project_page()
        require_user_auth()
        session = reconstruction_session
        page = session["page"]
        project_id = _new_project(session, "Reconstruction package palette")
        api_json(
            f"{session['backend']}/api/packages/projects/{project_id}/install",
            session["token"], method="POST",
            payload={"dirName": "curio.example-ui@1"},
        )
        page.goto(f"{session['frontend']}/dataflow/{project_id}")
        page.wait_for_load_state("domcontentloaded")
        dismiss_toasts(page)
        open_tools_palette(page, "packages")
        package = page.locator(
            '#packages-palette [data-pkg-palette-coords~="curio.example-ui@1"]'
        )
        expect(package).to_have_count(1, timeout=45000)
        # The package's kinds are rows inside its accordion; the grip carries
        # data-pkg-template-id and the label sits beside it.
        row = package.locator("div:has(> [data-pkg-template-id])").filter(
            has_text="Column Filter"
        )
        expect(row).to_have_count(1, timeout=15000)


class TestThePlansCard:
    """Mode 2 of what a person judges: the plan lands whole with the reply,
    its card says what it built, and the canvas shows it."""

    def test_the_plan_lands_with_its_card_and_the_canvas_shows_it(
        self, reconstruction_session
    ):
        require_project_page()
        require_user_auth()
        session = reconstruction_session
        page = session["page"]
        project_id = _new_project(session, "Reconstruction review")
        _provision(session, project_id)
        _attach_builder(session, project_id)
        _script_the_oracle(session, solve_content=False)

        page.goto(f"{session['frontend']}/dataflow/{project_id}")
        page.wait_for_load_state("domcontentloaded")
        dismiss_toasts(page)
        panel = _open_chat(page)
        _send(panel, FIXTURE.prompt)

        expected_nodes = len(FIXTURE.expected["nodes"])
        expected_edges = len(FIXTURE.expected["edges"])
        card = panel.get_by_role(
            "group", name=re.compile(r"^Change: Plan")
        ).first
        expect(card).to_be_visible(timeout=45000)
        # The card says what it built, in the words the runtime landed it with.
        expect(card).to_contain_text(f"{expected_nodes} nodes", timeout=15000)
        expect(card).to_contain_text(f"{expected_edges} edges")
        expect(card.get_by_role("button", name="Undo")).to_be_visible()
        save_workflow_test_screenshot(
            page, SCREENSHOT_STEM, test_name="plan_card",
            fit_reactflow=False,
        )

        page.wait_for_function(
            "(n) => window.__curio_reactFlow.getNodes().length === n",
            arg=expected_nodes, timeout=45000,
        )
        spec = _saved_spec(session, project_id)
        assert len(attempt_mod.spec_nodes(spec)) == expected_nodes

        # And it is the RIGHT graph, judged by the same comparator the other
        # tiers use rather than by counting boxes.
        scored = attempt_mod.score_attempt(
            FIXTURE,
            actual_spec=spec,
            templates=TEMPLATES,
            example=_example(),
            universe=Universe(templates=frozenset(TEMPLATES)),
            solve_results={},
        )
        assert scored.comparison.templates.missing == ()
        assert scored.comparison.templates.extra == ()
        assert scored.comparison.edges.missing == ()
        assert scored.comparison.edges.extra == ()
        # The canvas is the subject, and the chat panel covers the right of it.
        panel.get_by_role("button", name="Close chat").click()
        expect(page.locator('[role="dialog"][aria-label^="Chat with"]')).to_have_count(
            0, timeout=10000
        )
        leave_agent_badge(page)
        save_workflow_test_screenshot(
            page, SCREENSHOT_STEM, test_name="applied_canvas", sweep_toasts=True,
        )


#: How long the page keeps its Solve request before it sends it (#1024). In
#: run 8 of build 39320211415 the test reloaded the page 45 ms after the page
#: made that request. The request was still waiting for its CORS preflight, so
#: the reload cancelled it, the server never started Solve, and nothing was
#: there to re-attach to or to write. Holding the request plays that slow start
#: on every run. A reload replaces the page in tens of milliseconds, so a test
#: that reloads before the server has answered Solve always loses the request.
SOLVE_REQUEST_HOLD_MS = 3000

#: Wraps ``window.fetch`` in the current page only, so the reload drops it.
#: The whole-plan Solve, ``POST .../attachments/<id>/solve/stream``, waits
#: ``holdMs`` before it is sent; every other request goes straight through.
#: ``window.__curioSolveHold`` counts the requests it held and sent. It works
#: in the page rather than through ``page.route``, for the reason
#: ``utils/run_all.py`` gives: the sync API runs a route handler on the
#: dispatcher thread.
_HOLD_THE_SOLVE_REQUEST_JS = r"""(holdMs) => {
    const real = window.fetch.bind(window);
    const hold = { held: 0, sent: 0 };
    window.__curioSolveHold = hold;
    window.fetch = (input, init) => {
        const url = typeof input === 'string' ? input : (input && input.url) || '';
        const method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
        if (method !== 'POST' || !/\/attachments\/[^/]+\/solve\/stream$/.test(url)) {
            return real(input, init);
        }
        hold.held += 1;
        return new Promise((resolve) => setTimeout(resolve, holdMs)).then(() => {
            hold.sent += 1;
            return real(input, init);
        });
    };
    return true;
}"""


class TestSolveProgressAndReconnection:
    """Solve is a detached job (``DEC-073``). The strip must report it, and a
    reload must re-attach rather than lose it."""

    def test_solve_reports_progress_survives_a_reload_and_writes_content(
        self, reconstruction_session
    ):
        require_project_page()
        require_user_auth()
        session = reconstruction_session
        page = session["page"]
        project_id = _new_project(session, "Reconstruction solve")
        _provision(session, project_id)
        _attach_builder(session, project_id)
        _script_the_oracle(session)

        page.goto(f"{session['frontend']}/dataflow/{project_id}")
        page.wait_for_load_state("domcontentloaded")
        dismiss_toasts(page)
        panel = _open_chat(page)
        _send(panel, FIXTURE.prompt)
        # The plan lands with the reply.
        expect(panel.get_by_role("group", name=re.compile(r"^Change: Plan")).first).to_be_visible(timeout=45000)

        strip = page.get_by_role("group", name="Dataflow Builder").first
        expect(strip).to_be_visible(timeout=20000)
        # The whole-plan button, named by its text. Each pending node's row has
        # its own "Solve node <id> on its own" button, which a prefix match
        # would also hit, and those rows may render before this one.
        solve = strip.get_by_role("button", name=re.compile(r"^(Solve|Retry \d+ \w+)$"))
        expect(solve).to_be_visible(timeout=20000)
        assert page.evaluate(_HOLD_THE_SOLVE_REQUEST_JS, SOLVE_REQUEST_HOLD_MS)
        # Solve has started once the server answers its request: the handler
        # starts the detached job before it streams anything back. A reload
        # before that answer cancels the request with the page, and then no
        # job exists for the reload to find (#1024).
        with page.expect_response(
            lambda r: r.request.method == "POST" and r.url.endswith("/solve/stream"),
            timeout=60000,
        ) as solve_answer:
            solve.click()
        answer = solve_answer.value
        # An OK answer is the job's event stream, open until the job ends, so
        # only a refusal is read.
        assert answer.ok, (
            f"the server refused Solve: HTTP {answer.status} {answer.text()[:300]}"
        )

        # The run is reported while it runs: the strip's per-node progress list
        # is the surface a person watches. The list is on screen from the moment
        # the plan is applied, with every node pending, so it is no sign that
        # Solve started; the answer above is.
        progress = panel.get_by_label("Plan node progress")
        expect(progress).to_be_visible(timeout=30000)
        hold = page.evaluate("() => window.__curioSolveHold")
        assert hold and hold["held"] == 1, (
            f"the Solve request never went through the hold ({hold}), so this "
            "test raced nothing"
        )

        # A reload must re-attach to the SAME detached job, not start over and
        # not lose it (``GET .../jobs/stream``).
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        dismiss_toasts(page)
        panel = _open_chat(page)
        # The per-node list survives the run's end, so it is the proof either
        # way; a text match would also hit the agent's own description.
        expect(panel.get_by_label("Plan node progress")).to_be_visible(timeout=60000)

        # Whatever the run's outcome, what landed must be on disk and on the
        # canvas -- and every executable node that passed carries its code.
        def _content_landed() -> bool:
            nodes = attempt_mod.spec_nodes(_saved_spec(session, project_id))
            return any((node.get("content") or "").strip() for node in nodes)

        page.wait_for_timeout(1000)
        for _ in range(60):
            if _content_landed():
                break
            page.wait_for_timeout(1000)
        spec = _saved_spec(session, project_id)
        filled = [
            node for node in attempt_mod.spec_nodes(spec)
            if (node.get("content") or "").strip()
        ]
        assert filled, "Solve wrote nothing to the persisted dataflow"
        code_node = next(
            (n for n in filled if n.get("type") == "curio.builtin/data-loading"), None
        )
        if code_node:
            assert "curio_data_path" in read_node_code(page, code_node["id"]), (
                "the content Solve wrote is on the server but not in the "
                "node's editor on the canvas"
            )
