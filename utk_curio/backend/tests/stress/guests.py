"""Hosted guests on one example (``--guests``), each on its own copy of it.

A Curio started with ``--deploy`` lets visitors in as hosted guests: each
visit signs in to the shared guest's account (``POST /api/auth/signin/guest``),
a session of its own, and its gallery lists the account's examples
(``GET /api/projects``). A guest's edits, plays and agents work on a copy of
the example of its own, made on its first change (``projects/visitor_copies.py``),
so a workshop of guests on one example never meets each other's work.

Each guest of a tier does what a guest's page does (:class:`GuestVisit`):

* signs in, finds the example in its gallery by its name and opens it as the
  canvas does (``GET /api/projects/<id>?results=last``), naming it in
  ``X-Curio-Dataflow``; what it opens must be the example, with no work of any
  guest in it;
* behind the tier's start gate, opens a tab of it, whose handshake and join
  name the example, as the page does (``requestHeaders.ts``): the join answers
  with the id of the room it joined, its own copy's, which the tab's later
  events name (``sockets.Tab``), and which must not be the example's;
* takes the lock of the example's first Python node (:func:`guest_node`),
  types two comment lines in its code and lets the lock go
  (``sockets.Tab.work``);
* once the server answered every keystroke, asks Node Builder, attached to
  that node, to put a line on top of its code (``agents.MemberTurn``), on
  Curio's scripted model, which ``run.py`` makes the stack's default for the
  tier, its replies queued for its own attachment; every call names the
  example, as the page's do, and the agent writes in the guest's copy;
* checks that its tab holds the agent's code and was told the turn's end, and
  that neither its tab nor the server's room (a joining tab's snapshot) still
  has an agent or a lock in it;
* reads its copy back as a reload does (the same ``GET``), which must hold its
  own work and nothing else (:func:`copy_problems`): its lines and its agent's
  in that node, and every other node as the example has it.

A guest of the stage's own (:class:`ExampleReader`), which changes nothing and
so never has a copy, opens the example before the tiers; after each tier it
opens it again, and the example must be as it was, and no two guests may have
joined one room.

**Sync.** A copy's room holds its guest's one tab, so no update waits for
another tab there. A guest's sync is each keystroke's and drag's time from its
tab to the server's answer, once the copy's doc holds it (``socket yjs
update``).

**Each copy's process.** With several backend processes each guest's copy
belongs to one of them; the report gives each copy its process and each
process its copies (``report.copy_process``).
"""

from __future__ import annotations

import time
from typing import Optional

from ..test_frontend.workflow_spec import parse_workflow_dict
from . import sockets
from .agents import MemberTurn, agent_content, present_in
from .driver import BURST, Pacing, UserFailed, UserResult, VirtualUser

#: The node a guest types in and asks Node Builder about: the example's first
#: Python node, by the type the harness reads the canvas's
#: ``curio.builtin/python-computation`` as.
GUEST_NODE_TYPE = "PYTHON_COMPUTATION"

#: The label of a guest's answered updates (``sockets.Tab``), its sync.
UPDATE_LABEL = "socket yjs update"

#: Who the reader's checks after a tier are recorded on.
READER = "the example's reader"


class GuestsError(RuntimeError):
    """The stage cannot run: its example cannot be found or opened."""


def node_codes(spec) -> dict:
    """Each node's code in *spec* (a dataflow as ``GET /api/projects/<id>``
    gives it), by node id; an empty text for a node whose code is no text."""
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    nodes = dataflow.get("nodes") if isinstance(dataflow, dict) else None
    return {
        node["id"]: node.get("content") if isinstance(node.get("content"), str) else ""
        for node in nodes or []
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    }


def guest_node(spec) -> Optional[str]:
    """The node of the example a guest types in and asks Node Builder about:
    the first Python node in the order the dataflow runs; None for a dataflow
    with none."""
    if not isinstance(spec, dict):
        return None
    for node in parse_workflow_dict(spec).topo_sorted_nodes():
        if node.type == GUEST_NODE_TYPE:
            return node.id
    return None


def named_in(listing, name: str) -> list:
    """The ids of the dataflows named *name* in a gallery's *listing*
    (``GET /api/projects``)."""
    entries = listing if isinstance(listing, list) else []
    return [entry.get("id") for entry in entries if isinstance(entry, dict) and entry.get("name") == name]


