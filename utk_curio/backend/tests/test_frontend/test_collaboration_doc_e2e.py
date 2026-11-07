"""Playwright E2E: a dataflow edited together, through its Yjs doc.

The owner and an editor she invited each open the dataflow in a browser of
their own. Each keystroke in a node's code reaches the other's editor as it is
typed, with the typist's cursor in their color, and Ctrl+Z undoes only one's
own typing. A widget's value, a scenario and a drag reach the other tab too,
the drag live while it goes. A tab that opens later finds the last edit, and a
watcher's typing never reaches anyone. The merge rules say what happened:
removing a node someone is editing asks first, the one editing it is told and
can put it back, and a connection drawn to a node removed meanwhile is dropped
with a message to whoever drew it. Every stack serves this: there is no switch
for it.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from .utils import (
    _wait_for_reactflow_ready,
    api_json,
    connect_nodes,
    frame_nodes,
    node_locator,
    read_node_code,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    set_node_code,
    stub_db_login,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

FRAMES = "collaboration-doc"
#: A warning toast saying *words*: the merge rules' messages.
_TOAST = '[aria-label="Notifications"] [role="status"]:has-text("{}")'
CODE_NODE = "doc-code"
SPEC_NODE = "doc-other"
TYPE = "curio.builtin/python-computation"
OWNER, EDITOR, WATCHER = "doc_owner_e2e", "doc_editor_e2e", "doc_watcher_e2e"
SCENARIO = "doc-scenario"


def _spec() -> dict:
    return {
        "name": "Typed together",
        "dataflow": {
            "name": "Typed together",
            "nodes": [
                {
                    "id": CODE_NODE, "type": TYPE, "x": 0, "y": 0, "content": "x = 1\n",
                    "metadata": {"widgets": [{"name": "rows", "type": "number", "default": 5, "label": "Rows"}]},
                },
                {"id": SPEC_NODE, "type": TYPE, "x": 700, "y": 0, "content": "y = 2\n"},
            ],
            "edges": [],
            "scenarios": [{"id": SCENARIO, "name": "Cool roofs", "color": "#4477aa", "nodes": [SPEC_NODE]}],
        },
    }


_BOUND_JS = """() => {
    const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
    return document.querySelectorAll('.react-flow__node').length >= 2 && editors.length >= 1;
}"""


class _Room:
    """The owner's dataflow, and a browser for each person who opens it."""

    def __init__(self, base: str, backend: str, browser):
        self.base, self.backend, self.browser = base, backend, browser
        self.contexts = []
        self.tokens: dict[str, str] = {}
        self.project_id = None

    def person(self, username: str, name: str, *, owns: bool = False, before_open=None):
        context = self.browser.new_context(viewport={"width": 1280, "height": 768})
        self.contexts.append(context)
        page = context.new_page()
        if before_open is not None:
            before_open(page)
        login = stub_db_login(
            page, frontend_url=self.base, backend_url=self.backend, username=username, name=name,
            **({"project_name": "Typed together", "project_spec": _spec()} if owns else {}),
        )
        self.tokens[username] = login["token"]
        if owns:
            self.project_id = login["project"]["id"]
        return page

    def invite(self, username: str) -> None:
        api_json(f"{self.backend}/api/projects/{self.project_id}/editors", self.tokens[OWNER],
                 method="POST", payload={"username": username})

    def open(self, page) -> None:
        """Open the dataflow and wait until its code editor is bound to the doc."""
        page.goto(f"{self.base}/dataflow/{self.project_id}", timeout=120000)
        node_locator(page, CODE_NODE).wait_for(timeout=30000)
        node_locator(page, CODE_NODE).locator(".monaco-editor").first.wait_for(timeout=30000)
        page.wait_for_function(_BOUND_JS, timeout=30000)
        # The doc's first sync, and the editor's binding to it, take a moment:
        # the page then colors everyone else's cursor.
        try:
            page.wait_for_function(
                """() => !!document.querySelector('style#curio-remote-cursors')""", timeout=30000,
            )
        except Exception as exc:  # noqa: BLE001 - said in the test's words
            raise AssertionError("the canvas never bound to the dataflow's doc") from exc

    def saved(self) -> dict:
        return api_json(f"{self.backend}/api/projects/{self.project_id}", self.tokens[OWNER])["spec"]["dataflow"]

    def close(self) -> None:
        for context in self.contexts:
            context.close()


@pytest.fixture()
def room(app_frontend: "FrontendPage", current_server: str, browser):
    require_project_page()
    require_user_auth()
    opened = _Room(app_frontend.base_url, current_server, browser)
    try:
        yield opened
    finally:
        opened.close()


