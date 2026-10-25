"""Playwright E2E: komar41's Crown Heights example exercises the dashboard's
sharing features.

``docs/examples/dataflows/crown-heights-1550-bedford-shadow.json`` accumulates
the shadow of a tower proposed at 1550 Bedford Avenue. Its dashboard pins three
Parameter tiles (Period, a Date widget and Month), the Map Editor node that
adds the tower, the Autark map of the shadow and the table of the shade the
tower adds on Block 1259. Its "Cast sun rays on the GPU" node is an Autark
compute, which only a browser runs: on a dashboard each visitor's own page runs
it, after the server has run the Python before it, once for everyone (#1117).

* The owner runs the example, saves it and shares it. The Share menu copies
  the dashboard's link and the dataflow's, and opens the dashboard for the
  owner to lay out. A visitor with no session opens the link and sees the
  owner's results, with nothing run and no notice over them. A new date runs
  the Python before the GPU step on the server, the GPU step in the visitor's
  page and the Python after it on the server, and the map and the table draw
  it. A second visitor who
  picks the same date gets the steps before the GPU step as the first
  visitor's run kept them, runs the GPU step in its own page, and reads what
  the first one read. The saved date brings the saved results back with no
  run. Another account opens the dataflow's link and sees the owner's results,
  read-only.
* The link dev serves works on this deployment too. The shared guest's copy of
  a shipped dataflow (``projects/seed.py``) has an id made from the example's
  file name, the same on every deployment. Opened at that link, a dashboard no
  one ran fills its tiles through a run, and a new date draws them again.
  While the run goes, the table and the map say they are computing. In a
  browser with no WebGPU, they say which step could not run.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_crown_heights_dashboard_e2e.py -v
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .test_dashboard_page_e2e import (
    _Visitor,
    _catalog_ids,
    _enter,
    _files_read,
    _not_a_viewer_route,
    _project,
    _runs_started,
    _sent_results,
    _serve_hosted,
    _steps_sent,
)
from .test_map_edits_e2e import _changed, _map_pixels, _wait_for_map_drawn, _wait_for_redraw
from .utils import (
    CLOSEUP_MAX_DIFF_RATIO,
    CLOSEUP_PIXEL_THRESHOLD,
    REPO_ROOT,
    api_json,
    held_server_nodes,
    hold_server_runs,
    keep_drawing,
    node_locator,
    park_pointer,
    require_project_page,
    require_user_auth,
    require_webgpu,
    run_all_and_wait,
    save_dataflow,
    save_workflow_test_screenshot,
    stub_db_login,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

EXAMPLE = Path(REPO_ROOT, "docs", "examples", "dataflows", "crown-heights-1550-bedford-shadow.json")
NAME = "Crown Heights shade from 1550 Bedford Avenue"
STEM = "crown-heights-dashboard"

#: The namespace of the ids the shared guest's copies of the shipped dataflows
#: get (``_EXAMPLES_NAMESPACE`` in ``projects/seed.py``), written out here: a
#: shared link is made with it, so a change to it breaks every link already
#: shared and must fail this test.
SHIPPED_IDS = uuid.UUID("a3f1c0d4-1111-4b8e-9a6e-c0ff33ee5eed")
#: The id in the link to the shipped copy of the example: the same on dev, on
#: any other deployment and here.
LINK_ID = str(uuid.uuid5(SHIPPED_IDS, "dataflows/crown-heights-1550-bedford-shadow"))

#: The example's nodes, by the title each one's header shows.
LABELS = {
    "buildings": "Load existing buildings",
    "block": "Load Block 1259 outline",
    "streets": "Load streets",
    "date": "Pick a date (for Date)",
    "tower": "Add proposed tower (1550 Bedford Ave)",
    "prepare": "Prepare tower for the GPU",
    "grid": "Make ground grid and selected days",
    "rays": "Cast sun rays on the GPU",
    "shadow": "Read shadow per cell",
    "shaded": "Keep shaded cells for the map",
    "extent": "Map extent (keeps layers whole)",
    "average": "Average shade on Block 1259",
    "map": "Map: tower's accumulated shadow",
    "table": "Table: shade added on Block 1259",
}
#: What the Date tile's field is called.
DATE_LABEL = "Date (when Period is Date)"
#: The nodes before the map and the table that a date does not reach.
NOT_REACHED = ("buildings", "block", "streets", "tower", "extent")

#: How long a run of the chain may take: the Python before the GPU step, the
#: page's GPU step, then the Python after it, on a busy GPU runner.
RUN_TIMEOUT_MS = 240000

#: A shade as the table writes it: minutes, or hours past 90 minutes.
SHADE_RE = re.compile(r"^\d[\d,.]* (min|h)$")

#: What an Autark map's database asks of the backend on any page it draws on:
#: DuckDB's extensions, which Curio serves itself.
_EXTENSIONS_RE = re.compile(r"^GET /file/vendor/duckdb-extensions/")

#: What a tile with nothing yet says while a viewer's run makes it, title and
#: hint (``NODE_EMPTY_COPY["upstream-running"]``).
COMPUTING = ("Computing...", "Results will be shown here once they are ready.")

#: Before the page's own scripts: a browser with no WebGPU, as the
#: walkthroughs make one.
_NO_WEBGPU_JS = "Object.defineProperty(navigator, 'gpu', { configurable: true, value: undefined });"

#: The cells of the first row of the table node *id* draws, or null.
_TABLE_ROW_JS = """(id) => {
    const node = document.querySelector('.react-flow__node[data-id="' + id + '"]');
    const row = node && node.querySelector('table tbody tr');
    return row ? Array.from(row.querySelectorAll('td')).map((cell) => cell.textContent.trim()) : null;
}"""


def _spec() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _ids() -> dict[str, str]:
    """The example's node ids, by the names in :data:`LABELS`."""
    by_label = {
        (node.get("metadata") or {}).get("packageTemplateLabel"): node["id"]
        for node in _spec()["dataflow"]["nodes"]
    }
    missing = [label for label in LABELS.values() if label not in by_label]
    assert not missing, f"the example has no node titled {missing!r}"
    return {name: by_label[label] for name, label in LABELS.items()}


