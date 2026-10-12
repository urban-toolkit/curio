"""A wait for a node's run must not return on the result from before the run (#892).

``wait_for_node_settled`` returns once a node reads ``done`` or ``error``. A node
that already read ``done`` before the click (a map that drew when the page
opened) satisfies it at once, before the run the click started has reached the
node. The helper then reads the status a second time, so the scenario drop e2e
got ``running`` back when the run arrived between the two reads.

``watch_node_run`` records the node's status changes from before the click, and
``wait_for_node_run_to_end`` returns only after the node has gone ``running``
and then settled, with the status the same check saw.

The page is a stand-in for one canvas node: its status element, and a button
whose click starts a run that reaches the node 300 ms later and ends 600 ms
after that.
"""
from __future__ import annotations

import pytest

_NODE = "map"


def _page(outcome: str = "done", recreate: bool = False) -> str:
    return f"""<!doctype html><html><body>
<div class="react-flow__node" data-id="{_NODE}"><span data-curio-node-status="done"></span></div>
<button id="run" type="button">Run scenario</button>
<script>
  window.__ended = null;
  const node = document.querySelector('.react-flow__node');
  const setStatus = (value) => {{
    if ({str(recreate).lower()}) {{
      const fresh = document.createElement('span');
      fresh.setAttribute('data-curio-node-status', value);
      node.replaceChildren(fresh);
    }} else {{
      node.querySelector('[data-curio-node-status]').setAttribute('data-curio-node-status', value);
    }}
  }};
  document.getElementById('run').addEventListener('click', () => {{
    setTimeout(() => setStatus('running'), 300);
    setTimeout(() => {{ setStatus('{outcome}'); window.__ended = '{outcome}'; }}, 900);
  }});
</script></body></html>"""


def test_the_wait_returns_after_the_run_the_click_started_not_on_the_result_before_it(page):
    from utk_curio.backend.tests.test_frontend.utils import (
        wait_for_node_run_to_end,
        wait_for_node_settled,
        watch_node_run,
    )

    page.set_content(_page(), wait_until="load")
    watch_node_run(page, _NODE)
    page.click("#run")
    assert wait_for_node_settled(page, _NODE, timeout_ms=5000) == "done"
    assert page.evaluate("window.__ended") is None, (
        "the run ended before the plain settled wait returned, so the page did "
        "not reproduce #892 and this proves nothing"
    )

    assert wait_for_node_run_to_end(page, _NODE, timeout_ms=10000) == "done"
    assert page.evaluate("window.__ended") == "done", "the wait returned before the run ended"


def test_the_wait_returns_the_error_the_run_ends_with(page):
    from utk_curio.backend.tests.test_frontend.utils import wait_for_node_run_to_end, watch_node_run

    page.set_content(_page(outcome="error"), wait_until="load")
    watch_node_run(page, _NODE)
    page.click("#run")
    assert wait_for_node_run_to_end(page, _NODE, timeout_ms=10000) == "error"
    assert page.evaluate("window.__ended") == "error"


def test_the_wait_follows_a_status_element_the_run_renders_anew(page):
    from utk_curio.backend.tests.test_frontend.utils import wait_for_node_run_to_end, watch_node_run

    page.set_content(_page(recreate=True), wait_until="load")
    watch_node_run(page, _NODE)
    page.click("#run")
    assert wait_for_node_run_to_end(page, _NODE, timeout_ms=10000) == "done"
    assert page.evaluate("window.__ended") == "done", "the wait returned before the run ended"


def test_a_node_that_never_runs_fails_the_wait_and_says_so(page):
    from utk_curio.backend.tests.test_frontend.utils import wait_for_node_run_to_end, watch_node_run

    page.set_content(_page(), wait_until="load")
    watch_node_run(page, _NODE)
    with pytest.raises(AssertionError, match="never started a run"):
        wait_for_node_run_to_end(page, _NODE, timeout_ms=1500)
