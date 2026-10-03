"""Seed users and projects over the testing routes, without the browser, and
the JSON request helpers they use.
"""

import json
import time
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

from .auth import DEFAULT_TEST_PASSWORD


# ---------------------------------------------------------------------------
# DB stubs for Playwright — the browser does not drive the signup form.
#
# ``/api/testing/stub-login`` creates or fetches a user and returns a fresh
# session token, which we install as the ``session_token`` cookie on the
# Playwright context. ``/api/testing/stub-project`` seeds a workflow row
# owned by that user so ``/projects`` has something to render. Both endpoints
# require ``CURIO_TESTING=1``; see ``backend/app/testing/routes.py``.
# ---------------------------------------------------------------------------

SESSION_COOKIE_NAME = "session_token"


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    timeout: float = 10.0,
) -> dict:
    """Unauthenticated JSON request, returning the parsed body.

    Uses ``urllib`` (stdlib only) to match the rest of this module instead
    of introducing a ``requests`` dependency. For routes behind ``require_auth``
    use :func:`api_json`, which carries the bearer token.
    """
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method=method,
    )
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted local URL)
        body = resp.read().decode("utf-8") or "{}"
        return json.loads(body)


# 60 s, not 10: under ``--parallel`` four backends share the CPU with four
# Chromiums, and a stub-login that seeds the examples for a fresh user was
# measured taking 15-48 s to answer. The server does finish; a client that
# gives up at 10 s turns that into a class-wide setup error.
HTTP_TIMEOUT_S = 60.0


def _post_json(url: str, payload: dict, timeout: float = HTTP_TIMEOUT_S) -> dict:
    """POST *payload* as JSON to *url* and return the parsed JSON body."""
    return _request_json(url, method="POST", payload=payload, timeout=timeout)


def _get_json(url: str, timeout: float = 10.0) -> dict:
    """GET *url* and return the parsed JSON body."""
    return _request_json(url, method="GET", timeout=timeout)


def api_json(
    url: str,
    token: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    timeout: float = 10.0,
    raw: bool = False,
    extra_headers: dict | None = None,
):
    """Authenticated JSON request against the backend, stdlib only.

    The escape hatch for asserting backend state from a browser test: it makes a
    seeding or persistence problem fail in about a second with the offending
    payload, instead of as a 15-second locator timeout that says nothing about
    which side broke.

    ``extra_headers`` carries anything the target needs beyond the bearer token.
    The sandbox is the case that needs it: its code-execution routes require a
    shared secret rather than a user token (see the ``sandbox_auth_headers``
    fixture).
    """
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted local URL)
        body = resp.read()
        # ``raw`` for binary endpoints (e.g. a .curio.zip archive), where the
        # point is the bytes rather than a JSON document.
        return body if raw else json.loads(body.decode("utf-8") or "{}")


def install_session_cookie(page, frontend_url: str, token: str) -> None:
    """Install *token* as the ``session_token`` cookie on *page*'s context.

    Mirrors what ``setToken`` does in ``utils/authApi.ts`` (``js-cookie``
    defaults: path=/``, host-only, no ``Secure`` on http). Playwright derives
    the domain from ``url`` when neither ``domain`` nor ``path`` is set, so
    the SPA's ``Cookies.get("session_token")`` finds the same value.
    """
    page.context.add_cookies(
        [
            {
                "name": SESSION_COOKIE_NAME,
                "value": token,
                "url": frontend_url,
            }
        ]
    )


def _await_session(backend_url: str, token: str, *, timeout: float = HTTP_TIMEOUT_S) -> None:
    """Block until *token* authenticates, or fail saying it never did.

    Not defensive padding - it closes a real race in this harness. The autouse
    ``e2e_clean_db`` truncates ``user`` / ``user_session`` straight out of the
    sqlite file from the pytest process, before and after every test, while the
    backend serves threaded off a pooled connection. A pooled reader can hold a
    snapshot taken before the row this call just created, and the next
    ``require_auth`` request then answers 401.

    A browser test never notices: a page load stands between the stub-login and
    the first authenticated request. A test that drives the API directly fires
    the next request microseconds later, which is where the race became visible
    (an intermittent 401 on one parameter of ``test_agent_runs_e2e.py``). Wait
    for the state we just asked for instead of assuming it landed.
    """
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            api_json(f"{backend_url}/api/auth/me", token)
            return
        except HTTPError as exc:  # noqa: PERF203 - the retry IS the point
            if exc.code != 401:
                raise
            last = f"HTTP {exc.code}"
        except URLError as exc:
            last = str(exc)
        time.sleep(0.05)
    raise AssertionError(
        f"a freshly stubbed session never authenticated within {timeout}s "
        f"(last: {last or 'unknown'}) - the backend may not be up, or the DB "
        f"was truncated after the token was issued"
    )


