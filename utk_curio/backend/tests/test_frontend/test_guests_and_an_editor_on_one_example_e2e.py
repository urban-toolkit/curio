"""Playwright E2E: two hosted guests and an invited editor on one example.

Every request a dataflow's page sends with its sign-in names the dataflow it
works on, in a header, and its room's socket names it in its handshake's query
(``cli/backend_group.py`` reads both). With several backend processes
(``curio.py start --backend-processes N``) the router sends each to the
process that owns that dataflow, where its room and its doc are kept. A hosted
guest's canvas of an example works on the guest's own copy of it, which the
server keeps on the process the copy's own id names, so the guests of one
example spread over the processes: once the canvas's load of the example
answers with the copy's id (``copy_id``), the tab names the copy. Only reads
name the example, those its loads sent before their answers.

Two hosted guests open one example, which the shared guest account owns, and
each changes its node: each sees its own change, after a reload too, and never
the other's. An account holds the same example as a dataflow of its own, and
its owner invites an editor: each sees what the other writes there, and
neither guest does. Each guest's tab names its own copy on every write and on
every socket it opens, and no request of it names the other guest's copy; the
owner's and the editor's tabs name her dataflow on every request that carries
their sign-in, and on their sockets. A hosted guest's play runs in the browser:
it sends ``/processPythonCode`` and reports to ``/nodeRuntime``, paths that
name no dataflow. The editor's play is a run on the server, as an owner's is
(``FlowProvider``'s ``runsOnServer``), which the tab follows at
``/api/runs/<run>``, a path that names none either. An editor has no save
status (saving is the owner's), so the owner's canvas showing the editor's
change is the wait for the server to have it.

On a stack without sign-in (CI's test-isolated job) every tab is the shared
guest, the one local user, which owns the example: no copy is made, two tabs
of it share its edits, each names it, and its play is a run on the server.

A hosted guest's dashboard of the example names the guest's own copy as its
canvas does, from its load's answer or from the data its page was served
with, and its viewer's runs belong to the process the copy's own id names:
the example's process refuses a start that names the example. e2e-desktop's
stack runs 2 backend processes (``CURIO_E2E_BACKEND_PROCESSES``), so the
guests there are signed in so that their copies belong to the process that
is not the example's.
"""

from __future__ import annotations

import json
import os
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse, urlsplit

from playwright.sync_api import expect

