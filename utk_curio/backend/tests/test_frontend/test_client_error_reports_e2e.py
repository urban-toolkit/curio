"""Playwright E2E: what a page reports to the monitor as a browser error.

Every page sends the monitor each error it leaves uncaught and each promise
rejection nothing handles (``utils/clientErrorReporter.ts``). The browser's
notice that a ResizeObserver delivered some sizes a frame late is neither. The
browser raises it as a window ``error`` event with no error object when an
observer's callback changes a size it observes. A visitor's dashboard that
reports it asks the server for more than its data, which the dashboard tests
refuse: an unnamed report, sent as the Crown Heights link's dashboard opened,
failed one that way (run 40619435665, 10-28).

The page here is a visitor's dashboard, served as the hosted stacks serve it.
The loop is made on purpose, with the browser's own ResizeObserver, kept
before the page's scripts run: the page's code editors wrap the global one so
that its callbacks wait a frame, and no loop forms through it.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .test_dashboard_page_e2e import (
    CLIENT_ERROR_PATH,
    _chart_drew,
    _not_a_viewer_route,
    _pinned_and_saved,
    _serve_hosted,
    _Visitor,
)
from .utils import require_project_page, require_user_auth

if TYPE_CHECKING:
    from .utils import FrontendPage

#: Before the page's scripts: the browser's own ResizeObserver, every loop
#: notice the page gets, and a way to make one. The box grows once, in its own
#: observer's callback, so its new size waits for the next frame and the
#: browser raises its notice for the frame the box grew in.
_RESIZE_LOOP_JS = """(() => {
    const Native = window.ResizeObserver;
    window.__curioResizeLoopNotices = [];
    window.addEventListener('error', (event) => {
        if (event.error == null && /^ResizeObserver loop/.test(event.message)) {
            window.__curioResizeLoopNotices.push(event.message);
        }
    });
    window.__curioLoopAResizeObserver = () => {
        const box = document.createElement('div');
        box.style.cssText = 'position: fixed; left: 0; top: 0; width: 10px; height: 10px;'
            + ' visibility: hidden; pointer-events: none';
        document.body.appendChild(box);
        let grown = false;
        new Native(() => {
            if (grown) return;
            grown = true;
            box.style.width = '20px';
        }).observe(box);
    };
})();"""

#: The message of the error the page is made to leave uncaught.
UNCAUGHT = "curio-e2e-uncaught-error-7c41"


def _until_reported(visitor: _Visitor, words: str, *, timeout_ms: int = 30000) -> None:
    """Until the visitor's page has reported an error whose report reads *words*."""
    waited = 0
    while not any(words in report for report in visitor.reported):
        if waited >= timeout_ms:
            raise AssertionError(f"no report read {words!r} after {timeout_ms} ms")
        visitor.page.wait_for_timeout(100)
        waited += 100


def test_a_resize_observer_loop_on_a_visitors_dashboard_is_not_reported_but_an_uncaught_error_is(
    app_frontend: "FrontendPage", current_server, page, browser, monkeypatch,
):
    """The browser raises its ResizeObserver loop notice on a visitor's
    dashboard, and the page reports nothing for it: what it asks of the server
    is its data and, once it leaves an error uncaught, that error's report.

    The uncaught error comes last, so its report reaches the server after any
    report of the notice, and it shows the page reports errors at all.
    """
    require_project_page()
    require_user_auth()
    session = _pinned_and_saved(page, app_frontend, current_server, prefix="dash_resize_loop")
    project_id = session["project"]["id"]
    # Off the canvas: it can still save on its way out.
    page.goto("about:blank")
    hosted = _serve_hosted(app_frontend, current_server, monkeypatch)

    visitor = _Visitor(browser, current_server)
    try:
        visitor.ctx.add_init_script(_RESIZE_LOOP_JS)
        visitor.opens(hosted, project_id)
        visitor.waits_for("the chart from its saved rows", lambda: _chart_drew(visitor.page))
        visitor.page.evaluate("() => window.__curioLoopAResizeObserver()")
        visitor.waits_for(
            "the browser's ResizeObserver loop notice",
            lambda: visitor.page.wait_for_function(
                "() => window.__curioResizeLoopNotices.length > 0", polling=100, timeout=30000,
            ),
        )
        visitor.page.evaluate("(message) => { setTimeout(() => { throw new Error(message); }, 0); }", UNCAUGHT)
        visitor.waits_for("the uncaught error's report", lambda: _until_reported(visitor, UNCAUGHT))
        assert len(visitor.reported) == 1, (
            "the page reported more than the error it left uncaught" + visitor.story()
        )
        assert _not_a_viewer_route(visitor.asked) == [f"POST {CLIENT_ERROR_PATH}"], (
            "the dashboard asked the server for more than its data and the uncaught error's report"
            + visitor.story()
        )
    finally:
        visitor.close()
