"""Playwright E2E: a node's Provenance button opens its runs in the provenance drawer.

A Python node runs twice, its code typed in between: the typing is an entry of
its own, named after the person, before the second run. The dataflow is saved,
so its history is the server's. The first run's code is put back from the
drawer, without a run, though it is the code the node loaded with; the typing
and the run that follow then branch from that first run. The drawer lists the
line to the newest run, with the entries left behind folded under the run they
left from; opened, the fold shows them on a line of their own. A click opens a
run: what it read and returned, when it ran and its code. A notebook cell's
button opens the same drawer.

A run's entry goes to the server once the run has ended, on a request of its
own, while what the person types next goes on the dataflow's socket and can
get there first. The run still comes first: with its entry held in the page
until the typing after it is on the server, the drawer lists the run, the
typing and the next run on one line. So it does when that typing is an entry
already, after a 10 s pause, before the run's entry comes; and typing that
went on past a run's start is two entries, one each side of the run.

A run's times come from the server's clock, not the browser's, so no fixed date
reaches them. The frame shows them on one line, which the screenshot masks.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_node_provenance_drawer_e2e.py -v
"""
from __future__ import annotations

import re
import time
import uuid
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    api_json,
    dismiss_toasts,
    frame_nodes,
    no_tooltip,
    node_locator,
    play_node,
    read_node_code,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    save_workflow_test_screenshot,
    set_node_code,
    stub_login_and_enter_workflow,
    wait_for_drawer_closed,
    wait_for_run_guard_released,
)
from .walkthroughs.steps import (
    PROVENANCE_DRAWER,
    PROVENANCE_PANEL,
    await_drawer_at_rest,
    park_pointer_off_drawer,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

TEST_NAME = "test_a_nodes_runs_open_in_the_provenance_drawer"

#: Who runs and types, as the drawer names the typing.
OWNER = "Runs Owner"
NODE = "runs-node"
NODE_TYPE = "curio.builtin/computation-analysis"
FIRST = "return 1\n"
SECOND = "return 2\n"
THIRD = "return 3\n"
#: The menu bar, which holds the Canvas | Notebook switch.
BAR = "header[data-curio-menu-bar]"
ACTIVE = re.compile(r"\bactive\b")

#: Holds the first run entry the page sends the server (``POST
#: .../history/nodes/<node>/runs``) until the test lets it go with
#: ``window.__curio_heldRunEntry.release()``, as a slow request would. Its
#: ``held`` turns true once the entry is held.
_HOLD_THE_FIRST_RUN_ENTRY_JS = r"""(() => {
    const send = window.fetch.bind(window);
    const hold = window.__curio_heldRunEntry = { held: false, release: null };
    window.fetch = (input, init) => {
        const href = typeof input === "string" ? input : (input instanceof URL ? input.href : input.url);
        const method = String((init && init.method) || (input instanceof Request ? input.method : "GET"));
        const path = new URL(href, window.location.href).pathname;
        if (hold.held || method.toUpperCase() !== "POST" || !/\/history\/nodes\/[^/]+\/runs$/.test(path)) {
            return send(input, init);
        }
        hold.held = true;
        return new Promise((resolve, reject) => {
            hold.release = () => { send(input, init).then(resolve, reject); };
        });
    };
})()"""

#: As :data:`_HOLD_THE_FIRST_RUN_ENTRY_JS`, for the second run entry the page
#: sends: the first goes as it comes.
_HOLD_THE_SECOND_RUN_ENTRY_JS = r"""(() => {
    const send = window.fetch.bind(window);
    const hold = window.__curio_heldRunEntry = { sent: 0, held: false, release: null };
    window.fetch = (input, init) => {
        const href = typeof input === "string" ? input : (input instanceof URL ? input.href : input.url);
        const method = String((init && init.method) || (input instanceof Request ? input.method : "GET"));
        const path = new URL(href, window.location.href).pathname;
        if (method.toUpperCase() !== "POST" || !/\/history\/nodes\/[^/]+\/runs$/.test(path)) {
            return send(input, init);
        }
        hold.sent += 1;
        if (hold.sent !== 2) return send(input, init);
        hold.held = true;
        return new Promise((resolve, reject) => {
            hold.release = () => { send(input, init).then(resolve, reject); };
        });
    };
})()"""


def _spec() -> dict:
    return {
        "dataflow": {
            "name": "Node runs",
            "task": "",
            "description": "",
            "packages": [],
            "datasets": [],
            "nodes": [{
                "id": NODE, "type": NODE_TYPE, "x": 0, "y": 0,
                "in": "DEFAULT", "out": "DEFAULT", "goal": "",
                "metadata": {"keywords": []}, "content": FIRST,
            }],
            "edges": [],
        },
    }


def _run(page, code: str) -> None:
    set_node_code(page, NODE, code)
    run_node_and_wait(page, NODE, node_type="computation-analysis", timeout_ms=120000)


def _open_runs(page):
    node_locator(page, NODE).locator('.nav-link[data-rr-ui-event-key="provenance"]').first.click()
    expect(page.get_by_role("dialog", name="Node provenance")).to_be_visible(timeout=20000)
    await_drawer_at_rest(page)
    return page.locator(PROVENANCE_PANEL)


def _close(page) -> None:
    page.keyboard.press("Escape")
    wait_for_drawer_closed(page, PROVENANCE_DRAWER)


def _shown(panel) -> list[str]:
    return panel.locator("[data-provenance-item]").evaluate_all(
        "els => els.map((el) => el.dataset.provenanceItem)"
    )


def _run_item(panel, run_id: str):
    return panel.locator(f'[data-provenance-item="{run_id}"]')


def _open_run(panel, run_id: str) -> None:
    item = _run_item(panel, run_id)
    head = item.locator("button").first
    if head.get_attribute("aria-expanded") != "true":
        head.click()
    expect(item.get_by_role("button", name="Put this code back in the node", exact=True)).to_be_visible()


def _code_on_the_server(backend_url: str, token: str, project_id: str):
    """The node's code as the server's doc of the dataflow holds it now."""
    spec = api_json(f"{backend_url}/api/projects/{project_id}", token)["spec"]
    return next((node.get("content") for node in spec["dataflow"]["nodes"] if node["id"] == NODE), None)


def _kinds_on_the_server(backend_url: str, token: str, project_id: str) -> list[str]:
    """The node's entries as the server's history lists them: run or edit each."""
    listed = api_json(f"{backend_url}/api/projects/{project_id}/history/nodes/{NODE}", token)
    return [entry.get("kind", "run") for entry in listed["entries"]]


def _until(page, read, want, what: str, seconds: float = 20) -> None:
    """Read *read()* every 100 ms until it is *want*, for up to *seconds*."""
    deadline = time.time() + seconds
    while read() != want:
        assert time.time() < deadline, what
        page.wait_for_timeout(100)


def _enter_with_a_held_run_entry(page, app_frontend, current_server: str, hold_js: str) -> tuple[str, str]:
    """The owner on the node's dataflow, with *hold_js* in the page: its
    sign-in token and the dataflow's id."""
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    page.add_init_script(hold_js)
    login = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name=OWNER,
        username=f"node_runs_{uuid.uuid4().hex[:8]}",
        project_name="Node runs",
        project_spec=_spec(),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)
    frame_nodes(page, [NODE])
    return login["token"], login["project"]["id"]