def _table_reads(page, table_id: str, selection: str, *, timeout_ms: int = RUN_TIMEOUT_MS) -> str:
    """Wait until the table's row is *selection*'s, and return its shade,
    such as ``40 min``."""
    deadline = time.time() + timeout_ms / 1000
    row = None
    while True:
        row = page.evaluate(_TABLE_ROW_JS, table_id)
        shades = [cell for cell in row or [] if SHADE_RE.match(cell)]
        if row and selection in row and shades:
            return shades[0]
        if time.time() >= deadline:
            raise AssertionError(f"the table never read {selection}: its first row is {row!r}")
        page.wait_for_timeout(500)


def _pick_date(page, date_id: str, day: str) -> None:
    """Set the Date tile to *day*, ``YYYY-MM-DD``; leaving the field commits it."""
    field = node_locator(page, date_id).get_by_label(DATE_LABEL, exact=True)
    expect(field).to_be_enabled(timeout=20000)
    field.fill(day)
    field.blur()


def _map_canvas(map_id: str) -> str:
    return f"#autk-grammar-map-{map_id}"


def _step_outputs(visitor: "_Visitor") -> list[dict[str, str]]:
    """Each run the visitor's page followed, in order: the output of every
    step it finished, by node id. A step whose output was kept from an earlier
    run hands on that run's output again."""
    runs = []
    for stream in visitor.streams:
        outputs = {}
        for block in stream.strip().split("\n\n"):
            kind = block.split("\n", 1)[0].removeprefix("event: ")
            if kind != "step_finished" or "data: " not in block:
                continue
            payload = json.loads(block.split("data: ", 1)[1])
            if payload.get("status") == "ok":
                outputs[payload["nodeId"]] = (payload.get("output") or {}).get("path")
        runs.append(outputs)
    return runs


