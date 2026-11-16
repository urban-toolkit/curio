"""Playwright E2E: two hosted guests and an invited editor on one example.

Every request a dataflow's page sends with its sign-in names the dataflow the
page shows, in a header, and its room's socket names it in its handshake's
query (``cli/backend_group.py`` reads both). With several backend processes
(``curio.py start --backend-processes N``) the router sends each to the
process that owns that dataflow, where its room, its doc and its guests' copies
are kept. A hosted guest's page names the dataflow it shows, never the id of
its own copy, which the server keeps with the dataflow it copies.

Two hosted guests open one example, which the shared guest account owns, and
each changes its node: each sees its own change, after a reload too, and never
the other's. An account holds the same example as a dataflow of its own, and
its owner invites an editor: each sees what the other writes there, and
neither guest does. Every tab names the dataflow its page shows on every
request that carries its sign-in, and on its socket. A play in a guest's tab
and one in the editor's send ``/processPythonCode``, whose path names no
dataflow, and the guest's play reports to ``/nodeRuntime``.

On a stack without sign-in (CI's test-isolated job) every tab is the shared
guest, the one local user, which owns the example: no copy is made, two tabs
of it share its edits, and each names it.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect

from .utils import (
    allow_guest_login_env,
    api_json,
    auth_enabled_env,
    node_locator,
    read_node_code,
    run_node_and_wait,
    set_node_code,
    stub_db_login,
    wait_for_changes_kept,
    wait_for_node_code,
)

NODE = "one-example-trees"
ORIGINAL = "return 12  # street trees\n"
FIRST_GUESTS = "return 13  # the first visitor's count\n"
SECOND_GUESTS = "return 14  # the second visitor's count\n"
OWNERS = "return 20  # the owner's count\n"
EDITORS = "return 21  # the editor's count\n"
OWNER, EDITOR = "one_example_owner_e2e", "one_example_editor_e2e"
NAME = "One example"


def _route() -> tuple[str, str]:
    """The header a request names its dataflow in, and the query argument a
    socket's handshake does: the ones the router reads."""
    from utk_curio.cli.backend_group import ROUTE_HEADER, ROUTE_QUERY

    return ROUTE_HEADER, ROUTE_QUERY


def _spec() -> dict:
    return {
        "name": NAME,
        "dataflow": {
            "name": NAME,
            "nodes": [{
                "id": NODE, "type": "curio.builtin/python-computation", "x": 0, "y": 0,
                "content": ORIGINAL, "title": "Street trees",
            }],
            "edges": [],
        },
    }


class _Tab:
    """One person's browser, and what it sent the backend: each request that
    carries its sign-in, with the dataflow that request names, and the address
    of each socket it opened."""

    def __init__(self, browser, contexts: list, who: str):
        self.who = who
        self.context = browser.new_context(viewport={"width": 1280, "height": 768})
        contexts.append(self.context)
        self.page = self.context.new_page()
        self.signed: list[tuple[str, str, str | None]] = []
        self.sockets: list[str] = []
        header = _route()[0].lower()
        self.context.on("request", lambda request: self._sent(request, header))
        self.page.on("websocket", lambda socket: self.sockets.append(socket.url))

    def _sent(self, request, header: str) -> None:
        headers = request.headers
        if "authorization" in headers:
            self.signed.append((request.method, request.url, headers.get(header)))

    def open(self, base: str, dataflow: str, role: str) -> None:
        """Open *dataflow*'s canvas and wait until its room names this tab
        *role*, with the canvas bound to the doc it joined."""
        self.page.goto(f"{base}/dataflow/{dataflow}", timeout=120000)
        node_locator(self.page, NODE).wait_for(timeout=30000)
        try:
            self.page.locator(f'[data-curio-room-role="{role}"]').wait_for(state="attached", timeout=30000)
            self.page.wait_for_function("() => !!window.__curio_awareness", timeout=30000)
        except Exception as exc:  # noqa: BLE001 - said in the test's words
            raise AssertionError(f"the room never named {self.who}'s tab its {role}, with its doc bound") from exc

    def token(self) -> str:
        for cookie in self.context.cookies():
            if cookie["name"] == "session_token":
                return cookie["value"]
        raise AssertionError(f"{self.who}'s browser holds no session_token cookie")

    def sent_to(self, path: str) -> bool:
        return any(urlparse(url).path.endswith(path) for _method, url, _named in self.signed)

    def names_only(self, dataflow: str) -> None:
        """Every request this tab sent with its sign-in named *dataflow*, and
        so did the handshake of every socket it opened."""
        _header, query = _route()
        assert self.signed, f"{self.who}'s tab sent no request with its sign-in"
        others = [
            f"{method} {urlparse(url).path}: {named!r}"
            for method, url, named in self.signed if named != dataflow
        ]
        assert not others, (
            f"{self.who}'s tab, on dataflow {dataflow}, sent {len(others)} of {len(self.signed)} "
            f"requests naming another dataflow or none: {others[:10]}"
        )
        sockets = [url for url in self.sockets if "/socket.io/" in url]
        assert sockets, f"{self.who}'s tab opened no socket to its room"
        asked = [parse_qs(urlparse(url).query).get(query) for url in sockets]
        assert asked == [[dataflow]] * len(sockets), f"{self.who}'s sockets named {asked}, not {dataflow}"