def _open_run_from_off_the_drawer(page, panel, run_id: str) -> None:
    """Open the run *run_id*, the pointer moved off the drawer first. A row's
    tooltip shows above it, over the row before, and stays while the pointer
    is on it: with the pointer left on the next row, a click on *run_id*'s
    row would land on that tooltip."""
    park_pointer_off_drawer(page)
    no_tooltip(page, "the drawer, before a run opens", timeout=5000)
    _open_run(panel, run_id)


def _release_the_held_run_entry(page) -> None:
    with page.expect_response(
        lambda answer: answer.request.method == "POST" and answer.url.endswith(f"/history/nodes/{NODE}/runs"),
    ) as noted:
        page.evaluate("() => { window.__curio_heldRunEntry.release(); }")
    assert noted.value.status == 201, f"the held run's entry was answered {noted.value.status}"


def test_a_nodes_runs_open_in_the_provenance_drawer(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name=OWNER,
        username=f"node_runs_{uuid.uuid4().hex[:8]}",
        project_name="Node runs",
        project_spec=_spec(),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)
    frame_nodes(page, [NODE])

    _run(page, FIRST)
    _run(page, SECOND)

    # The two runs and the typing between them, the second run in use: the
    # next run would branch from it.
    panel = _open_runs(page)
    expect(panel.get_by_text(re.compile(r"^Runs of \S"))).to_be_visible()
    expect(panel.locator("[data-provenance-item]")).to_have_count(3, timeout=20000)
    runs = _shown(panel)
    first_run, typed, second_run = runs
    expect(_run_item(panel, typed)).to_contain_text(f"{OWNER} edited")
    expect(_run_item(panel, second_run)).to_have_attribute("data-provenance-current", "true")

    # Opening the first run shows it and puts nothing back.
    _open_run(panel, first_run)
    first = _run_item(panel, first_run)
    expect(first).to_contain_text("In: none | Out: VALUE")
    expect(first.get_by_text(re.compile(r"^Started "))).to_be_visible()
    expect(first.locator("pre")).to_have_text(re.compile(r"^\s*return 1\s*$"))
    assert read_node_code(page, NODE).strip() == SECOND.strip(), "opening a run changed the node's code"

    # Its button puts that code back, though it is the code the node loaded
    # with, and the next run branches from it. Nothing runs, and no entry is
    # added.
    first.get_by_role("button", name="Put this code back in the node", exact=True).click()
    expect(first).to_have_attribute("data-provenance-current", "true")
    expect(_run_item(panel, second_run)).not_to_have_attribute("data-provenance-current", "true")
    assert len(_shown(panel)) == 3, "putting a run's code back ran the node"
    _close(page)
    code_pill = node_locator(page, NODE).locator('.nav-link[data-rr-ui-event-key="code"]').first
    expect(code_pill).to_have_class(ACTIVE)
    assert read_node_code(page, NODE).strip() == FIRST.strip(), (
        "the first run's code did not go back in the node"
    )

    # The typing and the third run branch from the first: the list keeps the
    # line to them, with the typing and the second run folded under the first.
    # Opened, the fold shows them on a line of their own.
    _run(page, THIRD)
    panel = _open_runs(page)
    fold = panel.get_by_role("button", name=re.compile(r"^2 entries on another branch$"))
    expect(fold).to_have_attribute("aria-expanded", "false", timeout=20000)
    # The typing, then the run: both, once the run is in.
    expect(panel.locator("[data-provenance-item]")).to_have_count(3, timeout=20000)
    runs = _shown(panel)
    assert len(runs) == 3 and runs[0] == first_run and not set(runs[1:]) & {typed, second_run}, (
        f"the list should show the first run, then the typing and the third run, the rest folded: {runs}"
    )
    typed_again, third_run = runs[1:]
    expect(_run_item(panel, typed_again)).to_contain_text(f"{OWNER} edited")
    expect(_run_item(panel, third_run)).to_have_attribute("data-provenance-current", "true")
    fold.click()
    assert _shown(panel) == [first_run, typed, second_run, typed_again, third_run]
    lines = {
        run_id: _run_item(panel, run_id).evaluate("el => el.closest('ol').dataset.provenanceLine")
        for run_id in (first_run, typed, second_run, typed_again, third_run)
    }
    assert lines == {first_run: "0", typed: "1", second_run: "1", typed_again: "0", third_run: "0"}, lines

    _open_run(panel, third_run)
    park_pointer_off_drawer(page)
    save_workflow_test_screenshot(
        page, "node-provenance-list", test_name=TEST_NAME, fit_reactflow=False, clip_selector=PROVENANCE_PANEL,
    )
    _close(page)

    # A notebook cell's button opens the same drawer, with the same runs.
    radio = page.locator(BAR).get_by_role("radio", name="Notebook view", exact=True)
    radio.click()
    expect(radio).to_have_attribute("aria-checked", "true")
    panel = _open_runs(page)
    expect(panel.locator("[data-provenance-item]")).to_have_count(3, timeout=20000)
    assert sorted(_shown(panel)) == sorted([first_run, typed_again, third_run]), _shown(panel)
    _close(page)