def find_example(listing, name: str) -> tuple[Optional[str], Optional[str]]:
    """The id of the one dataflow named *name* in a gallery's *listing*, and
    None; or None and what is wrong: no such dataflow, or several, which a
    guest could not tell apart."""
    named = named_in(listing, name)
    if len(named) == 1 and isinstance(named[0], str) and named[0]:
        return named[0], None
    if not named:
        return None, f"the guests' gallery lists no dataflow named {name!r}"
    return None, f"the guests' gallery lists {len(named)} dataflows named {name!r}, which a guest cannot tell apart"


def _lines(code: Optional[str]) -> set:
    return set((code or "").splitlines())


def changed_nodes(before: dict, after: dict) -> list[str]:
    """The nodes whose code *after* holds otherwise than *before* (both node
    id -> code), each named with the lines it gained, or as removed or added."""
    changed = []
    for node_id in sorted(set(before) | set(after)):
        if before.get(node_id) == after.get(node_id):
            continue
        if node_id not in after:
            changed.append(f"node {node_id} is gone")
        elif node_id not in before:
            changed.append(f"node {node_id} was added")
        else:
            gained = [line for line in after[node_id].splitlines() if line not in _lines(before[node_id])]
            changed.append(f"node {node_id} holds other code" + (f", with {gained[:3]!r}" if gained else ""))
    return changed


def copy_problems(copy: dict, example: dict, node_id: str, expected: str) -> list[tuple[str, str]]:
    """What is wrong with a guest's copy as its page read it back (*copy*,
    node id -> code), each with its failure kind: node *node_id* must hold
    *expected*, the guest's own work as it left it, and every other node of
    the *example* its code there. A line in a node that is neither the
    example's nor the guest's own there is work that is not its own
    (``leaked``); its node holding less than its own work, its lines or its
    agent's, is that work missing from its copy (``not_in_copy``)."""
    problems = []
    for node in sorted(set(copy) | set(example)):
        wanted = expected if node == node_id else example.get(node)
        held = copy.get(node)
        if held == wanted:
            continue
        mine = node == node_id
        if node not in copy:
            problems.append((f"its copy has no node {node}", "not_in_copy" if mine else "leaked"))
            continue
        if node not in example and not mine:
            problems.append((f"its copy has a node {node} the example has not", "leaked"))
            continue
        foreign = [line for line in held.splitlines() if line not in _lines(wanted)]
        if foreign:
            problems.append((f"node {node} of its copy holds lines that are not its own work: {foreign[:3]!r}",
                             "leaked"))
        elif mine:
            problems.append((f"node {node} of its copy does not hold its own work as it left it: it holds "
                             f"{held[:300]!r}, not {wanted[:300]!r}", "not_in_copy"))
        else:
            problems.append((f"node {node} of its copy lacks some of the example's code there", "leaked"))
    return problems


def shared_rooms(outcomes: list) -> list[str]:
    """Each room more than one guest's tab joined (the ``project_id`` of the
    guests' outcomes), with the guests in it: a copy is one guest's alone."""
    by_room: dict = {}
    for outcome in outcomes:
        if outcome.get("project_id"):
            by_room.setdefault(outcome["project_id"], []).append(str(outcome.get("guest")))
    return [f"{', '.join(sorted(guests))} joined one room, {room}"
            for room, guests in sorted(by_room.items()) if len(guests) > 1]