def stub_db_user(
    backend_url: str,
    *,
    username: str,
    name: str,
    password: str = DEFAULT_TEST_PASSWORD,
    email: str | None = None,
    project_name: str | None = None,
    project_spec: dict | None = None,
) -> dict:
    """Seed a user (and optionally a project) over HTTP. No browser involved.

    The half of :func:`stub_db_login` that does not touch Playwright, split out
    for tests that live in this suite to reuse ``curio_servers`` but drive the
    backend directly - ``test_agent_runs_e2e.py``, like
    ``test_library_install_integration.py`` before it, requests no ``page``.

    Returns ``{user, token, created}``, plus ``project`` when one was stubbed.
    """
    payload = {"username": username, "name": name, "password": password}
    if email is not None:
        payload["email"] = email
    login = _post_json(f"{backend_url}/api/testing/stub-login", payload)
    _await_session(backend_url, login["token"])

    if project_name is not None:
        project_payload: dict = {"username": username, "name": project_name}
        if project_spec is not None:
            project_payload["spec"] = project_spec
        login["project"] = _post_json(
            f"{backend_url}/api/testing/stub-project", project_payload,
        )
    return login


def stub_db_login(
    page,
    frontend_url: str,
    backend_url: str,
    *,
    username: str,
    name: str,
    password: str = DEFAULT_TEST_PASSWORD,
    email: str | None = None,
    project_name: str | None = None,
    project_spec: dict | None = None,
) -> dict:
    """DB stub helper for Curio E2E tests.

    Creates (or re-uses) *username* directly via ``/api/testing/stub-login``,
    installs the returned session token as the browser cookie, and — when
    ``project_name`` is provided — seeds a workflow row owned by that user
    via ``/api/testing/stub-project`` so the ``/projects`` list page has
    content to render.

    Returns the parsed ``stub-login`` JSON (``{user, token, created}``),
    augmented with ``project`` when one was stubbed.

    The HTTP half is :func:`stub_db_user`; this adds the browser cookie. A test
    with no browser calls that one directly.
    """
    login = stub_db_user(
        backend_url,
        username=username,
        name=name,
        password=password,
        email=email,
        project_name=project_name,
        project_spec=project_spec,
    )
    install_session_cookie(page, frontend_url, login["token"])
    return login


def stub_login_and_enter_workflow(
    page,
    frontend_url: str,
    backend_url: str,
    *,
    username: str,
    name: str,
    password: str = DEFAULT_TEST_PASSWORD,
    project_name: str = "StubbedDataflow",
    project_spec: dict | None = None,
) -> dict:
    """DB-stubbed fast-path into an empty dataflow canvas.

    Creates the user + an empty project directly via
    ``/api/testing/stub-login`` and ``/api/testing/stub-project``, installs
    the session cookie on the Playwright context, and navigates straight to
    ``/dataflow/<project_id>`` — **no UI interaction**. Returns the full
    ``stub_db_login`` payload (``{user, token, created, project}``).

    This skips both the signup form and the "+ New Dataflow" click on
    ``/projects`` so the class-scoped ``loaded_workflow`` fixture spends its
    warm-up time on the actual workflow upload instead of UI plumbing.
    """
    result = stub_db_login(
        page,
        frontend_url=frontend_url,
        backend_url=backend_url,
        username=username,
        name=name,
        password=password,
        project_name=project_name,
        project_spec=project_spec,
    )
    project_id = result["project"]["id"]
    page.goto(f"{frontend_url}/dataflow/{project_id}")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_url(f"**/dataflow/{project_id}", timeout=15000)
    return result