def test_a_run_comes_before_the_typing_that_reaches_the_server_ahead_of_its_entry(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """The first run's entry is held in the page until the typing after the
    run is on the server, as when that typing beats the entry's request there.
    The run still comes first: the drawer lists it, then the typing, then the
    second run, in use, on one line, with nothing on another branch."""
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    page.add_init_script(_HOLD_THE_FIRST_RUN_ENTRY_JS)
    login = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name=OWNER,
        username=f"node_runs_{uuid.uuid4().hex[:8]}",
        project_name="Node runs",
        project_spec=_spec(),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)
    frame_nodes(page, [NODE])

    _run(page, FIRST)
    page.wait_for_function("() => window.__curio_heldRunEntry.held", timeout=20000)
    set_node_code(page, NODE, SECOND)
    token, project_id = login["token"], login["project"]["id"]
    deadline = time.time() + 20
    while _code_on_the_server(current_server, token, project_id) != SECOND:
        assert time.time() < deadline, "the typing after the first run never reached the server"
        page.wait_for_timeout(100)
    with page.expect_response(
        lambda answer: answer.request.method == "POST" and answer.url.endswith(f"/history/nodes/{NODE}/runs"),
    ) as noted:
        page.evaluate("() => { window.__curio_heldRunEntry.release(); }")
    assert noted.value.status == 201, f"the first run's entry was answered {noted.value.status}"
    run_node_and_wait(page, NODE, node_type="computation-analysis", timeout_ms=120000)

    panel = _open_runs(page)
    expect(panel.locator("[data-provenance-item]")).to_have_count(3, timeout=20000)
    first_run, typed, second_run = _shown(panel)
    expect(_run_item(panel, first_run)).to_contain_text("In: none | Out: VALUE")
    expect(_run_item(panel, typed)).to_contain_text(f"{OWNER} edited")
    expect(_run_item(panel, second_run)).to_have_attribute("data-provenance-current", "true")
    expect(panel.get_by_role("button", name=re.compile(r"on another branch$"))).to_have_count(0)
    _open_run(panel, first_run)
    expect(_run_item(panel, first_run).locator("pre")).to_have_text(re.compile(r"^\s*return 1\s*$"))
    _close(page)


