"""A hosted guest's dashboard of an example names the guest's own copy of it,
as its canvas does, and its viewer runs belong to the backend process the
copy's own id names (``projects/visitor_copies.py``, ``runs/viewer.py``,
``collaboration/owner_guard.py``).

In a start of several backend processes a hosted guest's copy of an example
belongs to the process its own id names, made or not yet, so the guests of one
example spread over the processes. The dashboard's page learns the copy's id
as the canvas does: from the load of the dataflow (``GET /api/projects/<id>``'s
``copy_id``), or, on a page served with its data, from that data
(``GET /api/projects/<id>/dashboard``'s ``copy_id``), and names the copy in
every request from then on (``src/utils/requestHeaders.ts``). So a viewer's
run of a hosted guest's dashboard is kept by the copy's process, whether the
copy is made yet or not, and the example's process refuses it (421, naming
the copy's process). Anyone else's dashboard run, a visitor's who sends no
sign-in or an account's, belongs to the dashboard's dataflow, as before.

At any process count a hosted guest's runs are its own copy's dashboard's
from its first visit, made or not yet (``dashboard:<copy id>`` in the run
registry): they join and wait on no other visitor's runs of the example's
dashboard, though they keep on the example while the guest has no copy, as
anyone's run of it does.

Here this test's process is set as one of two by the variables the launcher
sets, as ``test_collaboration/test_owner_guard.py`` sets it, before the
guard's first answer, on the example of ``test_guest_dashboard_copy.py``,
whose sandbox and page reader these tests use. Each new visitor's sign-in is
made so its copy belongs to the process a test needs. The page's ``copy_id``
and the registry's dashboards are read in a start of one process, where they
are the same.
"""
from __future__ import annotations

import json

import pytest

from utk_curio.backend import config
from utk_curio.backend.app.runs.models import KeptStepOutput
from utk_curio.backend.tests.test_collaboration._processes import (
    as_process,
    assert_names_the_owner,
    owner_of,
)
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers
from utk_curio.backend.tests.test_projects.test_guest_copy_leaks import VISITOR_A, VISITOR_B, _copy_of
from utk_curio.backend.tests.test_projects.test_guest_dashboard_copy import (  # noqa: F401 - fixtures
    COPY_CODE,
    EDGES,
    MINE,
    SHIPPED_CODE,
    _change,
    _load,
    _nodes,
    _payload,
    _ran,
    _shade,
    _start,
    app,
    dashboard,
    embedded,
    sandbox,
)
from utk_curio.backend.tests.test_runs.test_dashboard_viewer_runs import _wait

#: Values a viewer tries on the example's pinned control, Shade's Period.
MONTH = {"shade": {"period": "Month"}}
YEAR = {"shade": {"period": "Year"}}


@pytest.fixture()
def unsaved(client, db, monkeypatch):
    """The example of ``test_guest_dashboard_copy.py``'s ``dashboard`` with no
    output saved, so each value of Shade's Period, the saved one too, runs
    Shade: three runs of three values can go at once. Visitors A and B are
    signed in to the shared guest account, with sign-in on, as there. Its
    id."""
    from utk_curio.backend.app.users.models import User, UserSession

    guest = User(username=config.CURIO_SHARED_GUEST_USERNAME, name="Guest",
                 email="guest@test.com", is_guest=True)
    db.session.add(guest)
    db.session.flush()
    for token in (VISITOR_A, VISITOR_B):
        db.session.add(UserSession(user_id=guest.id, token=token))
    db.session.commit()
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
    created = client.post("/api/projects", data=json.dumps({
        "name": "Example",
        "spec": {"dataflow": {"name": "Example", "nodes": _nodes(), "edges": EDGES}},
        "outputs": [],
    }), headers=auth_headers(VISITOR_A))
    assert created.status_code == 201, created.get_data(as_text=True)
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    return created.get_json()["id"]