class _Guest(VirtualUser):
    """A hosted guest: a visit to the shared guest's account, with its own
    sign-in, on one example. Once it has opened the example every call names
    it (``X-Curio-Dataflow``), as the page names the dataflow it shows."""

    def __init__(self, backend_url: str, name: str, example: str, *, register_gate=None, start_gate=None,
                 pacing: Pacing = BURST, namespace: Optional[str] = None):
        super().__init__(backend_url, name, example, {}, None, {}, register_gate=register_gate,
                         start_gate=start_gate, pacing=pacing, namespace=namespace)

    def sign_in(self) -> None:
        """Sign in as a hosted guest, as the sign-in page's guest button does."""
        body = self._call("POST", "/api/auth/signin/guest", json_body={})
        self.token = body.get("token") if isinstance(body, dict) else None
        if not self.token:
            self._fail("/api/auth/signin/guest", "", "the guest sign-in answered no token", "http_error")
            raise UserFailed("guest sign-in returned no token")

    def listing(self):
        """The guest's gallery (``GET /api/projects``), which names no dataflow."""
        return self._call("GET", "/api/projects")

    def open(self, project_id: str) -> dict:
        """Open *project_id* as the canvas does, naming it from now on: its
        spec, the guest's own copy once it has one."""
        self.project_id = project_id
        body = self._call("GET", "/api/projects/:id", path_url=f"/api/projects/{project_id}",
                          params={"results": "last"})
        spec = body.get("spec") if isinstance(body, dict) else None
        if not isinstance(spec, dict):
            self._fail("/api/projects/:id", "", "opening the example answered no dataflow", "http_error")
            raise UserFailed("the example opened with no dataflow")
        return spec


class ExampleReader(_Guest):
    """A guest of the stage's own, which changes nothing and so never has a
    copy: it finds the example the tier's guests open (:meth:`open_example`)
    and, after each tier, opens it again (:meth:`check`)."""

    def __init__(self, backend_url: str, example: str, name: str):
        super().__init__(backend_url, READER, example)
        #: The example's name in the guests' gallery: its ``dataflow.name``.
        self.dataflow_name = name
        self.job: Optional[dict] = None

    def open_example(self) -> dict:
        """Sign in, find the example by its name and open it: what every guest
        of a tier needs of it (``id``, ``node_id``, ``codes``), the guests'
        job. Raises :class:`GuestsError` when it cannot, as the stage would
        measure nothing."""
        try:
            self.sign_in()
            example_id, problem = find_example(self.listing(), self.dataflow_name)
            if problem:
                raise GuestsError(problem)
            spec = self.open(example_id)
        except UserFailed as exc:
            detail = "; ".join(f"{s.endpoint}: {(s.error or '')[:200]}" for s in self.result.failures)
            raise GuestsError(f"{exc}: {detail}") from exc
        node_id = guest_node(spec)
        if node_id is None:
            raise GuestsError(f"{self.example} has no Python node for its guests to type in")
        self.job = {"example": self.example, "name": self.dataflow_name, "id": example_id,
                    "node_id": node_id, "codes": node_codes(spec)}
        return self.job

    def check(self, outcomes: list) -> UserResult:
        """Once a tier is over: the example opened again, which must be as it
        was before the tiers, and no room any two of the tier's guests
        joined. Each problem is a failure (``leaked``) of the result returned,
        which is no guest of the tier."""
        self.result = UserResult(user=READER, example=self.example, started_at=time.time())
        started = time.time()
        try:
            after = node_codes(self.open(self.job["id"]))
            changed = changed_nodes(self.job["codes"], after)
            if changed:
                self._fail("the example", "", "once the tier was over, the example itself held work: "
                           + "; ".join(changed), "leaked")
        except UserFailed:
            pass  # its Sample says why
        for shared in shared_rooms(outcomes):
            self._fail("guests' rooms", "", f"{shared}: a guest's copy is its own", "leaked")
        self.result.completed = not self.result.failures
        self.result.seconds = time.time() - started
        return self.result


