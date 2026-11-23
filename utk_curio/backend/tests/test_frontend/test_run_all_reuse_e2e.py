"""Playwright E2E: a second Run All with nothing changed reuses what the first
kept (dataflow audit step 6, step 9).

A signed-in owner's Run All runs on the server, and each step asks what a
dashboard visitor's step asks: whether an output is kept under its key. The
first Run All of a loader and a node that prints runs both, and the printing
node shows its print. The second, with nothing changed, sends the sandbox
nothing: each node shows Done with the first run's result, and its output
panel says the result was reused, and when it was made, in place of its
logs. A Play of the printing node runs it again, and its print comes back.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_run_all_reuse_e2e.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .utils import (
    SandboxRuns,
    node_execution_timeout_ms,
    node_locator,
    play_node,
    read_node_output_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    stub_login_and_enter_workflow,
    wait_for_node_run_to_end,
    watch_node_run,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADER_ID = "reuse-loader"
SAYER_ID = "reuse-sayer"
NODE_TYPE = "curio.builtin/python-computation"
LOADER_CODE = "import pandas as pd\n\nreturn pd.DataFrame({'n': [1, 2, 3]})\n"
SAYER_CODE = "print(f'<<said {len(input_0)}>>')\nreturn input_0\n"
SAID = "<<said 3>>"
#: How a reused result's output panel begins.
REUSED = "Reused the result of"


def _node(node_id: str, x: int, content: str) -> dict:
    return {
        "id": node_id, "type": NODE_TYPE, "x": x, "y": 0, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }


def _spec() -> dict:
    return {
        "dataflow": {
            "name": "Run All reuse",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Run All reuse",
            "nodes": [_node(LOADER_ID, 0, LOADER_CODE), _node(SAYER_ID, 650, SAYER_CODE)],
            "edges": [{
                "id": f"reactflow__edge-{LOADER_ID}out-{SAYER_ID}in", "source": LOADER_ID, "target": SAYER_ID,
            }],
        }
    }


def _wait_for_output(page, node_id: str, needle: str, what: str) -> None:
    try:
        page.wait_for_function(
            """([nodeId, needle]) => {
                const box = document.querySelector(
                    `.react-flow__node[data-id="${nodeId}"] [data-curio-node-output]`);
                return !!box && (box.textContent || "").includes(needle);
            }""",
            arg=[node_id, needle],
            timeout=node_execution_timeout_ms(NODE_TYPE),
        )
    except Exception:
        raise AssertionError(
            f"{what}: the node's output never read {needle!r}; it reads "
            f"{read_node_output_text(page, node_id)!r}"
        ) from None


def test_a_second_run_all_with_nothing_changed_reuses_what_the_first_kept(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Run All reuse",
        username="run_all_reuse_e2e",
        project_name="Run All reuse",
        project_spec=_spec(),
    )
    require_owner_view(page)
    project_id = session["project"]["id"]
    for node_id in (LOADER_ID, SAYER_ID):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)

    run_all_and_wait(page, timeout_ms=180000)
    _wait_for_output(page, SAYER_ID, SAID, "After the first Run All")

    runs = SandboxRuns(page, session["token"], project_id)
    run_all_and_wait(page, timeout_ms=180000)
    _wait_for_output(page, SAYER_ID, REUSED, "After a second Run All with nothing changed")
    sent = runs.stop()

    assert sent == [], f"the second Run All sent the sandbox {sent}"
    for node_id in (LOADER_ID, SAYER_ID):
        shown = read_node_output_text(page, node_id)
        assert REUSED in shown and SAID not in shown, f"{node_id} shows {shown!r}"

    # A Play runs its node, whatever was kept: its print comes back.
    watch_node_run(page, SAYER_ID)
    play_node(page, SAYER_ID)
    status = wait_for_node_run_to_end(
        page, SAYER_ID, node_type=NODE_TYPE, timeout_ms=node_execution_timeout_ms(NODE_TYPE),
    )
    assert status == "done", f"the played node ended {status!r}"
    _wait_for_output(page, SAYER_ID, SAID, "After a Play of the printing node")