def _wait_for_code(page, node_id: str, check, *, what: str, timeout: float = 15000) -> str:
    deadline = time.time() + timeout / 1000
    code = read_node_code(page, node_id)
    while not check(code) and time.time() < deadline:
        page.wait_for_timeout(100)
        code = read_node_code(page, node_id)
    assert check(code), f"{what}: the editor holds {code!r}"
    return code


def _type_in(page, node_id: str, text: str, *, at_start: bool = False) -> None:
    """Type *text* into *node_id*'s code, at its end or its start, key by key."""
    lines = node_locator(page, node_id).locator(".monaco-editor .view-lines").first
    lines.click()
    page.keyboard.press("Control+Home" if at_start else "Control+End")
    page.keyboard.type(text, delay=20)


_POSITION_JS = """(id) => {
    const node = window.__curio_reactFlow && window.__curio_reactFlow.getNodes().find((n) => n.id === id);
    return node ? [node.position.x, node.position.y] : null;
}"""

_WIDGET_JS = """([id, name]) => {
    const node = window.__curio_reactFlow && window.__curio_reactFlow.getNodes().find((n) => n.id === id);
    const widget = node && (node.data.widgets || []).find((w) => w && w.name === name);
    return widget ? (widget.value ?? null) : null;
}"""


def _position(page, node_id: str):
    return page.evaluate(_POSITION_JS, node_id)


#: Whether *id*'s node stands more than *far* canvas units from *start*.
_MOVED_JS = """([id, start, far]) => {
    const node = window.__curio_reactFlow.getNodes().find((n) => n.id === id);
    return !!node && Math.hypot(node.position.x - start[0], node.position.y - start[1]) > far;
}"""

# Before the app's own scripts, so d3's timers, which take requestAnimationFrame
# when the app loads and move React Flow's viewport through it, go through this.
# Switched on, it keeps every callback, as a page that draws no frame does. The
# page's next pointer move lets them go and runs them at once: on a busy runner
# the frame that brings a page short of frames its next move runs them right
# after the move, so the view lands between the move and the press after it.
_HOLD_FRAMES_UNTIL_A_MOVE_JS = """(() => {
    const request = window.requestAnimationFrame.bind(window);
    const cancel = window.cancelAnimationFrame.bind(window);
    let held = null;
    let nextId = -1;
    window.requestAnimationFrame = (callback) => {
        if (!held) return request(callback);
        const id = nextId--;
        held.set(id, callback);
        return id;
    };
    window.cancelAnimationFrame = (id) => {
        if (held && held.delete(id)) return;
        cancel(id);
    };
    window.__curioTestHoldFrames = () => { held = held || new Map(); };
    window.addEventListener("mousemove", () => {
        if (!held) return;
        const deferred = [...held.values()];
        held = null;
        const now = performance.now();
        for (const callback of deferred) {
            try { callback(now); } catch (error) { console.error(error); }
        }
    }, true);
})();"""

# A frame asked for now: whether it ran tells whether frames are held.
_ASK_FOR_A_FRAME_JS = """() => {
    window.__curioTestFrameRan = false;
    window.requestAnimationFrame(() => { window.__curioTestFrameRan = true; });
}"""

# What a press at a client point reaches: whether it is in *id*'s header, and
# whether the node drags from there, as React Flow judges it (no `nodrag`
# between the point and the node); the element there; and the view.
_PRESS_POINT_JS = """([x, y, id]) => {
    const hit = document.elementFromPoint(x, y);
    const node = hit && hit.closest(`.react-flow__node[data-id="${id}"]`);
    const header = hit && hit.closest(".curio-node-header");
    let drags = !!node;
    let blocker = null;
    for (let at = hit; node && at && at !== node; at = at.parentElement) {
        if (at.classList.contains("nodrag")) {
            drags = false;
            blocker = blocker || at;
        }
    }
    const name = (el) => !el ? "nothing" : el.tagName.toLowerCase() + (typeof el.className === "string"
        ? el.className.split(" ").filter(Boolean).map((c) => "." + c).join("") : "");
    const inNode = hit && hit.closest(".react-flow__node");
    return {
        header: !!node && !!header && node.contains(header),
        drags,
        hit: name(hit) + (inNode ? ` in node ${inNode.getAttribute("data-id")}` : ""),
        blocker: blocker ? name(blocker) : null,
        viewport: window.__curio_reactFlow.getViewport(),
    };
}"""

_SELECT_ONLY_JS = """(id) => window.__curio_reactFlow.setNodes(
    (nodes) => nodes.map((node) => ({ ...node, selected: node.id === id })))"""