def _visitor_whose_copy_belongs_to(example: str, process: int) -> str:
    """A new visitor's sign-in to the shared guest account, as another
    browser's, whose own copy of *example* belongs to the backend process
    numbered *process* (``visitor_copies.copy_id``, ``shard_of``)."""
    from utk_curio.backend.app.users.models import User, UserSession
    from utk_curio.backend.extensions import db

    guest = User.query.filter_by(username=config.CURIO_SHARED_GUEST_USERNAME).one()
    token = next(
        candidate for candidate in (f"hosted-guest-dashboard-visitor-{n}" for n in range(500))
        if owner_of(_copy_of(candidate, example)) == process
        and UserSession.query.filter_by(token=candidate).first() is None
    )
    db.session.add(UserSession(user_id=guest.id, token=token))
    db.session.commit()
    return token


def _an_accounts_sign_in() -> str:
    """The sign-in of an account of its own, not the shared guest's, which
    opens the example's dashboard from its link."""
    from utk_curio.backend.app.users.models import User, UserSession
    from utk_curio.backend.extensions import db

    user = User(username="hers", name="Hers", email="hers@test.com")
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSession(user_id=user.id, token="an-accounts-sign-in"))
    db.session.commit()
    return "an-accounts-sign-in"


def _refused(resp, dataflow: str, owner: int, here: int) -> None:
    """*resp* is a refusal of this process's: 421, naming *dataflow*, the
    process that owns it and this one."""
    assert resp.status_code == 421, (
        f"{resp.status_code}: process {here} started a dashboard's run that belongs to process {owner}, "
        f"which owns {dataflow}: {resp.get_data(as_text=True)}"
    )
    assert_names_the_owner(resp.get_json()["error"], dataflow, owner, here)


# ---------------------------------------------------------------------------
# The page names the copy
# ---------------------------------------------------------------------------

def test_a_hosted_guests_dashboard_page_names_its_own_copy_before_the_copy_is_made(client, dashboard, embedded):
    """The page served with its data names the copy the guest's sign-in and
    the example make, the one the load of the example names, and makes none:
    a visitor who only looks makes no copy."""
    from utk_curio.backend.app.projects import visitor_copies

    example = dashboard[0]

    for token in (VISITOR_A, VISITOR_B):
        page = _payload(client, token, example)
        assert "copy_id" in page, (
            "the dashboard's page names no copy, so it names the example in every request, "
            "and its runs reach the example's process"
        )
        assert page["copy_id"] == _copy_of(token, example), (token, page["copy_id"])
        assert page["copy_id"] == _load(client, token, example)["copy_id"], (
            f"{token}'s dashboard page and its load name two copies"
        )

    mine, theirs = _copy_of(VISITOR_A, example), _copy_of(VISITOR_B, example)
    assert len({mine, theirs, example}) == 3, "two visitors' copies of the example share an id"
    assert not visitor_copies.is_copy(mine) and not visitor_copies.is_copy(theirs), "a dashboard's page made a copy"


def test_the_copy_a_dashboard_page_names_is_the_copy_it_carries(client, dashboard, embedded):
    """A's copy holds A's change: A's page carries it and names it; B's page,
    of a guest with no copy, carries the example and names B's own copy."""
    example = dashboard[0]
    own = _change(VISITOR_A, example, COPY_CODE)

    mine, theirs = _payload(client, VISITOR_A, example), _payload(client, VISITOR_B, example)

    assert _shade(mine["spec"])["content"] == COPY_CODE
    assert mine.get("copy_id") == own, f"A's page carries A's copy {own} and names {mine.get('copy_id')!r}"
    assert _shade(theirs["spec"])["content"] == SHIPPED_CODE
    assert theirs.get("copy_id") == _copy_of(VISITOR_B, example), theirs.get("copy_id")


def test_a_dashboard_page_names_no_copy_for_anyone_else(client, dashboard, embedded, monkeypatch):
    """A visitor who sends no sign-in, an account, and the local guest, the
    one user of a Curio started without ``--deploy``, whose example is its own
    dataflow: each one's page names the example itself (``copy_id`` null), as
    each one's load does."""
    example = dashboard[0]
    account = _an_accounts_sign_in()

    pages = {"no sign-in": _payload(client, None, example), "an account": _payload(client, account, example)}
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
    pages["the local guest"] = _payload(client, VISITOR_A, example)

    for who, page in pages.items():
        assert "copy_id" in page and page["copy_id"] is None, (who, page.get("copy_id", "no copy_id at all"))