def _spec_code(backend: str, token: str, dataflow: str) -> str:
    """The node's code as the canvas of the one signed in as *token* opens it."""
    spec = api_json(f"{backend}/api/projects/{dataflow}", token)["spec"]
    return next(node for node in spec["dataflow"]["nodes"] if node["id"] == NODE)["content"]


def _example(backend: str, hosted: bool) -> str:
    """The example: a dataflow the shared guest account owns, as every
    shipped example is."""
    route = "signin/guest" if hosted else "signin/auto-guest"
    signed_in = api_json(f"{backend}/api/auth/{route}", "", method="POST", payload={})
    return api_json(
        f"{backend}/api/testing/stub-project", "", method="POST",
        payload={"username": signed_in["user"]["username"], "name": NAME, "spec": _spec()},
    )["id"]


def _kept_for_the_visit(tab: _Tab) -> None:
    expect(tab.page.locator("[data-curio-save-state]")).to_have_text("Kept for this visit")


def _two_tabs_of_the_local_guest(browser, contexts, base: str, example: str) -> None:
    """Without sign-in the shared guest is the one local user and owns the
    example: two tabs of it share its edits live, as the dataflow's own, and
    each names it."""
    first, second = _Tab(browser, contexts, "the first tab"), _Tab(browser, contexts, "the second tab")
    first.open(base, example, "owner")
    first.names_only(example)
    set_node_code(first.page, NODE, FIRST_GUESTS)
    wait_for_changes_kept(first.page)
    second.open(base, example, "owner")
    wait_for_node_code(second.page, NODE, FIRST_GUESTS)
    set_node_code(second.page, NODE, SECOND_GUESTS)
    wait_for_changes_kept(second.page)
    wait_for_node_code(first.page, NODE, SECOND_GUESTS)
    run_node_and_wait(first.page, NODE)
    assert first.sent_to("/processPythonCode"), "the first tab's play sent no /processPythonCode"
    first.names_only(example)
    second.names_only(example)