def _delete_with_the_key(page, node_id: str) -> None:
    """Select *node_id* alone and press Delete, as a person removes a node."""
    page.evaluate("() => document.activeElement && document.activeElement.blur && document.activeElement.blur()")
    page.evaluate(_SELECT_ONLY_JS, node_id)
    page.wait_for_function(
        """(id) => !!window.__curio_reactFlow.getNodes().find((n) => n.id === id && n.selected)""",
        arg=node_id, timeout=10000,
    )
    page.keyboard.press("Delete")


def _open_tab(page, node_id: str, key: str) -> None:
    tab = node_locator(page, node_id).locator(f'.nav-link[data-rr-ui-event-key="{key}"]').first
    tab.wait_for(state="visible", timeout=15000)
    if "active" not in (tab.get_attribute("class") or ""):
        tab.dispatch_event("click")


def test_typing_in_a_node_shows_in_the_other_tab_with_the_typists_cursor_and_undo_is_ones_own(room):
    owner = room.person(OWNER, "Doc Owner", owns=True)
    editor = room.person(EDITOR, "Doc Editor")
    room.invite(EDITOR)
    room.open(owner)
    room.open(editor)

    _type_in(owner, CODE_NODE, "# typed by the owner")
    _wait_for_code(editor, CODE_NODE, lambda code: "# typed by the owner" in code,
                   what="the owner's typing never reached the editor's tab")

    # The owner's cursor, in the owner's color, with the owner's name.
    try:
        node_locator(editor, CODE_NODE).locator(".yRemoteSelectionHead").first.wait_for(
            state="attached", timeout=10000)
    except Exception as exc:  # noqa: BLE001 - said in the test's words
        raise AssertionError("the editor's tab shows no cursor of the owner's in the node's code") from exc
    cursors = editor.evaluate("() => document.querySelector('style#curio-remote-cursors').textContent")
    assert "Doc Owner" in cursors, f"the owner's cursor is not named: {cursors!r}"

    # The editor types too; Ctrl+Z in the editor's tab undoes the editor's
    # typing alone, never the owner's.
    _type_in(editor, CODE_NODE, "# typed by the editor\n", at_start=True)
    _wait_for_code(owner, CODE_NODE, lambda code: code.startswith("# typed by the editor"),
                   what="the editor's typing never reached the owner's tab")
    for _ in range(40):
        editor.keyboard.press("Control+z")
    _wait_for_code(editor, CODE_NODE, lambda code: "# typed by the editor" not in code,
                   what="Ctrl+Z did not undo the editor's own typing")
    final = _wait_for_code(owner, CODE_NODE, lambda code: "# typed by the editor" not in code,
                           what="the editor's undo never reached the owner's tab")
    assert "# typed by the owner" in final, f"Ctrl+Z in the editor's tab undid the owner's typing: {final!r}"
    assert "# typed by the owner" in read_node_code(editor, CODE_NODE)