def test_a_hosted_guests_dashboard_page_of_its_own_new_dataflow_names_no_copy(client, dashboard, embedded):
    """A visitor's File > New copies no dataflow: its page names its own id."""
    created = client.post("/api/projects", data=json.dumps({
        "name": "New", "spec": {"dataflow": {"name": "New", "nodes": _nodes(), "edges": EDGES}}, "outputs": [],
    }), headers=auth_headers(VISITOR_A))
    assert created.status_code == 201, created.get_data(as_text=True)
    assert created.get_json()["kept_for_visit"] is True

    page = _payload(client, VISITOR_A, created.get_json()["id"])

    assert "copy_id" in page and page["copy_id"] is None, page.get("copy_id", "no copy_id at all")


# ---------------------------------------------------------------------------
# Its runs belong to the copy's process
# ---------------------------------------------------------------------------

def test_a_hosted_guests_dashboard_runs_on_its_copys_process_before_the_copy_is_made(
    client, dashboard, sandbox, monkeypatch,
):
    """A guest who only looks has no copy yet: its dashboard runs the example
    as it ships and keeps on the example, on the process its copy's own id
    names, which its page names. The example's process refuses that run,
    naming the copy's process, and keeps a run of a visitor who sends no
    sign-in, as before; the copy's process refuses that one, naming the
    example's. No run makes a copy."""
    from utk_curio.backend.app.projects import visitor_copies
    from utk_curio.backend.app.runs import viewer

    example = dashboard[0]
    examples = owner_of(example)
    copies = 1 - examples
    guest = _visitor_whose_copy_belongs_to(example, copies)
    own = _copy_of(guest, example)
    # The guard reads the start's process count, so it is named before the
    # guard's first answer.
    as_process(monkeypatch, examples)

    _refused(_start(client, guest, example, MONTH), own, copies, examples)
    assert sandbox.runs == [], "a refused run ran a step"
    _ran(client, None, example, MONTH)

    as_process(monkeypatch, copies)
    _refused(_start(client, None, example, YEAR), example, examples, copies)
    mine = _ran(client, guest, example, YEAR)

    assert viewer.REGISTRY.get_job(mine["runId"]) is not None, "the copy's process holds no run of the guest's"
    codes = [run[1]["code"] for run in sandbox.runs]
    assert len(codes) == 2 and all(MINE not in code for code in codes), codes
    assert '"Month"' in codes[0] and '"Year"' in codes[1], codes
    assert {row.project_id for row in KeptStepOutput.query.all()} == {example}, (
        "a run of the example's dashboard kept elsewhere than on the example"
    )
    assert not visitor_copies.is_copy(own), "a dashboard's run made the guest a copy"


def test_a_hosted_guests_dashboard_runs_its_own_copy_on_the_copys_process(client, dashboard, sandbox, monkeypatch):
    """A guest's change made its copy, on the copy's own process, as the
    guest's tab makes it there: its dashboard's run of the copy is that
    process's, and the example's process refuses it, naming the copy's. An
    account's run of the example's dashboard is the example's process's, as
    before, and the copy's process refuses it, naming the example's."""
    from utk_curio.backend.app.runs import viewer

    example = dashboard[0]
    examples = owner_of(example)
    copies = 1 - examples
    guest = _visitor_whose_copy_belongs_to(example, copies)
    account = _an_accounts_sign_in()
    # Named before the guard's first answer: the copy's own process makes it.
    as_process(monkeypatch, copies)
    own = _change(guest, example, COPY_CODE)

    as_process(monkeypatch, examples)
    _refused(_start(client, guest, example, {}), own, copies, examples)
    assert sandbox.runs == [], "a refused run ran a step"

    as_process(monkeypatch, copies)
    _refused(_start(client, account, example, MONTH), example, examples, copies)
    # Opening the page: Shade holds the copy's change, which its saved output
    # was not made by, so it runs.
    opened = _ran(client, guest, example, {})
    assert viewer.REGISTRY.get_job(opened["runId"]) is not None, "the copy's process holds no run of the guest's"
    assert [(node, MINE in body["code"]) for node, body in sandbox.runs] == [("shade", True)], sandbox.runs
    assert [row.project_id for row in KeptStepOutput.query.all()] == [own], "the copy's run kept elsewhere than on it"

    as_process(monkeypatch, examples)
    _ran(client, account, example, MONTH)
    theirs = sandbox.runs[-1][1]["code"]
    assert len(sandbox.runs) == 2 and MINE not in theirs and '"Month"' in theirs, theirs