class GuestVisit(_Guest):
    """One hosted guest's visit, as its page makes it: sign in, open the
    example, open its tab, type, ask Node Builder, check, read its copy back
    (:meth:`run`); every failure is recorded on its result. *job* is what
    every guest of the tier shares of the example
    (:meth:`ExampleReader.open_example`)."""

    def __init__(self, backend_url: str, name: str, index: int, job: dict, *, register_gate=None,
                 start_gate=None, pacing: Pacing = BURST, namespace: Optional[str] = None):
        super().__init__(backend_url, name, job["example"], register_gate=register_gate,
                         start_gate=start_gate, pacing=pacing, namespace=namespace)
        self.index = index
        self.job = job
        self.tab: Optional[sockets.Tab] = None
        self.turn: Optional[MemberTurn] = None
        #: The node's code as the guest's tab held it once its typing was
        #: answered, which its agent writes under its own line.
        self.typed: Optional[str] = None
        #: Its copy as it read it back (``read``, and the problems of each
        #: kind), the agents and the locks its room still had at the end, by
        #: name; None until read.
        self.copy: Optional[dict] = None
        self.present_at_end: Optional[list] = None
        self.locks_at_end: Optional[list] = None

    # -- the visit ------------------------------------------------------------

    def run(self) -> UserResult:
        """Sign in and open the example, then, behind the tier's start gate,
        the work on its copy (:meth:`on_its_copy`). Completed when all of it
        went with no failure."""
        started = time.time()
        went = False
        try:
            if self.register_gate is not None:
                with self.register_gate:
                    self.arrive()
            else:
                self.arrive()
            self._wait_at_start_gate()
            if self.pacing.arrival_delay:
                time.sleep(self.pacing.arrival_delay)
            went = self.on_its_copy()
        except UserFailed:
            self._release_start_gate()
        except Exception as exc:  # noqa: BLE001 - a crashed driver is a finding too
            self._release_start_gate()
            self._fail("driver", "", f"{type(exc).__name__}: {exc}", "transport")
        self.result.completed = went and not self.result.failures
        self.result.seconds = time.time() - started
        return self.result

    def arrive(self) -> None:
        """Sign in, find the example in the gallery and open it: what it
        opens must be the example, which no guest's work is in."""
        self.sign_in()
        if self.job["id"] not in named_in(self.listing(), self.job["name"]):
            self._fail("/api/projects", "", f"its gallery lists no dataflow named {self.job['name']!r} "
                       f"as the example {self.job['id']}", "http_error")
            raise UserFailed("the example is not in the guest's gallery")
        changed = changed_nodes(self.job["codes"], node_codes(self.open(self.job["id"])))
        if changed:
            self._fail("/api/projects/:id", "", "what it opened as the example held work that is not the "
                       "example's: " + "; ".join(changed), "leaked")
            raise UserFailed("the example it opened was not the example")

    def on_its_copy(self) -> bool:
        """Its tab, its typing and its agent on its copy, the checks once the
        turn is over, and its copy read back; whether all of it went."""
        record = self.socket_sample
        tab = sockets.Tab(self.name, self.project_id, sockets.SyncLedger(), record)
        self.tab = tab
        node_id = self.job["node_id"]
        try:
            tab.connect(lambda on_yjs, on_close: sockets.SocketLink(
                self.backend_url, self.namespace, self.token, on_yjs, on_close, on_room=tab.room_event,
                dataflow=self.project_id))
            tab.join()
            if tab.room_id == self.project_id:
                record("socket join_session", 0.0, False, f"its tab joined the example's own room, "
                       f"{self.project_id}, not a copy of its own", "leaked")
                return False
            tab.sync()
            target = [(node_id, "# ")]
            if tab.target(target)[0] != node_id:
                record("socket type", 0.0, False, f"its copy has no node {node_id} with code to type in", "socket")
                return False
            tab.work(target, self.pacing, lock=True)
            tab.wait_for_answers(sockets.CALL_TIMEOUT_S)
            self.typed = tab.code_of(node_id)
            self.turn = MemberTurn(self.name, node_id, agent_content(self.name, self.typed), early=False,
                                   dataflow=self.project_id)
            self.turn.run(self)
            self.after_the_turn(tab, self.turn)
        except sockets.TabFailed:
            return False  # what happened is already recorded
        finally:
            tab.close()
            self.result.tab = tab.summary()
        self.read_back(node_id)
        return True

    def after_the_turn(self, tab: sockets.Tab, turn: MemberTurn) -> None:
        """Once its turn is over: its tab holds the agent's write and was told
        the turn's end, and neither its tab nor then the server's room (a
        joining tab's snapshot) still has an agent or a lock in it. The tab
        is waited for first: an agent leaves the room, and lets go of its
        lock, a moment after its turn's end."""
        record = self.socket_sample
        wait = sockets.SETTLE_TIMEOUT_S
        if turn.landed:
            lacking = tab.wait_for_code({turn.node_id: turn.content}, wait)
            if lacking:
                record("agent write", wait, False, f"its agent's write of node {turn.node_id} was not in its tab "
                       f"{wait:.0f}s after the turn ended (the tab holds {lacking[turn.node_id]!r})"[:2000],
                       "agent_unsynced")
        if turn.end is not None and tab.wait_told_ends([turn.ask_id], wait):
            record("agent turn told", wait, False, f"its tab was never told that its agent's turn "
                   f"({turn.ask_id}) ended, {wait:.0f}s after it did", "agent_unsynced")
        shown = tab.wait_for_no_agents(wait)
        if shown:
            record("agents present", wait, False, f"its tab still showed {len(shown)} agent(s) in its room "
                   f"{wait:.0f}s after its turn: " + ", ".join(sorted(shown.values())), "agent_present")
        locks = tab.wait_for_no_locks(wait)
        if locks:
            record("socket locks", wait, False, f"its tab still showed {len(locks)} lock(s) {wait:.0f}s after "
                   "its turn: " + ", ".join(f"node {node} by {who}" for node, who in sorted(locks.items())),
                   "locked")
        try:
            snapshot = tab.server_room()
        except sockets.TabFailed:
            return  # recorded; the room's agents and locks stay not read
        here = present_in(snapshot.get("activity"))
        self.present_at_end = sorted(here.values())
        if here:
            record("agents present", 0.0, False, f"the server still had {len(here)} agent(s) in its room once "
                   "its turn was over: " + ", ".join(sorted(here.values())), "agent_present")
        held = snapshot.get("locks") if isinstance(snapshot.get("locks"), dict) else {}
        self.locks_at_end = sorted(f"{node} by {sockets.holder(lock)}" for node, lock in held.items())
        if held:
            record("socket locks", 0.0, False, f"the server still held {len(held)} lock(s) in its room once "
                   "its turn was over: " + ", ".join(self.locks_at_end), "locked")

    def read_back(self, node_id: str) -> None:
        """Its copy, read as a reload reads it (the same ``GET`` as its
        open), which must hold its own work and nothing else
        (:func:`copy_problems`): its agent's write where it landed, else its
        lines."""
        expected = self.turn.content if self.turn is not None and self.turn.landed else self.typed
        copy = node_codes(self.open(self.project_id))
        problems = copy_problems(copy, self.job["codes"], node_id, expected or "")
        self.copy = {"read": True,
                     "not_in_copy": [message for message, kind in problems if kind == "not_in_copy"],
                     "leaked": [message for message, kind in problems if kind == "leaked"]}
        for message, kind in problems:
            self._fail("its copy", node_id, message, kind)

    # -- the report -------------------------------------------------------------

    def outcome(self) -> dict:
        """What the guest did, for the report (``report.guests_summary``,
        ``report.process_summary``): a room of its own, its copy's, whose id
        is the one its tab's join answered (``project_id``), beside the
        example it copies (``example_id``); its sync, its agent's turn, and
        its checks."""
        tab = self.result.tab or {}
        turn = self.turn.outcome() if self.turn is not None else None
        asked = turn is not None and turn.get("asked")
        joined = tab.get("room_id") if tab.get("role") else None
        return {
            "room": self.index,
            "guest": self.name,
            "example": self.example,
            "example_id": self.job["id"],
            "project_id": joined if joined != self.job["id"] else None,
            "node_id": self.job["node_id"],
            "tab": tab,
            "updates": (tab.get("keystrokes") or 0) + (tab.get("drags") or 0),
            "sync_seconds": [sample.seconds for sample in self.result.samples
                             if sample.endpoint == UPDATE_LABEL and sample.ok],
            "agents": {
                "turn_seconds": [turn["seconds"]] if asked and turn.get("seconds") is not None else [],
                "phases": {phase: [seconds] for phase, seconds in ((turn or {}).get("phases") or {}).items()},
            },
            "turn": turn,
            "copy": self.copy,
            "present_at_end": self.present_at_end,
            "locks_at_end": self.locks_at_end,
        }


def slice_visits(job: dict, start_gate, register_gate) -> list:
    """The guests one harness process carries of a tier (``run.run_slice``)."""
    return [
        GuestVisit(job["backend_url"], job["names"][index], index, job["guests"], register_gate=register_gate,
                   start_gate=start_gate, pacing=job["pacing"][index], namespace=job["namespace"])
        for index in job["indices"]
    ]