@pytest.mark.parametrize("frames", ["drawn", "held"])
def test_a_widget_a_scenario_and_a_drag_show_in_the_other_tab(room, frames):
    """*frames* ``held``: the owner's page draws no frame from the drag's
    framing until her first pointer move, as the busy runner of run
    41966029009 did (``_HOLD_FRAMES_UNTIL_A_MOVE_JS``)."""
    hold = (lambda page: page.add_init_script(_HOLD_FRAMES_UNTIL_A_MOVE_JS)) if frames == "held" else None
    owner = room.person(OWNER, "Doc Owner", owns=True, before_open=hold)
    editor = room.person(EDITOR, "Doc Editor")
    room.invite(EDITOR)
    room.open(owner)
    room.open(editor)

    # A widget's value.
    _open_tab(owner, CODE_NODE, "widgets")
    node_locator(owner, CODE_NODE).locator("[data-widgets-panel]").first.get_by_label("Rows", exact=True).fill("9")
    try:
        editor.wait_for_function(f"() => ({_WIDGET_JS})([{CODE_NODE!r}, 'rows']) === 9", timeout=15000)
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(
            f"the owner's widget value never reached the editor: {editor.evaluate(_WIDGET_JS, [CODE_NODE, 'rows'])}"
        ) from exc

    # A scenario, collapsed into its box with its frame's Collapse.
    frame_nodes(owner, [SPEC_NODE])
    owner.get_by_test_id(f"scenario-collapse-{SCENARIO}").click()
    owner.get_by_test_id(f"scenario-box-{SCENARIO}").wait_for(state="visible", timeout=15000)
    frame_nodes(editor, [SPEC_NODE])
    try:
        editor.get_by_test_id(f"scenario-box-{SCENARIO}").wait_for(state="visible", timeout=15000)
    except Exception as exc:  # noqa: BLE001
        raise AssertionError("the owner's collapsed scenario never showed as a box in the editor's tab") from exc

    # A drag: live in the other tab while it goes, and the place at the drop.
    if frames == "held":
        owner.evaluate("() => window.__curioTestHoldFrames()")
        owner.evaluate(_ASK_FOR_A_FRAME_JS)
        owner.wait_for_timeout(500)
        assert not owner.evaluate("() => window.__curioTestFrameRan"), (
            "an animation frame ran while the owner's frames were held back, so this test proves nothing"
        )
    # Each tab frames the node at zoom 1 through the app's fit, which sets the
    # view at once and is read back until the page draws it: React Flow's
    # setViewport moves through a d3 transition, which lands only on an
    # animation frame, so a box read before one came was the old view's, and
    # the press then missed the header (run 41966029009).
    for page in (owner, editor):
        _wait_for_reactflow_ready(page, node_ids=[CODE_NODE], max_zoom=1.0)
    start = _position(editor, CODE_NODE)
    owner_start = _position(owner, CODE_NODE)
    box = node_locator(owner, CODE_NODE).bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + 15
    owner.mouse.move(x, y)
    if frames == "held":
        try:
            owner.wait_for_function("() => window.__curioTestFrameRan === true", polling=100, timeout=10000)
        except Exception as exc:  # noqa: BLE001
            raise AssertionError("the owner's pointer move did not let her frames go") from exc
    # The press lands where the box was read: on her node's header, a place
    # the node drags from.
    pressed = owner.evaluate(_PRESS_POINT_JS, [x, y, CODE_NODE])
    assert pressed["header"] and pressed["drags"], (
        f"the owner's press at {x:.0f}, {y:.0f} is on {pressed['hit']}, not on a part of her node's header "
        f"it drags from (in its header: {pressed['header']}; the node drags from there: {pressed['drags']}"
        f"{', under ' + pressed['blocker'] if pressed['blocker'] else ''}): the canvas shows "
        f"{pressed['viewport']}, and the node's box was read as {box}"
    )
    owner.mouse.down()
    for i in range(1, 21):
        owner.mouse.move(x + 8 * i, y + 4 * i)
        owner.wait_for_timeout(20)
    try:
        owner.wait_for_function(_MOVED_JS, arg=[CODE_NODE, owner_start, 60], timeout=10000)
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(
            f"the owner's drag did not move her own node: {_position(owner, CODE_NODE)}, from {owner_start}"
        ) from exc
    try:
        editor.wait_for_function(_MOVED_JS, arg=[CODE_NODE, start, 60], timeout=10000)
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"the owner's drag did not show in the editor's tab while it went: {_position(editor, CODE_NODE)}") from exc
    owner.mouse.up()
    owner.wait_for_timeout(300)
    dropped = _position(owner, CODE_NODE)
    try:
        editor.wait_for_function(
            """([id, want]) => {
                const node = window.__curio_reactFlow.getNodes().find((n) => n.id === id);
                return !!node && Math.abs(node.position.x - want[0]) < 0.5 && Math.abs(node.position.y - want[1]) < 0.5;
            }""",
            arg=[CODE_NODE, dropped], timeout=15000,
        )
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"the drop's place {dropped} never reached the editor: {_position(editor, CODE_NODE)}") from exc

    # The server keeps all three, with no save.
    deadline = time.time() + 15
    while time.time() < deadline:
        saved = room.saved()
        node = next(n for n in saved["nodes"] if n["id"] == CODE_NODE)
        scenario = (saved.get("scenarios") or [{}])[0]
        widget = next((w for w in (node.get("metadata") or {}).get("widgets", []) if w["name"] == "rows"), {})
        if widget.get("value") == 9 and scenario.get("collapsed") is True and (node["x"], node["y"]) == pytest.approx(tuple(dropped), abs=0.5):
            break
        time.sleep(0.5)
    assert widget.get("value") == 9, f"the server did not keep the widget's value: {widget}"
    assert scenario.get("collapsed") is True, f"the server did not keep the collapsed scenario: {scenario}"
    assert (node["x"], node["y"]) == pytest.approx(tuple(dropped), abs=0.5), (
        f"the server did not keep the drop's place: {node['x']}, {node['y']} not {dropped}"
    )


