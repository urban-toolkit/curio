"""Playwright E2E for #354: Ctrl/Cmd+Enter against REAL Monaco.

#223 reported that the chord inserted a blank line instead of running the node,
because Monaco's own ``InsertLineAfterAction`` owns Ctrl+Enter. The fix
(``runNodeMonacoAction``) registers a standalone-editor action, whose weight
outranks the built-in one.

That claim - "our action wins" - is the whole fix, and the Jest suite cannot
test it: there is no jest.config monaco mapping and no global mock, every
existing suite hand-rolls a fake ``{addAction}``, and real Monaco needs workers,
ResizeObserver and canvas that jsdom does not provide. A fake always lets our
action win, because a fake has no InsertLineAfterAction to lose to. So a Monaco
version bump could silently restore #223 with every test green.

Here the browser runs the real editor, so both halves of the claim are checked
at once: the node runs, AND no line is inserted.

The canvas-level half of the shortcut (no editor focused) is covered in Jest by
``src/tests/hook/useRunSelectedNodeShortcut.test.tsx``; it needs no browser
because it is a plain window listener.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_run_node_shortcut_e2e.py -v
"""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from .utils import (
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    set_node_code,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

NODE_ID = "run-shortcut-node"
NODE_TYPE = "curio.builtin/computation-analysis"

# One line, no trailing newline: "a line was inserted" is then simply "the
# model has more than one line".
NODE_CODE = "return [21 * 2]"

# Monaco's ``KeyMod.CtrlCmd`` is Cmd on macOS and Ctrl everywhere else, so the
# chord to PRESS differs by platform even though the binding is one constant.
# (``isRunNodeChord``, which drives the canvas-level listener, accepts either on
# every platform - that is a different rule for a different handler.)
RUN_CHORD = "Meta+Enter" if sys.platform == "darwin" else "Control+Enter"


def _spec() -> dict:
    return {
        "dataflow": {
            "name": "Run Node Shortcut",
            "task": "",
            "nodes": [{
                "id": NODE_ID,
                "type": NODE_TYPE,
                "x": 300,
                "y": 150,
                "content": NODE_CODE,
                "in": "DEFAULT",
                "out": "DEFAULT",
                "goal": "",
                "metadata": {"keywords": []},
            }],
            "edges": [],
        }
    }


def _editor_state(page) -> dict:
    """Line count and text, read off the REAL Monaco model."""
    return page.evaluate(
        """() => {
            const m = window.monaco?.editor?.getModels?.() ?? [];
            const model = m[m.length - 1];
            if (!model) return null;
            return { lines: model.getLineCount(), text: model.getValue() };
        }"""
    )


def test_ctrl_enter_runs_the_node_and_inserts_no_line(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Shortcut User",
        username="run_shortcut",
        project_name="Run Node Shortcut",
        project_spec=_spec(),
    )
    require_owner_view(page)

    node = node_locator(page, NODE_ID)
    node.scroll_into_view_if_needed()
    # Through the same path a user's typing takes, so the model and data.code
    # agree before we measure either.
    set_node_code(page, NODE_ID, NODE_CODE)

    editor = node.locator(".monaco-editor").first
    editor.wait_for(state="visible", timeout=30000)

    before = _editor_state(page)
    assert before is not None, "real Monaco did not load - window.monaco is absent"
    assert before["lines"] == 1, f"fixture should start on one line, got {before!r}"

    # Put the caret INSIDE the editor: this is the case #223 is about, and the
    # case the canvas-level listener deliberately stands down for.
    # Click the rendered text, not `textarea.inputarea`: Monaco's real input is
    # a 1px offscreen textarea that Playwright will not click as "visible".
    editor.locator(".view-lines").first.click()
    # And confirm the caret really is inside, or the rest of this test would be
    # measuring the canvas-level listener instead of the Monaco action.
    focused = page.evaluate(
        "() => document.activeElement?.closest?.('.monaco-editor') != null"
    )
    assert focused, "clicking the editor did not move focus into Monaco"

    page.keyboard.press(RUN_CHORD)

    # Check the EDITOR first, before waiting on the run. An insert lands
    # immediately, so this way a regression reports #223's actual symptom
    # ("a line was inserted") instead of a 60s run timeout that says nothing
    # about why.
    page.wait_for_timeout(500)
    after = _editor_state(page)
    assert after["lines"] == 1, (
        f"{RUN_CHORD} inserted a line - Monaco's InsertLineAfterAction won the "
        f"chord, which is #223 exactly (model now: {after['text']!r})"
    )
    assert after["text"] == before["text"], (
        f"the editor content changed: {before['text']!r} -> {after['text']!r}"
    )

    # And the chord reached the run. (Settled rather than "succeeded": this is
    # about the keystroke arriving, not what the sandbox made of the code.)
    wait_for_node_settled(page, NODE_ID, node_type=NODE_TYPE, timeout_ms=60000)