def test_two_hosted_guests_keep_their_own_edits_and_an_editor_shares_the_owners_each_tab_naming_its_dataflow(
    app_frontend, current_server, browser,
):
    """With sign-in, each hosted guest's edit of the example is kept in its
    own copy and the invited editor shares the owner's dataflow, while every
    tab names the dataflow its page shows. Without sign-in, two tabs of the
    local guest share the example (:func:`_two_tabs_of_the_local_guest`)."""
    hosted = auth_enabled_env()
    if hosted:
        assert allow_guest_login_env(), "this stack turns guest login off, so it has no hosted guest"
    base, backend = app_frontend.base_url, current_server
    example = _example(backend, hosted)
    contexts: list = []
    try:
        if not hosted:
            _two_tabs_of_the_local_guest(browser, contexts, base, example)
            return

        # The account's dataflow of the same example, and the editor its owner invites.
        owner, editor = _Tab(browser, contexts, "the owner"), _Tab(browser, contexts, "the editor")
        owners = stub_db_login(
            owner.page, frontend_url=base, backend_url=backend, username=OWNER, name="Owner",
            project_name=NAME, project_spec=_spec(),
        )
        dataflow = owners["project"]["id"]
        stub_db_login(editor.page, frontend_url=base, backend_url=backend, username=EDITOR, name="Editor")
        api_json(f"{backend}/api/projects/{dataflow}/editors", owners["token"], method="POST",
                 payload={"username": EDITOR})

        # The first visitor changes the example's node: its own copy holds it.
        first = _Tab(browser, contexts, "the first guest")
        first.open(base, example, "owner")
        first.names_only(example)
        set_node_code(first.page, NODE, FIRST_GUESTS)
        wait_for_changes_kept(first.page)
        _kept_for_the_visit(first)

        # The second visitor opens the example as it was, and changes it too.
        second = _Tab(browser, contexts, "the second guest")
        second.open(base, example, "owner")
        wait_for_node_code(second.page, NODE, ORIGINAL)
        set_node_code(second.page, NODE, SECOND_GUESTS)
        wait_for_changes_kept(second.page)
        _kept_for_the_visit(second)

        # Each reload opens that visitor's own copy, with its own change alone.
        for tab, code in ((first, FIRST_GUESTS), (second, SECOND_GUESTS)):
            tab.page.reload()
            node_locator(tab.page, NODE).wait_for(timeout=30000)
            wait_for_node_code(tab.page, NODE, code)
            assert _spec_code(backend, tab.token(), example) == code, f"{tab.who}'s canvas opens without its change"
        assert first.token() != second.token()

        # A play in the first visitor's tab, which names no dataflow in its path.
        run_node_and_wait(first.page, NODE)
        assert first.sent_to("/processPythonCode"), "the first guest's play sent no /processPythonCode"
        assert first.sent_to("/nodeRuntime"), "the first guest's play reported no outcome to /nodeRuntime"

        # The owner and the editor each see what the other writes, on her dataflow.
        owner.open(base, dataflow, "owner")
        editor.open(base, dataflow, "editor")
        wait_for_node_code(editor.page, NODE, ORIGINAL)
        set_node_code(owner.page, NODE, OWNERS)
        wait_for_changes_kept(owner.page)
        wait_for_node_code(editor.page, NODE, OWNERS)
        set_node_code(editor.page, NODE, EDITORS)
        wait_for_changes_kept(editor.page)
        wait_for_node_code(owner.page, NODE, EDITORS)
        run_node_and_wait(editor.page, NODE)
        assert editor.sent_to("/processPythonCode"), "the editor's play sent no /processPythonCode"
        assert _spec_code(backend, owners["token"], dataflow) == EDITORS

        # Neither visitor sees what the owner and the editor wrote, nor each
        # other's change, and the example itself is as it was.
        assert read_node_code(first.page, NODE) == FIRST_GUESTS
        assert read_node_code(second.page, NODE) == SECOND_GUESTS
        assert _spec_code(backend, first.token(), example) == FIRST_GUESTS
        assert _spec_code(backend, second.token(), example) == SECOND_GUESTS
        newcomer = api_json(f"{backend}/api/auth/signin/guest", "", method="POST", payload={})["token"]
        assert _spec_code(backend, newcomer, example) == ORIGINAL

        # Every tab named the dataflow its page shows, the guests' never their copies'.
        for tab in (first, second):
            tab.names_only(example)
        for tab in (owner, editor):
            tab.names_only(dataflow)
    finally:
        for context in contexts:
            context.close()