from .utils import (
    allow_guest_login_env,
    api_json,
    auth_enabled_env,
    install_session_cookie,
    named_dataflow,
    node_locator,
    read_node_code,
    run_node_and_wait,
    serve_built_frontend,
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

#: The pinned Data Pool of the dashboards' example, which shows what NODE makes.
POOL = "one-example-pool"
#: What NODE makes in the dashboards' example as it ships: three rows.
SHIPPED_ROWS = (
    "import pandas as pd\n\n"
    "return pd.DataFrame({'block': ['a', 'b', 'c'], 'trees': [3, 7, 5]})\n"
)
#: What it makes in the first visitor's copy: five rows.
FIRST_GUESTS_ROWS = (
    "import pandas as pd\n\n"
    "return pd.DataFrame({'block': ['a', 'b', 'c', 'd', 'e'], 'trees': [3, 7, 5, 9, 4]})\n"
)


def _route() -> tuple[str, str]:
    """The header a request names its dataflow in, and the query argument a
    socket's handshake does: the ones the router reads."""
    from utk_curio.cli.backend_group import ROUTE_HEADER, ROUTE_QUERY

    return ROUTE_HEADER, ROUTE_QUERY


def _home_only(path: str) -> bool:
    """Whether the router sends a request to *path* to the home process
    whatever dataflow it names: the monitor's routes, a page's error reports
    among them."""
    return path == "/api/monitor" or path.startswith("/api/monitor/")


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

    def sent_naming(self, dataflow: str) -> int:
        """How many requests this tab sent with its sign-in that named
        *dataflow*."""
        return sum(1 for _method, _url, named in self.signed if named == dataflow)

    def followed_a_run(self) -> bool:
        """Whether this tab followed a run on the server, at
        ``/api/runs/<run>``, a path that names no dataflow."""
        return any("/api/runs/" in urlparse(url).path for _method, url, _named in self.signed)

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

    def names_its_copy(self, example: str, copy: str) -> None:
        """This tab, a hosted guest's on *example*, named its own copy of it,
        *copy*, on every write it sent with its sign-in and in the handshake
        of every socket it opened. A request of it that did not name the copy
        named the example and was a read, as the reads its loads of the
        example send before their answers name the copy are, or a report to
        the monitor, which the router sends to the home process whatever it
        names. No request named any other dataflow, nor none."""
        _header, query = _route()
        assert self.signed, f"{self.who}'s tab sent no request with its sign-in"
        others = [
            f"{method} {urlparse(url).path}: {named!r}"
            for method, url, named in self.signed if named not in (copy, example)
        ]
        assert not others, (
            f"{self.who}'s tab, on its copy {copy} of {example}, sent {len(others)} of {len(self.signed)} "
            f"requests naming another dataflow or none: {others[:10]}"
        )
        writes = [
            f"{method} {urlparse(url).path}: {named!r}"
            for method, url, named in self.signed
            if method != "GET" and named != copy and not _home_only(urlparse(url).path)
        ]
        assert not writes, (
            f"{self.who}'s tab sent {len(writes)} writes that did not name its copy {copy}: {writes[:10]}"
        )
        sockets = [url for url in self.sockets if "/socket.io/" in url]
        assert sockets, f"{self.who}'s tab opened no socket to its room"
        asked = [parse_qs(urlparse(url).query).get(query) for url in sockets]
        assert asked == [[copy]] * len(sockets), f"{self.who}'s sockets named {asked}, not its copy {copy}"


def _own_copy(tab: _Tab, example: str) -> str:
    """The id of the own copy of *example* of *tab*'s hosted guest: the one
    its sign-in and the example make (``visitor_copies.copy_id``), whose room
    its tab joins."""
    from utk_curio.backend.app.projects.visitor_copies import copy_id

    return copy_id(tab.token(), example)


def _spec_code(backend: str, token: str, dataflow: str) -> str:
    """The node's code as the canvas of the one signed in as *token* opens it."""
    spec = api_json(f"{backend}/api/projects/{dataflow}", token)["spec"]
    return next(node for node in spec["dataflow"]["nodes"] if node["id"] == NODE)["content"]


def _example(backend: str, hosted: bool, spec: dict | None = None) -> str:
    """The example: a dataflow the shared guest account owns, as every
    shipped example is, holding *spec*, by default :func:`_spec`'s."""
    route = "signin/guest" if hosted else "signin/auto-guest"
    signed_in = api_json(f"{backend}/api/auth/{route}", "", method="POST", payload={})
    return api_json(
        f"{backend}/api/testing/stub-project", "", method="POST",
        payload={"username": signed_in["user"]["username"], "name": NAME, "spec": spec or _spec()},
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
    # The local guest owns the example, so its play is a run on the server.
    run_node_and_wait(first.page, NODE)
    assert first.followed_a_run(), "the first tab's play followed no run at /api/runs/<run>"
    first.names_only(example)
    second.names_only(example)


def test_two_hosted_guests_keep_their_own_edits_and_an_editor_shares_the_owners_each_tab_naming_its_dataflow(
    app_frontend, current_server, browser,
):
    """With sign-in, each hosted guest's edit of the example is kept in its
    own copy and the invited editor shares the owner's dataflow, while every
    tab names the dataflow it works on: a guest's its own copy, the owner's
    and the editor's her dataflow. Without sign-in, two tabs of the local
    guest share the example (:func:`_two_tabs_of_the_local_guest`)."""
    hosted = auth_enabled_env()
    guests = allow_guest_login_env()
    if hosted:
        assert guests, "this stack turns guest login off, so it has no hosted guest"
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
        copies = {first.who: _own_copy(first, example)}
        first.names_its_copy(example, copies[first.who])
        set_node_code(first.page, NODE, FIRST_GUESTS)
        wait_for_changes_kept(first.page)
        _kept_for_the_visit(first)

        # The second visitor opens the example as it was, and changes it too.
        second = _Tab(browser, contexts, "the second guest")
        second.open(base, example, "owner")
        copies[second.who] = _own_copy(second, example)
        assert len({*copies.values(), example}) == 3, f"the two visitors' copies of {example}: {copies}"
        wait_for_node_code(second.page, NODE, ORIGINAL)
        set_node_code(second.page, NODE, SECOND_GUESTS)
        wait_for_changes_kept(second.page)
        _kept_for_the_visit(second)

        # Each reload opens that visitor's own copy, with its own change alone.
        for tab, code in ((first, FIRST_GUESTS), (second, SECOND_GUESTS)):
            tab.page.reload()
            node_locator(tab.page, NODE).wait_for(timeout=30000)
            wait_for_node_code(tab.page, NODE, code)
            opened = _spec_code(backend, tab.token(), example)
            assert opened == code, f"{tab.who}'s canvas opens {opened!r}, not its change"
        tokens = {first.token(), second.token()}
        assert len(tokens) == 2, "the two visitors share one sign-in"

        # A play in the first visitor's tab, which names no dataflow in its path.
        run_node_and_wait(first.page, NODE)
        played, reported = first.sent_to("/processPythonCode"), first.sent_to("/nodeRuntime")
        assert played, "the first guest's play sent no /processPythonCode"
        assert reported, "the first guest's play reported no outcome to /nodeRuntime"

        # The owner and the editor each see what the other writes, on her dataflow.
        owner.open(base, dataflow, "owner")
        editor.open(base, dataflow, "editor")
        wait_for_node_code(editor.page, NODE, ORIGINAL)
        set_node_code(owner.page, NODE, OWNERS)
        wait_for_changes_kept(owner.page)
        wait_for_node_code(editor.page, NODE, OWNERS)
        set_node_code(editor.page, NODE, EDITORS)
        # An editor has no save status: the owner's canvas showing the change
        # is the wait for the server to have it.
        wait_for_node_code(owner.page, NODE, EDITORS)
        # The editor's play, as an owner's, is a run on the server.
        run_node_and_wait(editor.page, NODE)
        assert editor.followed_a_run(), "the editor's play followed no run at /api/runs/<run>"
        kept = _spec_code(backend, owners["token"], dataflow)
        assert kept == EDITORS, f"the owner's dataflow holds {kept!r}"

        # Neither visitor sees what the owner and the editor wrote, nor each
        # other's change, and the example itself is as it was.
        newcomer = api_json(f"{backend}/api/auth/signin/guest", "", method="POST", payload={})["token"]
        seen = {
            "the first guest's canvas": read_node_code(first.page, NODE),
            "the second guest's canvas": read_node_code(second.page, NODE),
            "the first guest's copy": _spec_code(backend, first.token(), example),
            "the second guest's copy": _spec_code(backend, second.token(), example),
            "the example": _spec_code(backend, newcomer, example),
        }
        assert seen == {
            "the first guest's canvas": FIRST_GUESTS,
            "the second guest's canvas": SECOND_GUESTS,
            "the first guest's copy": FIRST_GUESTS,
            "the second guest's copy": SECOND_GUESTS,
            "the example": ORIGINAL,
        }

        # Every tab named the dataflow it works on: each guest's its own copy,
        # which the load of the example answers with, never the other's; the
        # owner's and the editor's her dataflow.
        for tab in (first, second):
            tab.names_its_copy(example, copies[tab.who])
            assert tab.sent_naming(copies[tab.who]), f"{tab.who}'s tab sent no request naming its copy"
            answered = named_dataflow(backend, tab.token(), example)
            assert answered == copies[tab.who], (
                f"{tab.who}'s load of the example names {answered!r}, not its own copy {copies[tab.who]}"
            )
        for tab in (owner, editor):
            tab.names_only(dataflow)
    finally:
        for context in contexts:
            context.close()


# ---------------------------------------------------------------------------
# Each hosted guest's dashboard of one example
# ---------------------------------------------------------------------------

def _dashboard_spec() -> dict:
    """The example the dashboards open: NODE makes a table of three rows,
    which the pinned Data Pool shows. Nothing of it is saved, so each
    dashboard starts a viewer's run as it opens, for the pool's rows."""
    def node(node_id: str, node_type: str, x: int, content: str = "", **more) -> dict:
        return {
            "id": node_id, "type": node_type, "x": x, "y": 0, "in": "DEFAULT", "out": "DEFAULT",
            "goal": "", "metadata": {"keywords": []}, "content": content, **more,
        }

    return {
        "name": NAME,
        "dataflow": {
            "name": NAME,
            "nodes": [
                node(NODE, "curio.builtin/python-computation", 0, SHIPPED_ROWS, title="Street trees"),
                node(POOL, "curio.builtin/data-pool", 700, dashboardPinned=True),
            ],
            "edges": [{"id": f"reactflow__edge-{NODE}out-{POOL}in", "source": NODE, "target": POOL}],
        },
    }


def _processes() -> int:
    """How many backend processes the stack runs behind its router: the
    job's ``CURIO_E2E_BACKEND_PROCESSES``, which ``docker-compose.ci.yml``
    starts the stack with, 1 when it names none."""
    try:
        return max(1, int(os.environ.get("CURIO_E2E_BACKEND_PROCESSES") or "1"))
    except ValueError:
        return 1


def _guests_off_the_examples_process(backend: str, example: str, processes: int, count: int) -> list[str]:
    """The sign-ins of *count* new hosted guests whose own copies of
    *example* belong to a backend process other than the example's, so the
    process that runs each one's dashboard tells its copy's from the
    example's (``visitor_copies.copy_id``, ``shard_of``); with one process,
    the first *count*."""
    from utk_curio.backend.app.projects.visitor_copies import copy_id
    from utk_curio.common.backend_processes import shard_of

    examples = shard_of(example, processes)
    chosen: list[str] = []
    for _ in range(64):
        token = api_json(f"{backend}/api/auth/signin/guest", "", method="POST", payload={})["token"]
        if processes <= 1 or shard_of(copy_id(token, example), processes) != examples:
            chosen.append(_authenticated(backend, token))
            if len(chosen) == count:
                return chosen
    raise AssertionError(f"of 64 hosted guests, fewer than {count} have a copy of {example} off its process {examples}")


def _authenticated(backend: str, token: str, *, timeout: float = 60.0) -> str:
    """*token*, once it authenticates. A sign-in made a moment ago can meet a
    pooled reader of the database that does not see it yet, as
    ``utils/db_stubs._await_session`` says, and a page whose first request is
    refused signs in anew, as another visitor."""
    deadline = time.time() + timeout
    while True:
        try:
            api_json(f"{backend}/api/auth/me", token)
            return token
        except HTTPError as exc:
            if exc.code != 401 or time.time() >= deadline:
                raise
        time.sleep(0.05)


def _served_as_the_hosted_stacks_serve_it(base: str, backend: str, monkeypatch) -> str:
    """The production page server on the built bundle, which serves a
    dashboard's page with its data, built for the sign-in of the visitor
    who opens it (``cli/static_server.py``). Started the hosted way, with
    ``--backend-url /api``: it asks this stack's backend, which the launcher
    hands it as ``FLASK_BACKEND_HOST`` and ``FLASK_BACKEND_PORT``. It is
    opened on the app's own host, so the browser's sign-in is the page's."""
    address = urlsplit(backend)
    monkeypatch.setenv("FLASK_BACKEND_HOST", address.hostname)
    monkeypatch.setenv("FLASK_BACKEND_PORT", str(address.port))
    return serve_built_frontend("/api", host=urlsplit(base).hostname)


class _Dashboard:
    """A dashboard's page in one person's browser (a page of *tab*'s
    context), and what it sent the backend with its sign-in: each request,
    with the dataflow it names."""

    def __init__(self, tab: _Tab, url: str):
        self.who = f"{tab.who}'s dashboard"
        self.page = tab.context.new_page()
        self.signed: list[tuple[str, str, str | None]] = []
        header = _route()[0].lower()
        self.page.on("request", lambda request: self._sent(request, header))
        self.page.goto(url, timeout=120000)
        self.page.get_by_test_id("open-dataflow-link").wait_for(state="visible", timeout=45000)

    def _sent(self, request, header: str) -> None:
        headers = request.headers
        if "authorization" in headers:
            self.signed.append((request.method, request.url, headers.get(header)))

    def served_with_its_data(self) -> bool:
        return self.page.locator("script#curio-dashboard-payload").count() == 1

    def shows_rows(self, rows: int) -> None:
        """The pinned pool's table holds *rows* rows, which only the viewer's
        run the page started as it opened makes: nothing is saved."""
        table = node_locator(self.page, POOL).locator("table").first
        expect(table.locator("tbody tr")).to_have_count(rows, timeout=90000)

    def _runs(self) -> tuple[list, list, list]:
        """Each request of the page's viewer's runs, its starts and its
        streams, as ``(method, path, named)``."""
        runs = [
            (method, urlsplit(url).path, named) for method, url, named in self.signed
            if "/dashboard/runs" in urlsplit(url).path
        ]
        starts = [run for run in runs if run[0] == "POST" and run[1].endswith("/dashboard/runs")]
        streams = [run for run in runs if run[0] == "GET" and run[1].endswith("/stream")]
        assert starts and streams, f"{self.who} started no viewer's run, or followed none: {runs}"
        return runs, starts, streams

    def names_its_copy(self, example: str, copy: str) -> None:
        """This page, a hosted guest's dashboard of *example*, named its own
        copy of it, *copy*, on every write it sent with its sign-in and on
        every request of its viewer's runs, their starts and their streams,
        whose paths name the example. A request of it that did not name the
        copy named the example and was a read, sent before the page knew
        the copy, or a report to the monitor, which the router sends to the
        home process whatever it names. No request named another dataflow,
        nor none."""
        assert self.signed, f"{self.who} sent no request with its sign-in"
        others = [
            f"{method} {urlsplit(url).path}: {named!r}"
            for method, url, named in self.signed if named not in (copy, example)
        ]
        assert not others, (
            f"{self.who}, on its copy {copy} of {example}, sent {len(others)} of {len(self.signed)} "
            f"requests naming another dataflow or none: {others[:10]}"
        )
        writes = [
            f"{method} {urlsplit(url).path}: {named!r}"
            for method, url, named in self.signed
            if method != "GET" and named != copy and not _home_only(urlsplit(url).path)
        ]
        assert not writes, f"{self.who} sent {len(writes)} writes that did not name its copy {copy}: {writes[:10]}"
        runs = self._runs()[0]
        astray = [
            f"{method} {path}: {named!r}" for method, path, named in runs
            if named != copy or not path.startswith(f"/api/projects/{example}/dashboard/runs")
        ]
        assert not astray, (
            f"{self.who}'s viewer's runs did not name its copy {copy}, or their paths the example {example}: "
            f"{astray[:10]}"
        )

    def names_only(self, dataflow: str) -> None:
        """Every request this page sent with its sign-in named *dataflow*, its
        viewer's runs among them."""
        assert self.signed, f"{self.who} sent no request with its sign-in"
        others = [
            f"{method} {urlsplit(url).path}: {named!r}"
            for method, url, named in self.signed if named != dataflow
        ]
        assert not others, f"{self.who}, on dataflow {dataflow}, sent requests naming another or none: {others[:10]}"
        self._runs()


def _refused_on_the_examples_process(backend: str, token: str, example: str, copy: str, processes: int) -> None:
    """A start of the guest's dashboard's run that names the example, as a
    page that knew no copy would send it, reaches the example's process,
    which refuses it (421), naming the process the guest's copy belongs to."""
    from utk_curio.common.backend_processes import shard_of

    try:
        answer = api_json(
            f"{backend}/api/projects/{example}/dashboard/runs", token, method="POST",
            payload={"values": {}}, dataflow=example,
        )
    except HTTPError as exc:
        status, said = exc.code, exc.read().decode("utf-8", "replace")
    else:
        status, said = None, json.dumps(answer)
    owner, here = shard_of(copy, processes), shard_of(example, processes)
    assert status == 421, (
        f"the example's process {here} answered a start of a hosted guest's dashboard run with {status}, "
        f"not a refusal naming the guest's copy's process {owner}: {said}"
    )
    named = [copy, f"belongs to backend process {owner}", f"process {here} of {processes}"]
    assert all(part in said for part in named), f"the refusal does not name {named}: {said}"


def _the_local_guests_dashboard(browser, contexts: list, base: str, example: str) -> None:
    """Without sign-in the shared guest is the one local user and owns the
    example, which no copy is made of: its dashboard names the example on
    every request, its viewer's run among them."""
    tab = _Tab(browser, contexts, "the local guest")
    dashboard = _Dashboard(tab, f"{base}/dashboard/{example}")
    dashboard.shows_rows(3)
    dashboard.names_only(example)


def test_each_hosted_guests_dashboard_of_one_example_names_its_copy_and_runs_on_that_copys_process(
    app_frontend, current_server, browser, monkeypatch,
):
    """Each hosted guest's dashboard of an example names the guest's own
    copy, as its canvas does, and its viewer's run belongs to the backend
    process that copy's own id names, made or not yet. The two guests here
    have copies off the example's process.

    The first changes the example on its canvas, which makes its copy, and
    opens the dashboard as the hosted stacks serve it, with its data, which
    the page server built for that guest's sign-in: the page names the copy
    the data names, and its run on open runs the copy, whose five rows the
    pool shows. The second only looks, so has no copy: its dashboard, on a
    page that loads its own data, names the copy the load answers with, and
    its run on open runs the example as it ships, three rows. Each page's
    viewer's run, its start and its stream, names the copy, its path the
    example, and the example's process refuses a start that names the
    example, naming the copy's process. The example is as it shipped.

    Without sign-in the local guest owns the example, and its dashboard names
    the example (:func:`_the_local_guests_dashboard`)."""
    hosted = auth_enabled_env()
    base, backend = app_frontend.base_url, current_server
    example = _example(backend, hosted, _dashboard_spec())
    contexts: list = []
    try:
        if not hosted:
            _the_local_guests_dashboard(browser, contexts, base, example)
            return
        assert allow_guest_login_env(), "this stack turns guest login off, so it has no hosted guest"
        processes = _processes()
        first, second = _Tab(browser, contexts, "the first guest"), _Tab(browser, contexts, "the second guest")
        for tab, token in zip((first, second), _guests_off_the_examples_process(backend, example, processes, 2)):
            install_session_cookie(tab.page, base, token)
        copies = {tab.who: _own_copy(tab, example) for tab in (first, second)}
        assert len({*copies.values(), example}) == 3, f"the two visitors' copies of {example}: {copies}"

        # The first visitor changes the example on its canvas: its own copy holds it.
        first.open(base, example, "owner")
        set_node_code(first.page, NODE, FIRST_GUESTS_ROWS)
        wait_for_changes_kept(first.page)
        _kept_for_the_visit(first)
        dashboards = {first.who: _Dashboard(
            first, f"{_served_as_the_hosted_stacks_serve_it(base, backend, monkeypatch)}/dashboard/{example}",
        )}
        assert dashboards[first.who].served_with_its_data(), (
            "the page server, started as the hosted stacks start it, served the dashboard without its data"
        )
        dashboards[first.who].shows_rows(5)

        # The second visitor only looks, on a page that loads its own data.
        dashboards[second.who] = _Dashboard(second, f"{base}/dashboard/{example}")
        assert not dashboards[second.who].served_with_its_data(), "this stack's own page server served its data"
        dashboards[second.who].shows_rows(3)

        for tab in (first, second):
            dashboards[tab.who].names_its_copy(example, copies[tab.who])
            answered = named_dataflow(backend, tab.token(), example)
            assert answered == copies[tab.who], (
                f"{tab.who}'s load of the example names {answered!r}, not its own copy {copies[tab.who]}"
            )
            if processes > 1:
                _refused_on_the_examples_process(backend, tab.token(), example, copies[tab.who], processes)
        newcomer = api_json(f"{backend}/api/auth/signin/guest", "", method="POST", payload={})["token"]
        seen = {
            "the first guest's copy": _spec_code(backend, first.token(), example),
            "the example": _spec_code(backend, newcomer, example),
        }
        assert seen == {"the first guest's copy": FIRST_GUESTS_ROWS, "the example": SHIPPED_ROWS}, seen
    finally:
        for context in contexts:
            context.close()
