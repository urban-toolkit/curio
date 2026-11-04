"""Taking a test's routes off a page or a context before the context closes.

Playwright's ``close()`` does not wait for a route's handler. Closing a context
first disposes of every answer its ``route.fetch()`` calls got, so a handler
still running then fails when it reads its answer (``response.text()``,
``body()``, ``json()``): "Response has been disposed". The sync API keeps a
handler's error and raises it at the worker's next Playwright call, whatever
that call is and whichever test makes it. In run 40721143993 (10-28) that was
the next visitor's ``browser.new_context()``; in run 40200172002 (10-25),
pytest-playwright's ``Tracing.stop`` at the test's teardown.

``unroute_all(behavior="wait")`` takes the routes off and waits for the calls
of them still running, so each one ends against an open context and nothing is
dropped: an error of such a call is still raised, at this worker's next call.
A handler that only answers, aborts or continues its route needs none of this,
since Playwright races those with the page's close. A handler that parks its
route unanswered holds the wait until the route is answered, so a test that
parks routes releases them before it ends its routes.
"""

from __future__ import annotations


def end_routes(target) -> None:
    """Take every route off *target*, a page or a context, once the calls of
    them still running have ended. A closed *target* has no call left to wait
    for."""
    if not target.is_closed():
        target.unroute_all(behavior="wait")


def close_after_routes(context) -> None:
    """Close *context* once no call of its pages' routes, or of its own, is
    still running."""
    for page in context.pages:
        end_routes(page)
    end_routes(context)
    context.close()