def test_a_late_joiner_sees_the_last_edit_and_a_watchers_typing_never_arrives(room):
    owner = room.person(OWNER, "Doc Owner", owns=True)
    room.open(owner)
    set_node_code(owner, CODE_NODE, "x = 1\n# the last edit\n")

    # Opened right after, before the server wrote the dataflow to its file.
    watcher = room.person(WATCHER, "Doc Watcher")
    room.open(watcher)
    _wait_for_code(watcher, CODE_NODE, lambda code: code == "x = 1\n# the last edit\n",
                   what="a tab that opened later did not find the last edit")

    set_node_code(watcher, CODE_NODE, "x = 1\n# the last edit\n# a watcher's typing\n")
    owner.wait_for_timeout(2500)
    assert "a watcher's typing" not in read_node_code(owner, CODE_NODE), "a watcher's typing reached the owner"
    assert "a watcher's typing" not in next(n for n in room.saved()["nodes"] if n["id"] == CODE_NODE)["content"], (
        "the server kept a watcher's typing"
    )


def test_removing_a_node_someone_is_editing_asks_first_and_they_can_put_it_back(room):
    owner = room.person(OWNER, "Doc Owner", owns=True)
    editor = room.person(EDITOR, "Doc Editor")
    room.invite(EDITOR)
    room.open(owner)
    room.open(editor)

    # The editor is in the node's code.
    _type_in(editor, CODE_NODE, "# the editor's line")
    _wait_for_code(owner, CODE_NODE, lambda code: "# the editor's line" in code, what="the editor's typing")

    # The owner removes it with the Delete key: asked first.
    _delete_with_the_key(owner, CODE_NODE)
    dialog = owner.get_by_role("dialog")
    dialog.wait_for(timeout=10000)
    assert "Doc Editor is editing this node. Remove it anyway?" in dialog.inner_text()
    save_workflow_test_screenshot(owner, FRAMES, test_name="removal-question",
                                  clip_selector='[role="dialog"]', fit_reactflow=False)
    dialog.get_by_role("button", name="Remove").click()
    node_locator(owner, CODE_NODE).wait_for(state="detached", timeout=10000)

    # The editor is told who removed it, and puts it back.
    toast = editor.get_by_text("Doc Owner removed this node while you were editing it.")
    toast.wait_for(timeout=15000)
    save_workflow_test_screenshot(editor, FRAMES, test_name="removed-while-editing",
                                  clip_selector=_TOAST.format("removed this node"), fit_reactflow=False)
    editor.get_by_role("button", name="Put it back").click()
    node_locator(editor, CODE_NODE).wait_for(timeout=15000)
    node_locator(owner, CODE_NODE).wait_for(timeout=15000)
    _wait_for_code(owner, CODE_NODE, lambda code: "# the editor's line" in code,
                   what="the node put back did not hold the editor's code")


def test_a_connection_drawn_to_a_node_removed_meanwhile_is_dropped_and_its_drawer_told(room):
    """The editor's changes are held on their way while the owner removes the
    node the editor connects to; then they go, and the server drops the
    connection that points nowhere."""
    held: list = []
    holding = {"on": False}

    def hold_outgoing(page):
        def route(ws):
            server = ws.connect_to_server()

            def to_server(message):
                if holding["on"]:
                    held.append(message)
                else:
                    server.send(message)

            ws.on_message(to_server)
            server.on_message(lambda message: ws.send(message))
            room._servers.append(server)

        room._servers = []
        page.route_web_socket("**/socket.io/**", route)

    owner = room.person(OWNER, "Doc Owner", owns=True)
    editor = room.person(EDITOR, "Doc Editor", before_open=hold_outgoing)
    room.invite(EDITOR)
    room.open(owner)
    room.open(editor)
    frame_nodes(editor, [CODE_NODE, SPEC_NODE])

    holding["on"] = True
    connect_nodes(editor, SPEC_NODE, CODE_NODE)
    # The owner removes the node the editor connects to, which nobody edits.
    _delete_with_the_key(owner, CODE_NODE)
    node_locator(owner, CODE_NODE).wait_for(state="detached", timeout=10000)
    owner.wait_for_timeout(500)
    holding["on"] = False
    server = room._servers[-1]
    for message in held:
        server.send(message)

    editor.get_by_text("Doc Owner removed that node, so this connection was not kept.").wait_for(timeout=15000)
    save_workflow_test_screenshot(editor, FRAMES, test_name="connection-not-kept",
                                  clip_selector=_TOAST.format("connection was not kept"), fit_reactflow=False)
    deadline = time.time() + 15
    while time.time() < deadline and room.saved()["edges"]:
        time.sleep(0.5)
    assert room.saved()["edges"] == [], f"the server kept a connection to a removed node: {room.saved()['edges']}"