def _start_answers(visitor: "_Visitor") -> list[tuple[int, str | None]]:
    """How each start of a viewer's run was answered: its status, and the id of
    the run to follow (none when the values need no run)."""
    answers = []
    for line in visitor.answered:
        asked, _, answer = line.partition(" -> ")
        if not (asked.startswith("POST ") and asked.endswith("/dashboard/runs")):
            continue
        status, _, body = answer.partition(" ")
        try:
            run_id = json.loads(body).get("runId")
        except ValueError:
            run_id = None
        answers.append((int(status) if status.isdigit() else 0, run_id))
    return answers


def _beyond_viewer_runs(visitor: "_Visitor") -> list[str]:
    """What the visitor's page asked beyond a viewer's run and DuckDB's extensions."""
    return [line for line in _not_a_viewer_route(visitor.asked) if not _EXTENSIONS_RE.match(line)]


def _ran_since(visitor: "_Visitor", earlier: int) -> list[dict[str, str]]:
    """The step outputs of the runs the visitor's page followed after its first *earlier*."""
    return _step_outputs(visitor)[earlier:]


def _tile_says(page, node_id: str, reason: str, *words: str, timeout_ms: int) -> None:
    """The tile of *node_id* shows only its notice for *reason*, which reads each of *words*."""
    notice = node_locator(page, node_id).locator(f'[data-curio-node-empty="{reason}"]')
    for said in words:
        expect(notice).to_contain_text(said, timeout=timeout_ms)


#: The reason the tile of node *id* gives for showing nothing, or null.
_TILE_EMPTY_JS = """(id) => {
    const node = document.querySelector('.react-flow__node[data-id="' + id + '"]');
    const empty = node && node.querySelector('[data-curio-node-empty]');
    return empty ? empty.getAttribute('data-curio-node-empty') : null;
}"""


def _reasons_until_read(page, table_id: str, selection: str, *, timeout_ms: int = RUN_TIMEOUT_MS) -> set[str]:
    """Every reason the table gives for showing nothing until its row is
    *selection*'s, read every 100 ms."""
    seen: set[str] = set()
    deadline = time.time() + timeout_ms / 1000
    while True:
        reason = page.evaluate(_TILE_EMPTY_JS, table_id)
        if reason:
            seen.add(reason)
        row = page.evaluate(_TABLE_ROW_JS, table_id)
        if row and selection in row and any(SHADE_RE.match(cell) for cell in row):
            return seen
        if time.time() >= deadline:
            raise AssertionError(f"the table never read {selection}: it said {sorted(seen)!r}, its first row {row!r}")
        page.wait_for_timeout(100)


def _until_held(backend: str, visitor: "_Visitor") -> None:
    """Until a step of a run on *backend* waits for the hold to end."""
    deadline = time.time() + 60
    while held_server_nodes(backend) < 1:
        if time.time() >= deadline:
            raise AssertionError("the run on open never reached a step on the server" + visitor.story())
        visitor.page.wait_for_timeout(250)