# ---------------------------------------------------------------------------
# Its runs are its own copy's dashboard's
# ---------------------------------------------------------------------------

def _started(resp) -> dict:
    """The answer of a start that started a run of its own."""
    assert resp.status_code == 202, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["runId"] and body["joined"] is False, body
    return body


def _waits(resp, what: str) -> None:
    """*resp* is a start refused while a dashboard runs as many runs as it may."""
    assert resp.status_code == 429, f"{what}: {resp.status_code} {resp.get_data(as_text=True)}"


def test_a_hosted_guests_dashboard_runs_are_its_own_copys_from_its_first_visit(client, unsaved, sandbox):
    """With the example's dashboard at its two live runs, an anonymous
    visitor's, a third start of it waits. Two hosted guests with no copy yet
    still start runs of their own, each as its own copy's dashboard: a start
    of values one of the visitor's runs runs does not join that run, and a
    start of the third values does not wait. Each guest counts against its
    own copy's dashboard alone: it starts as many runs as one dashboard may
    have, a start of values its own run runs joins that run, and one more
    waits. Every run keeps on the example, as anyone's run of it does, so a
    guest's later run of values a visitor ran reuses what that run kept."""
    from utk_curio.backend.app.projects import visitor_copies

    example = unsaved
    #: Shade's Period as the example saves it, Date, which has no saved output here.
    saved_values: dict = {}
    sandbox.hold.add("shade")
    runs: list[str] = []
    try:
        anyones = {"Month": _started(_start(client, None, example, MONTH)),
                   "Year": _started(_start(client, None, example, YEAR))}
        runs += [body["runId"] for body in anyones.values()]
        _waits(_start(client, None, example, saved_values), "a third start of the example's dashboard")

        theirs: set[str] = set()
        for token in (VISITOR_A, VISITOR_B):
            month = _start(client, token, example, MONTH)
            assert month.status_code == 202, month.get_data(as_text=True)
            assert month.get_json()["joined"] is False, (
                f"{token}, with no copy yet, joined the anonymous visitor's run of the same values: "
                f"{month.get_json()}"
            )
            mine = {"Month": _started(month), "Date": _started(_start(client, token, example, saved_values))}
            ids = {body["runId"] for body in mine.values()}
            assert not ids & {body["runId"] for body in anyones.values()} and not ids & theirs, (token, ids)
            again = _start(client, token, example, MONTH)
            assert again.status_code == 202, again.get_data(as_text=True)
            assert (again.get_json()["runId"], again.get_json()["joined"]) == (mine["Month"]["runId"], True)
            assert again.get_json()["token"] == mine["Month"]["token"]
            _waits(_start(client, token, example, YEAR), f"{token}'s third start, past its own dashboard's two")
            theirs |= ids
        runs += sorted(theirs)
    finally:
        sandbox.release()

    for run_id in runs:
        _wait(run_id)
    assert len(runs) == 6, runs
    assert {row.project_id for row in KeptStepOutput.query.all()} == {example}, (
        "a run of a guest with no copy kept elsewhere than on the example"
    )
    ran = len(sandbox.runs)
    # The visitor's Year was kept on the example: a guest's run of it now
    # reuses it, and runs nothing.
    _ran(client, VISITOR_B, example, YEAR)
    assert len(sandbox.runs) == ran, "a guest's run ran a step a visitor's run of the same values had kept"
    for token in (VISITOR_A, VISITOR_B):
        assert not visitor_copies.is_copy(_copy_of(token, example)), f"a dashboard's run made {token} a copy"
