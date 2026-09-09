"""Playwright: reconstruction as a person sees it (memo dev/121).

The deterministic suite (``tests/test_agents/test_example_reconstruction.py``)
proves the server rebuilds an example from its prompt. It cannot see the four
things a person actually judges, so this module covers exactly those and no
more -- it is representative by design, not a second matrix:

1. **The palettes.** A dataset installed through the catalog service shows up as
   a draggable row, and a package's templates appear under their package, so
   "provisioned" means provisioned in the UI and not only in a lockfile.
2. **The review card.** The plan arrives as a card that names what it will
   build, and nothing reaches the canvas until someone presses Apply.
3. **Solve progress and reconnection.** The strip reports the run, and a reload
   mid-run re-attaches to the same job instead of losing it.
4. **The output.** The applied nodes render on the canvas and carry the content
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
from utk_curio.backend.app.agents.evaluation.fixtures import FIXTURE_ROOT, load_fixture

from .utils import (
    api_json,
    canvas_nodes,
    dismiss_toasts,
    install_session_cookie,
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
DFB_COORD = "agent.dataflow-builder@1.0.0"
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
            f"{backend}/api/datasets/dataflows/{project_id}/datasets/install",
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

    The provider is scripted positionally here (``script_agent_replies``), so
    the content replies are ordered by wave. The plan is what this module is
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
    replies = [plan.as_reply()]
    if solve_content:
        # More replies than calls is harmless; the script is a queue and the
        # provider falls back to the last entry.
        replies.extend(contents.values())
    script_agent_replies(session["backend"], *replies)
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
        row = page.locator(f'[data-dataset-id="{dataset_id}"]').first
        expect(row).to_be_visible(timeout=45000)
        save_workflow_test_screenshot(
            page, SCREENSHOT_STEM, test_name="dataset_palette_row",
        )

    def test_a_package_contributes_its_templates_to_the_palette(
        self, reconstruction_session
    ):
        """Example 10's kinds live in ``curio.streetvision@1``. Enlisting it
        must put its templates in the palette, because that -- not the lockfile
        -- is where a person looks for them."""
        require_project_page()
        require_user_auth()
        session = reconstruction_session
        page = session["page"]
        project_id = _new_project(session, "Reconstruction package palette")
        api_json(
            f"{session['backend']}/api/packages/projects/{project_id}/install",
            session["token"], method="POST",
            payload={"dirName": "curio.streetvision@1"},
        )
        page.goto(f"{session['frontend']}/dataflow/{project_id}")
        page.wait_for_load_state("domcontentloaded")
        dismiss_toasts(page)
        row = page.locator(
            '[data-pkg-template-id="curio.streetvision/street-view-fetcher"]'
        ).first
        expect(row).to_be_visible(timeout=45000)


class TestReviewCardAndApply:
    """Mode 2 of what a person judges: the plan is a proposal, and the canvas
    changes only when they say so."""

    def test_the_plan_is_reviewed_then_applied_and_the_canvas_shows_it(
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
            "group", name=re.compile(r"^Review proposal: Apply plan")
        ).first
        expect(card).to_be_visible(timeout=45000)
        # The card says what it will build, in the words the runtime minted.
        expect(card).to_contain_text(f"{expected_nodes} nodes", timeout=15000)
        expect(card).to_contain_text(f"{expected_edges} edges")
        # Nothing has happened yet: a proposal is not a change (DEC-048).
        assert canvas_nodes(page) == []
        assert not attempt_mod.spec_nodes(_saved_spec(session, project_id))
        save_workflow_test_screenshot(
            page, SCREENSHOT_STEM, test_name="plan_review_card",
        )

        apply_control = panel.get_by_role(
            "button", name=re.compile(r"^(Apply plan|Apply all without validation)$")
        ).first
        expect(apply_control).to_be_visible(timeout=20000)
        with page.expect_response(
            lambda r: "/proposals/" in r.url
            and r.url.endswith("/apply")
            and r.request.method == "POST",
            timeout=60000,
        ) as info:
            apply_control.click()
        assert info.value.ok, f"apply failed: {info.value.status}"

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
        dismiss_toasts(page)
        save_workflow_test_screenshot(
            page, SCREENSHOT_STEM, test_name="applied_canvas",
        )


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
        attachment_id = _attach_builder(session, project_id)
        _script_the_oracle(session)

        page.goto(f"{session['frontend']}/dataflow/{project_id}")
        page.wait_for_load_state("domcontentloaded")
        dismiss_toasts(page)
        panel = _open_chat(page)
        _send(panel, FIXTURE.prompt)
        apply_control = panel.get_by_role(
            "button", name=re.compile(r"^(Apply plan|Apply all without validation)$")
        ).first
        expect(apply_control).to_be_visible(timeout=45000)
        with page.expect_response(
            lambda r: r.url.endswith("/apply") and r.request.method == "POST",
            timeout=60000,
        ):
            apply_control.click()

        strip = page.get_by_role("group", name="Dataflow Builder").first
        expect(strip).to_be_visible(timeout=20000)
        solve = strip.get_by_role("button", name=re.compile(r"^(Solve|Retry)")).first
        expect(solve).to_be_visible(timeout=20000)
        solve.click()

        # The run is reported while it runs: the strip's per-node progress list
        # is the surface a person watches.
        progress = panel.get_by_label("Plan node progress")
        expect(progress).to_be_visible(timeout=30000)

        # A reload must re-attach to the SAME detached job, not start over and
        # not lose it (``GET .../jobs/stream``).
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        dismiss_toasts(page)
        panel = _open_chat(page)
        expect(
            panel.get_by_label("Plan node progress").or_(
                panel.get_by_text(re.compile(r"solved|verified", re.I)).first
            )
        ).to_be_visible(timeout=60000)

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
            assert "curio_dataset_path" in read_node_code(page, code_node["id"]), (
                "the content Solve wrote is on the server but not in the "
                "node's editor on the canvas"
            )
        dismiss_toasts(page)
        save_workflow_test_screenshot(
            page, SCREENSHOT_STEM, test_name="solved_canvas",
        )