@pytest.mark.xdist_group("crown-heights-sharing")
def test_the_owner_shares_the_crown_heights_dashboard_and_each_visitor_tries_a_date(
    app_frontend: "FrontendPage", current_server, page, browser, monkeypatch,
):
    require_project_page()
    require_user_auth()
    ids = _ids()

    # The owner runs the example on the canvas and saves it, which saves the
    # outputs the pinned tiles read.
    session = _enter(page, app_frontend, current_server, prefix="crown_owner", spec=_spec())
    require_webgpu(page)
    project_id = session["project"]["id"]
    run_all_and_wait(page, timeout_ms=300000)
    # komar41's figure for Dec 21, the saved date.
    assert _table_reads(page, ids["table"], "Dec 21") == "40 min"
    _wait_for_map_drawn(page, ids["map"], "the owner's Run All")
    save_dataflow(page)
    recorded = {output["node_id"] for output in _project(current_server, session["token"], project_id)["outputs"]}
    read_by_tiles = {ids[name] for name in ("buildings", "block", "streets", "tower", "extent", "shaded", "average")}
    assert read_by_tiles <= recorded, (
        f"the save recorded {sorted(recorded)!r}, not every output the pinned tiles read {sorted(read_by_tiles)!r}"
    )

    # The Share menu: the dashboard's link, the dataflow's link, and the
    # dashboard opened for the owner, who may lay it out.
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.get_by_test_id("share-menu-btn").click(force=True)
    page.get_by_text("Copy dashboard link", exact=True).click()
    dashboard_link = page.evaluate("() => navigator.clipboard.readText()")
    assert dashboard_link == f"{app_frontend.base_url}/dashboard/{project_id}", dashboard_link
    page.get_by_test_id("share-menu-btn").click(force=True)
    page.get_by_text("Copy dataflow link", exact=True).click()
    dataflow_link = page.evaluate("() => navigator.clipboard.readText()")
    assert dataflow_link == f"{app_frontend.base_url}/dataflow/{project_id}", dataflow_link
    page.get_by_test_id("share-menu-btn").click(force=True)
    with page.context.expect_page() as popup:
        page.get_by_test_id("open-dashboard-link").click()
    owners_tab = popup.value
    owners_tab.wait_for_url(re.compile(rf"/dashboard/{project_id}$"), timeout=30000)
    owners_tab.get_by_test_id("edit-layout-btn").wait_for(state="visible", timeout=45000)
    assert _table_reads(owners_tab, ids["table"], "Dec 21") == "40 min"
    _wait_for_map_drawn(owners_tab, ids["map"], "the owner opened the dashboard")
    owners_tab.close()
    # Off the canvas first: it can still save on its way out.
    page.goto("about:blank")
    before = _project(current_server, session["token"], project_id)
    catalog_before = _catalog_ids(current_server, session["token"], project_id)
    hosted = _serve_hosted(app_frontend, current_server, monkeypatch)

    first = _Visitor(browser, current_server)
    try:
        # The copied link, on the page server as the hosted stacks serve it.
        first.opens(hosted, project_id)
        first.waits_for(
            "the owner's table", lambda: _table_reads(first.page, ids["table"], "Dec 21", timeout_ms=90000),
        )
        first.waits_for("the owner's map", lambda: _wait_for_map_drawn(first.page, ids["map"], "the link opened"))
        assert _runs_started(first.asked) == [] and _files_read(first.asked) == set(), (
            "the dashboard ran or read outputs to show the owner's results, which the page carries" + first.story()
        )
        # The tiles alone: no notice over them about what a visitor may do.
        expect(first.page.get_by_test_id("shared-view-banner")).to_have_count(0)
        assert not re.search(r"shared dashboard|not saved", first.page.locator("body").inner_text(), re.I), (
            "the dashboard tells a visitor what its changes do" + first.story()
        )
        assert first.page.get_by_test_id("edit-layout-btn").count() == 0, "a visitor may lay out the owner's dashboard"
        tower = node_locator(first.page, ids["tower"])
        expect(tower.locator('li[data-edit-op="add"]')).to_have_count(2, timeout=30000)
        expect(tower.get_by_role("button", name=re.compile(r"^Delete edit"))).to_have_count(0)
        expect(tower.get_by_test_id("interaction-commit")).to_have_count(0)
        park_pointer(first.page)
        save_workflow_test_screenshot(first.page, STEM, test_name="shared", sweep_toasts=True)

        saved_map = _map_pixels(first.page, ids["map"])
        keep_drawing(first.page, _map_canvas(ids["map"]))
        _pick_date(first.page, ids["date"], "2027-06-21")
        june: list[str] = []
        first.waits_for("the table for Jun 21", lambda: june.append(_table_reads(first.page, ids["table"], "Jun 21")))
        first.waits_for("the map for Jun 21", lambda: _wait_for_redraw(first.page, ids["map"], "the date changed"))
        moved = _changed(saved_map, _map_pixels(first.page, ids["map"]))
        assert moved > 0.005, f"the map for Jun 21 differs from Dec 21's in {moved:.2%} of its pixels" + first.story()
        park_pointer(first.page)
        save_workflow_test_screenshot(first.page, STEM, test_name="jun-21", sweep_toasts=True)
        save_workflow_test_screenshot(
            first.page,
            STEM,
            test_name="jun-21-map",
            pixel_threshold=CLOSEUP_PIXEL_THRESHOLD,
            max_diff_ratio=CLOSEUP_MAX_DIFF_RATIO,
            clip_selector=f'.react-flow__node[data-id="{ids["map"]}"]',
            sweep_toasts=True,
            closeup=True,
        )

        first.waits_for_runs(2, timeout_ms=RUN_TIMEOUT_MS)
        assert len(_runs_started(first.asked)) == 2, (
            "a date started other than a run and the start going on from the GPU step it left to the page"
            + first.story()
        )
        assert len(_steps_sent(first.asked)) == 1, "the page did not send what it made of the GPU step" + first.story()
        before_gpu, after_gpu = _step_outputs(first)
        assert {ids["grid"], ids["prepare"]} <= set(before_gpu), f"the run before the GPU step ran {before_gpu!r}"
        assert {ids["shadow"], ids["shaded"], ids["average"]} <= set(after_gpu), (
            f"the run after the GPU step ran {after_gpu!r}"
        )
        reran = (set(before_gpu) | set(after_gpu)) & {ids[name] for name in NOT_REACHED}
        assert not reran, f"a date ran {sorted(reran)!r} again, which it does not reach" + first.story()
        first_sent = _sent_results(first)
        first_read = _files_read(first.asked)
        assert _beyond_viewer_runs(first) == [], (
            "the dashboard asked the server for more than a viewer's run" + first.story()
        )
    finally:
        first.close()

    second = _Visitor(browser, current_server)
    try:
        second.opens(hosted, project_id)
        second.waits_for(
            "the owner's table", lambda: _table_reads(second.page, ids["table"], "Dec 21", timeout_ms=90000),
        )
        second.waits_for("the owner's map", lambda: _wait_for_map_drawn(second.page, ids["map"], "the link opened"))
        opened_map = _map_pixels(second.page, ids["map"])
        keep_drawing(second.page, _map_canvas(ids["map"]))
        _pick_date(second.page, ids["date"], "2027-06-21")
        second.waits_for(
            "the table for Jun 21",
            lambda: june.append(_table_reads(second.page, ids["table"], "Jun 21")),
        )
        assert june[1] == june[0], f"two visitors' Jun 21 read {june!r}" + second.story()
        second.waits_for("the map for Jun 21", lambda: _wait_for_redraw(second.page, ids["map"], "the date changed"))
        second.waits_for_runs(2, timeout_ms=RUN_TIMEOUT_MS)
        assert len(_steps_sent(second.asked)) == 1, "the second page did not run the GPU step itself" + second.story()
        before_gpu_2, after_gpu_2 = _step_outputs(second)
        for name in ("grid", "prepare"):
            assert before_gpu_2.get(ids[name]) == before_gpu[ids[name]], (
                f"{LABELS[name]} ran again for the second visitor's Jun 21 instead of handing on what the "
                f"first visitor's run kept: {before_gpu_2.get(ids[name])!r}, not {before_gpu[ids[name]]!r}"
                + second.story()
            )
        for name in ("shadow", "shaded", "average"):
            assert after_gpu_2.get(ids[name]) not in (None, after_gpu[ids[name]]), (
                f"{LABELS[name]} handed the second visitor what the first visitor's page made" + second.story()
            )
        second_read = _files_read(second.asked)
        assert not second_read & first_sent, (
            f"the second page read {sorted(second_read & first_sent)!r}, what the first page sent" + second.story()
        )
        assert second_read & first_read, (
            "the second page read none of the outputs kept from the first visitor's run" + second.story()
        )

        # The saved date brings the owner's results back, with no run.
        keep_drawing(second.page, _map_canvas(ids["map"]))
        _pick_date(second.page, ids["date"], "2027-12-21")
        second.waits_for(
            "the table for Dec 21 again", lambda: _table_reads(second.page, ids["table"], "Dec 21", timeout_ms=90000),
        )
        second.waits_for("the saved map again", lambda: _wait_for_redraw(second.page, ids["map"], "the date went back"))
        assert _table_reads(second.page, ids["table"], "Dec 21") == "40 min"
        back = _changed(opened_map, _map_pixels(second.page, ids["map"]))
        assert back <= 0.01, f"the saved date's map differs from the one the page opened with in {back:.2%}"
        # The page asks, and the server answers that the saved values need no
        # run: the page follows no run and runs no GPU step.
        second.waits_for_runs(3, timeout_ms=RUN_TIMEOUT_MS)
        assert _start_answers(second)[2:] == [(200, None)], (
            f"the saved date was answered {_start_answers(second)[2:]!r}, not with no run" + second.story()
        )
        assert len(second.streams) == 2, "the saved date ran again" + second.story()
        assert len(_steps_sent(second.asked)) == 1, "the saved date ran the GPU step again" + second.story()
        assert _beyond_viewer_runs(second) == [], (
            "the dashboard asked the server for more than a viewer's run" + second.story()
        )
    finally:
        second.close()

    # Another account opens the dataflow's link: the owner's results, read-only.
    other_ctx = browser.new_context()
    try:
        other = other_ctx.new_page()
        stub_db_login(
            other,
            frontend_url=app_frontend.base_url,
            backend_url=current_server,
            username=f"crown_other_{uuid.uuid4().hex[:8]}",
            name="Someone Else",
        )
        other.goto(dataflow_link)
        other.get_by_test_id("shared-view-banner").wait_for(timeout=45000)
        assert _table_reads(other, ids["table"], "Dec 21", timeout_ms=90000) == "40 min"
        _wait_for_map_drawn(other, ids["map"], "another account opened the dataflow's link")
    finally:
        other_ctx.close()

    after = _project(current_server, session["token"], project_id)
    assert after["spec"] == before["spec"], "a visitor's run changed the owner's dataflow"
    assert after["outputs"] == before["outputs"], "a visitor's run changed the dataflow's recorded outputs"
    assert _catalog_ids(current_server, session["token"], project_id) == catalog_before, (
        "a visitor's run added to the Data Catalog"
    )