def test_a_run_comes_before_the_typing_that_became_an_entry_before_the_runs_entry_came(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """The first run's entry is held in the page while the typing after the
    run pauses 10 s and becomes an entry, as typing while a long run goes
    does. The run still comes first: the drawer lists it, then the typing,
    then the second run, in use, on one line, with nothing on another
    branch."""
    token, project_id = _enter_with_a_held_run_entry(page, app_frontend, current_server,
                                                     _HOLD_THE_FIRST_RUN_ENTRY_JS)
    _run(page, FIRST)
    page.wait_for_function("() => window.__curio_heldRunEntry.held", timeout=20000)
    set_node_code(page, NODE, SECOND)
    _until(page, lambda: _kinds_on_the_server(current_server, token, project_id), ["edit"],
           "the typing after the first run never became an entry", seconds=60)
    _release_the_held_run_entry(page)
    run_node_and_wait(page, NODE, node_type="computation-analysis", timeout_ms=120000)

    panel = _open_runs(page)
    expect(panel.locator("[data-provenance-item]")).to_have_count(3, timeout=20000)
    first_run, typed, second_run = _shown(panel)
    expect(_run_item(panel, first_run)).to_contain_text("In: none | Out: VALUE")
    expect(_run_item(panel, typed)).to_contain_text(f"{OWNER} edited")
    expect(_run_item(panel, second_run)).to_have_attribute("data-provenance-current", "true")
    expect(panel.get_by_role("button", name=re.compile(r"on another branch$"))).to_have_count(0)
    _open_run_from_off_the_drawer(page, panel, first_run)
    expect(_run_item(panel, first_run).locator("pre")).to_have_text(re.compile(r"^\s*return 1\s*$"))
    _close(page)


def test_typing_that_goes_on_past_a_runs_start_is_an_entry_each_side_of_the_run(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """The owner types, runs the node and types on, with no pause and without
    leaving the editor, as Ctrl+Enter in it lets her; the second run's entry
    is held in the page until the typing after its start is on the server.
    The drawer lists the first run, the typing up to the code the second run
    ran, that run, the typing after it and the third run, in use, on one
    line, with nothing on another branch."""
    token, project_id = _enter_with_a_held_run_entry(page, app_frontend, current_server,
                                                     _HOLD_THE_SECOND_RUN_ENTRY_JS)
    with page.expect_response(
        lambda answer: answer.request.method == "POST" and answer.url.endswith(f"/history/nodes/{NODE}/runs"),
    ) as noted:
        _run(page, FIRST)
    assert noted.value.status == 201, f"the first run's entry was answered {noted.value.status}"

    # The first run over, the typing, the second run's start and the typing
    # after it follow each other well within the typing's 10 s pause.
    wait_for_run_guard_released(page, timeout_ms=120000)
    set_node_code(page, NODE, SECOND)
    _until(page, lambda: _code_on_the_server(current_server, token, project_id), SECOND,
           "the typing before the second run never reached the server")
    # A run takes the node's code once the server holds the tab's changes,
    # just before it asks the server to start.
    with page.expect_response(
        lambda answer: answer.request.method == "POST" and answer.url.endswith(f"/api/projects/{project_id}/runs"),
    ) as started:
        play_node(page, NODE)
    assert started.value.ok, f"the second run was answered {started.value.status}"
    # The typing goes on until the run's entry is held, as someone still
    # typing does: a 10 s pause would end it there.
    set_node_code(page, NODE, THIRD)
    deadline = time.time() + 120
    while not page.evaluate("() => window.__curio_heldRunEntry.held"):
        assert time.time() < deadline, "the second run's entry never left the page"
        page.wait_for_timeout(2000)
        set_node_code(page, NODE, THIRD + "\n")
        set_node_code(page, NODE, THIRD)
    _until(page, lambda: _code_on_the_server(current_server, token, project_id), THIRD,
           "the typing after the second run's start never reached the server")
    assert _kinds_on_the_server(current_server, token, project_id) == ["run"], (
        "the typing was an entry before the second run's entry came: it paused, so it never went on past "
        "the run's start"
    )
    _release_the_held_run_entry(page)
    with page.expect_request(
        lambda request: request.method == "POST" and request.url.endswith(f"/history/nodes/{NODE}/runs"),
        timeout=150000,
    ) as third_entry:
        run_node_and_wait(page, NODE, node_type="computation-analysis", timeout_ms=120000)
    # A run's entry names the code the node held when it started, which the
    # typing that went on past the second run's start had left.
    named = (third_entry.value.post_data_json or {}).get("code")
    assert named == THIRD, f"the third run's entry named {named!r}, not the code the node held at its start"

    panel = _open_runs(page)
    expect(panel.locator("[data-provenance-item]")).to_have_count(5, timeout=20000)
    shown = _shown(panel)
    titles = ["In: none | Out: VALUE", f"{OWNER} edited", "In: none | Out: VALUE", f"{OWNER} edited",
              "In: none | Out: VALUE"]
    for item, title in zip(shown, titles):
        expect(_run_item(panel, item)).to_contain_text(title)
    expect(_run_item(panel, shown[-1])).to_have_attribute("data-provenance-current", "true")
    expect(panel.get_by_role("button", name=re.compile(r"on another branch$"))).to_have_count(0)
    _open_run_from_off_the_drawer(page, panel, shown[2])
    expect(_run_item(panel, shown[2]).locator("pre")).to_have_text(re.compile(r"^\s*return 2\s*$"))
    _close(page)