@pytest.mark.xdist_group("crown-heights-link")
def test_the_crown_heights_dashboard_link_dev_shares_works_on_this_deployment_too(
    app_frontend: "FrontendPage", current_server, browser, monkeypatch,
):
    require_project_page()
    require_user_auth()
    ids = _ids()

    # The shared guest's copy, seeded as dev seeds it: by the first listing
    # since the start (here, since the last test emptied the database).
    guest = api_json(f"{current_server}/api/auth/signin/guest", "", method="POST", payload={})["token"]
    api_json(f"{current_server}/api/projects", guest)
    copy = api_json(f"{current_server}/api/projects/{LINK_ID}", guest)
    assert copy["spec"]["dataflow"]["name"] == NAME, copy["spec"]["dataflow"].get("name")
    assert not copy["outputs"], "the shipped copy has saved outputs, which no one ran"
    hosted = _serve_hosted(app_frontend, current_server, monkeypatch)

    visitor = _Visitor(browser, current_server)
    try:
        # No one ran it, so its tiles fill through a run: the server, the
        # page's GPU step, then the server again. Held at its first step, the
        # run leaves the table and the map saying they are computing, not
        # that a node is left to run.
        hold_server_runs(current_server, True)
        try:
            visitor.opens(hosted, LINK_ID)
            require_webgpu(visitor.page)
            _until_held(current_server, visitor)
            for name in ("table", "map"):
                visitor.waits_for(
                    f"{LABELS[name]} computing",
                    lambda name=name: _tile_says(
                        visitor.page, ids[name], "upstream-running", *COMPUTING, timeout_ms=60000,
                    ),
                )
        finally:
            # A hold left standing would stop every later run on this backend.
            hold_server_runs(current_server, False)
        # Until its rows are in, the table says it is computing: not that its
        # input is not a table, nor an empty one, while it reads the rows.
        said: list[set[str]] = []
        visitor.waits_for(
            "the table's rows", lambda: said.append(_reasons_until_read(visitor.page, ids["table"], "Dec 21")),
        )
        assert said[0] <= {"upstream-running"}, (
            f"before its rows the table said {sorted(said[0])!r}, not only that it was computing" + visitor.story()
        )
        shade: list[str] = []
        visitor.waits_for(
            "the table the run made", lambda: shade.append(_table_reads(visitor.page, ids["table"], "Dec 21")),
        )
        assert shade == ["40 min"], f"the run on open gave Dec 21 {shade!r}, not komar41's 40 min" + visitor.story()
        visitor.waits_for(
            "the map the run made", lambda: _wait_for_map_drawn(visitor.page, ids["map"], "the link opened"),
        )
        visitor.waits_for_runs(2, timeout_ms=RUN_TIMEOUT_MS)
        assert len(_runs_started(visitor.asked)) == 2, (
            "opening the link started other than one run and its sequel" + visitor.story()
        )
        assert len(_steps_sent(visitor.asked)) == 1, "the page did not run the GPU step" + visitor.story()
        opened = _step_outputs(visitor)
        assert {ids[name] for name in NOT_REACHED + ("grid", "prepare")} <= set(opened[0]), (
            f"the run on open ran {opened[0]!r}"
        )

        opened_map = _map_pixels(visitor.page, ids["map"])
        keep_drawing(visitor.page, _map_canvas(ids["map"]))
        _pick_date(visitor.page, ids["date"], "2027-06-21")
        visitor.waits_for("the table for Jun 21", lambda: _table_reads(visitor.page, ids["table"], "Jun 21"))
        visitor.waits_for("the map for Jun 21", lambda: _wait_for_redraw(visitor.page, ids["map"], "the date changed"))
        moved = _changed(opened_map, _map_pixels(visitor.page, ids["map"]))
        assert moved > 0.005, f"the map for Jun 21 differs from Dec 21's in {moved:.2%} of its pixels" + visitor.story()
        visitor.waits_for_runs(4, timeout_ms=RUN_TIMEOUT_MS)
        assert len(_runs_started(visitor.asked)) == 4, (
            "a date started other than one run and its sequel" + visitor.story()
        )
        assert len(_steps_sent(visitor.asked)) == 2, "the page did not run the GPU step for the date" + visitor.story()
        # Only the ground grid reads the date: everything else before the GPU
        # step is what the run on open kept, handed on again or not asked for.
        changed = _ran_since(visitor, 2)[0]
        assert changed.get(ids["grid"]) not in (None, opened[0][ids["grid"]]), (
            "the ground grid was not made again for Jun 21" + visitor.story()
        )
        for name in NOT_REACHED + ("prepare",):
            assert changed.get(ids[name]) in (None, opened[0][ids[name]]), (
                f"{LABELS[name]} ran again for Jun 21, which it does not read" + visitor.story()
            )
        assert _beyond_viewer_runs(visitor) == [], (
            "the dashboard asked the server for more than a viewer's run" + visitor.story()
        )
    finally:
        visitor.close()

    # A browser with no WebGPU: the run on open stops at the GPU step, and the
    # table and the map say which step could not run, with nothing to press.
    blind = _Visitor(browser, current_server)
    try:
        blind.ctx.add_init_script(_NO_WEBGPU_JS)
        blind.opens(hosted, LINK_ID)
        stopped = f'"{LABELS["rays"]}" could not run in this browser.'
        for name in ("table", "map"):
            blind.waits_for(
                f"{LABELS[name]} saying why it has nothing",
                lambda name=name: _tile_says(
                    blind.page, ids[name], "upstream-stopped", stopped, timeout_ms=RUN_TIMEOUT_MS,
                ),
            )
        blind.waits_for_runs(1, timeout_ms=RUN_TIMEOUT_MS)
        assert len(_runs_started(blind.asked)) == 1, (
            "the run started again past a step the page could not run" + blind.story()
        )
        assert _steps_sent(blind.asked) == [], "the page sent a GPU step it could not run" + blind.story()
        assert _beyond_viewer_runs(blind) == [], (
            "the dashboard asked the server for more than a viewer's run" + blind.story()
        )
    finally:
        blind.close()

    after = api_json(f"{current_server}/api/projects/{LINK_ID}", guest)
    assert after["spec"] == copy["spec"], "a visitor's run changed the shipped copy"
    assert not after["outputs"], "a visitor's run saved outputs to the shipped copy"
