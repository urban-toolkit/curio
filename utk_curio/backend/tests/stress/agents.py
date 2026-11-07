"""Each member's agent on a shared canvas (``--agents``), on Curio's scripted model.

With ``--agents`` every member of a shared canvas (``--shared-canvas``) also
asks Node Builder to write the code of its own node, as a person asks the
agent on a node through its chat: it attaches the agent to its node
(``POST /api/agents/projects/<id>/attachments``), asks it a turn
(``POST .../attachments/<id>/turns``), which runs on a thread of the server,
and follows the turn to its end (``GET .../turns/<askId>/stream``). The agent
joins the room, waits for anyone else in the node, takes the node's lock and
writes through the dataflow's doc, as it does on the canvas
(``agents/application/in_the_room.py``, ``proposals/changes.py``). An
editor's turn runs on the owner's model, so each member drives the owner's
agent. The room's owner installs Node Builder in the dataflow before it
invites anyone (:meth:`RoomAgents.install`); every new dataflow holds it
already, and an install is idempotent.

**The model** is Curio's scripted one (``agents/infrastructure/testing_provider.py``):
for the tier ``run.py`` makes it Curio's default (:func:`on_the_scripted_model`),
which an account with no LLM configuration of its own answers with, and puts
the launch's models back after. Each member queues the replies of its own
attachment's calls (:func:`script_body`, with ``reset`` off, which would
drop every other member's): the write, then a line of text
(:func:`write_reply`, :data:`DONE_REPLY`). The conversation's title, asked
once the agent left the room, takes from the shared queue, which nobody
fills, so it gets the scripted model's inert reply. No LLM is asked and no
token spent: a live model is out, as the owner's gateway takes about eight
calls at once, so a hundred turns would measure it, not Curio.

**What the agent writes** is the node's code as the member's tab holds it when
it asks, under a line naming the member's agent (:func:`agent_content`): a
pass-through still, so every result stays the solo baseline's, and in a room
where people typed in the members' nodes their lines stay.

**When a member asks**, so that nobody types in a node while its agent writes
it. Where the room's example has a code node, people type there and never in
the members' own nodes: each member asks as soon as its node is in every tab
(:meth:`RoomAgents.ask_early`), so the agents work while people type and drag.
Where it has none (examples 11 and regression), the members type in their own
nodes, two to a node: each member asks once the room's typing is over and its
tabs agreed, as it starts to play the dataflow (:meth:`RoomAgents.ask_late`),
so the agents work while people play. Either way every turn of a room ends
before its owner runs the dataflow on the server and saves it
(:meth:`RoomAgents.before_the_run`), so the save holds every agent's code; and
no write lands while the room's tabs compare their docs.

**What is checked.** A turn must end ``done`` with its write landed (the
``tool_result`` of its write says ``applied``): one that ends in an error,
never ends (:data:`TURN_TIMEOUT_S`) or writes nothing is a failure
(``agent_turn``), and so is a write refused; a refusal because the node took
other code after the agent read it is its own kind (``changed_meanwhile``),
since none should happen. Before the tabs compare their docs, and again once
the room's work is over, every tab must hold each landed write
(``agent_unsynced``); then the tabs compare their docs again, every agent's
code in them (``diverged``), and each tab must have been told the end of every
turn (``agent_turn`` events, ``agent_unsynced``). No agent may still be in the
room then, on the server (a joining tab's Activity) or in a tab
(``agent_present``), nor hold a lock (``sockets._locks_at_the_end``), and the
save must hold each agent's code (``unsaved``).
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Callable, Optional

import requests

from . import sockets
from .driver import API_TIMEOUT_S, Sample, UserFailed

#: The agent each member asks, and what it asks.
COORD = "agent.curio.node-builder@1"
MESSAGE = "Put a line naming you on top of my node's code, and keep the rest as it is."
#: The line the agent puts on top of the node's code, a comment in Python.
AGENT_LINE = "# {member}'s Node Builder wrote this line"
#: The model's last reply of the turn, once its write is answered.
DONE_REPLY = "Your node's code now starts with a line naming me; the rest is as it was."
#: The tool the agent writes with, and the status of a write that landed
#: (``changes.LANDED``).
WRITE_TOOL = "node.content.write"
LANDED = "applied"
#: The events that end an ask (``turn_jobs.ENDINGS``, and its withdrawal).
ENDINGS = ("done", "error", "withdrawn")

# Each wait is a judgement, as sockets.py's are:
#   TURN   - from the ask to the turn's end. A scripted turn does no model work:
#            it waits at most LOCK_WAIT_S (30 s) for a person in its node and
#            keeps its lock a second after its write; one still going five
#            minutes on under the 100-user burst is stuck, and is stopped.
#   WAIT   - how long a member waits for its agent's work as a whole: the
#            three calls before the turn, each bounded by API_TIMEOUT_S, and
#            the turn.
#   BROKEN - how many times a turn's stream that broke is followed again.
TURN_TIMEOUT_S = 5 * 60
TURN_WAIT_S = TURN_TIMEOUT_S + 3 * API_TIMEOUT_S + 30
FOLLOW_AGAIN = 3


def agent_content(member: str, code: Optional[str]) -> str:
    """What *member*'s agent writes in its node: the line naming it, then
    *code*, the node's code as the member's tab holds it when it asks (the
    member's own pass-through when it holds none). Stripped, as the server
    keeps an agent's code (``content.extract_node_content``), so a tab and
    the save must hold it as it is."""
    code = code if isinstance(code, str) and code.strip() else sockets.PASS_ON_CODE
    return f"{AGENT_LINE.format(member=member)}\n{code}".strip()


def write_reply(node_id: str, content: str) -> str:
    """The model's reply that writes *content* in node *node_id*: a tool
    request in the fenced protocol, which the scripted endpoint speaks."""
    request = {"toolRequest": {"tool": WRITE_TOOL, "params": {"nodeId": node_id, "content": content}}}
    return "```curio.v1\n" + json.dumps(request) + "\n```"


def script_body(attachment_id: str, node_id: str, content: str) -> dict:
    """The body that queues a member's replies, for its attachment's calls
    alone: the write, then a line of text. ``reset`` stays off: on, it would
    drop every other member's queue and let go of every hold."""
    return {"replies": [write_reply(node_id, content), DONE_REPLY], "attachmentId": attachment_id,
            "reset": False}


def changed_meanwhile(node_id: str) -> str:
    """What a write refused because its node took other code after the
    agent read it says (``change.changed-meanwhile``), as the reason of its
    ``tool_result`` carries it: its first line."""
    from utk_curio.backend.app.agents.domain import agent_text

    return agent_text.message("change.changed-meanwhile", node_id=repr(node_id)).strip().splitlines()[0]


def is_changed_meanwhile(node_id: str, reason: Optional[str]) -> bool:
    """Whether a refused write's *reason* says its node changed meanwhile.
    False when the message cannot be read: the refusal is then a failure of
    the turn all the same."""
    try:
        return (reason or "").strip() == changed_meanwhile(node_id)
    except Exception:  # noqa: BLE001 - never hides the refusal, only its kind
        return False


def turn_envelope(event: Optional[str], line: str) -> Optional[dict]:
    """The room envelope a line of an ask's Server-Sent Events carries: the
    data of a ``turn`` event; None for any other line."""
    if event != "turn" or not line.startswith("data:"):
        return None
    try:
        envelope = json.loads(line[len("data:"):].strip())
    except ValueError:
        return None
    return envelope if isinstance(envelope, dict) else None


def turn_envelopes(lines) -> list:
    """Every room envelope the lines of an ask's Server-Sent Events carry."""
    found, event = [], None
    for line in lines:
        if line.startswith("event:"):
            event = line[len("event:"):].strip()
            continue
        envelope = turn_envelope(event, line)
        if envelope is not None:
            found.append(envelope)
    return found


def present_in(activity) -> dict:
    """The agents a room's Activity (a joining tab's snapshot) still has in
    the room: each agent's join with no leave after it, participant id ->
    name (``agent_peers.JOINED_EVENT``, ``LEFT_EVENT``)."""
    here: dict = {}
    for entry in activity or []:
        if not isinstance(entry, dict):
            continue
        payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
        who = payload.get("participant_id")
        if entry.get("kind") == "agent_joined" and isinstance(who, str):
            here[who] = str(payload.get("name") or "an agent")
        elif entry.get("kind") == "agent_left":
            here.pop(who, None)
    return here


def _request(user, session, method: str, label: str, path: str, *, json_body=None,
             expect=200, timeout: float = API_TIMEOUT_S) -> dict:
    """One call of a member's agent work on *session*, recorded on the
    member's result as its own calls are (``VirtualUser._call``), under
    *label*; raises ``UserFailed`` on anything but *expect*."""
    started = time.time()
    try:
        resp = session.request(method, f"{user.backend_url}{path}", json=json_body,
                               headers=user._headers(), timeout=timeout)
    except requests.Timeout:
        user._record(label, None, None, started, False, f"no response in {timeout:.0f}s", "timeout")
        raise UserFailed(f"{label} timed out")
    except requests.RequestException as exc:
        user._record(label, None, None, started, False, str(exc)[:500], "transport")
        raise UserFailed(f"{label} transport error")
    expected = (expect,) if isinstance(expect, int) else expect
    if resp.status_code not in expected:
        user._record(label, None, resp.status_code, started, False, resp.text[:500], "http_error")
        raise UserFailed(f"{label} returned {resp.status_code}")
    user._record(label, None, resp.status_code, started, True)
    try:
        return resp.json() if resp.content else {}
    except ValueError:
        return {}


# ---------------------------------------------------------------------------
# One member's turn
# ---------------------------------------------------------------------------

class MemberTurn:
    """One member's agent at work on its node: attached, scripted, asked and
    followed on a thread of its own (:meth:`run`), then judged
    (:meth:`judge`). *early*: it asked as its node was in, not once the
    room's typing was over."""

    def __init__(self, member: str, node_id: str, content: str, *, early: bool):
        self.member = member
        self.node_id = node_id
        self.content = content
        self.early = early
        self.attachment_id: Optional[str] = None
        #: The ask's id, chosen here as a tab chooses one, to follow it by.
        self.ask_id = uuid.uuid4().hex
        #: Whether the ask was answered (202), and when it was sent.
        self.asked = False
        self.asked_at: Optional[float] = None
        #: From the ask to its end, as its follow read it.
        self.seconds: Optional[float] = None
        #: How the turn ended (:data:`ENDINGS`), with its error; None until it did.
        self.end: Optional[str] = None
        self.error: Optional[str] = None
        #: The last result of its write: its status and why, as its
        #: ``tool_result`` event says; None while it wrote nothing.
        self.write: Optional[str] = None
        self.reason: Optional[str] = None
        #: The events its follows read, and the streams that broke.
        self.events = 0
        self.broken = 0
        self._seen: set = set()
        #: Set once the work is over, however it ended.
        self.over = threading.Event()

    # -- the turn's events ------------------------------------------------------

    def take(self, envelope: dict) -> None:
        """One envelope its follow read: the ask as it stood (``snapshot``),
        whose kept events may hold its whole turn, or one of its events."""
        if not isinstance(envelope, dict):
            return
        if envelope.get("event") == "snapshot":
            view = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
            for kept in view.get("events") or []:
                if isinstance(kept, dict):
                    self._event(kept.get("seq"), kept.get("event"), kept.get("data"))
            return
        self._event(envelope.get("seq"), envelope.get("event"), envelope.get("data"))

    def _event(self, seq, name, data) -> None:
        if seq is not None:
            if seq in self._seen:
                return  # a follow again replays what the last one read
            self._seen.add(seq)
        self.events += 1
        data = data if isinstance(data, dict) else {}
        if name == "tool_result" and data.get("tool") == WRITE_TOOL:
            self.write, self.reason = data.get("status"), data.get("reason")
        elif name in ENDINGS and self.end is None:
            self.end = name
            self.error = data.get("error") if name == "error" else None
            if self.asked_at is not None:
                self.seconds = time.perf_counter() - self.asked_at

    @property
    def landed(self) -> bool:
        return self.write == LANDED

    # -- the work ---------------------------------------------------------------

    def run(self, user, on_over: Callable[["MemberTurn"], None] = lambda turn: None) -> None:
        """Attach, script, ask and follow, on this thread, then judge; every
        failure is recorded on *user*'s result, never raised. *on_over* is
        told once the work is over."""
        session = requests.Session()
        base = f"/api/agents/projects/{user.room.project_id}"
        try:
            attached = _request(user, session, "POST", "/api/agents/projects/:id/attachments",
                                f"{base}/attachments", expect=201,
                                json_body={"coord": COORD, "target": {"kind": "node", "targetId": self.node_id}})
            self.attachment_id = attached.get("attachmentId")
            if not self.attachment_id:
                user._fail("/api/agents/projects/:id/attachments", self.node_id,
                           f"attaching {COORD} to its node answered no attachment: {attached!r}", "agent_turn")
                return
            _request(user, session, "POST", "/api/testing/agent-script", "/api/testing/agent-script",
                     json_body=script_body(self.attachment_id, self.node_id, self.content))
            turns = f"{base}/attachments/{self.attachment_id}/turns"
            self.asked_at = time.perf_counter()
            _request(user, session, "POST", "/api/agents/projects/:id/attachments/:id/turns", turns,
                     expect=202, json_body={"message": MESSAGE, "askId": self.ask_id})
            self.asked = True
            self._follow(user, session, f"{turns}/{self.ask_id}")
        except UserFailed:
            pass  # its Sample says why
        except Exception as exc:  # noqa: BLE001 - a crashed agent thread is a finding too
            user._fail("agent turn", self.node_id, f"{type(exc).__name__}: {exc}", "agent_turn")
        finally:
            session.close()
            try:
                self.judge(user)
            finally:
                self.over.set()
                on_over(self)

    def _follow(self, user, session, ask: str) -> None:
        """Follow the ask to its end (``turns/<askId>/stream``), as a tab no
        room holds does, and again after a stream that broke, until
        :data:`TURN_TIMEOUT_S` after the ask; a turn still going then is
        stopped (``.../stop``), so it never leaks into a later run."""
        label = "/api/agents/projects/:id/attachments/:id/turns/:id/stream"
        deadline = self.asked_at + TURN_TIMEOUT_S
        while self.end is None and time.perf_counter() < deadline and self.broken <= FOLLOW_AGAIN:
            started = time.time()
            try:
                with session.get(f"{user.backend_url}{ask}/stream", headers=user._headers(), stream=True,
                                 timeout=(API_TIMEOUT_S, max(1.0, deadline - time.perf_counter()))) as resp:
                    if resp.status_code != 200:
                        user._record(label, None, resp.status_code, started, False, resp.text[:500], "http_error")
                        break
                    resp.encoding = "utf-8"
                    event = None
                    for line in resp.iter_lines(decode_unicode=True):
                        if line.startswith("event:"):
                            event = line[len("event:"):].strip()
                        else:
                            self.take(turn_envelope(event, line))
                        if self.end is not None or time.perf_counter() >= deadline:
                            break
                user._record(label, None, 200, started, True)
            except requests.RequestException as exc:
                if time.perf_counter() >= deadline:
                    break  # nothing came before the turn's deadline: judged as never ended
                self.broken += 1
                user._record(label, None, None, started, False,
                             f"the turn's stream broke before its end: {type(exc).__name__}: {exc}"[:500],
                             "transport")
        if self.end is None:
            try:
                session.post(f"{user.backend_url}{ask}/stop", headers=user._headers(), timeout=API_TIMEOUT_S)
            except requests.RequestException:
                pass  # what is judged is the turn's end, or that none came

    def judge(self, user) -> None:
        """Record how the turn went on *user*'s result, as ``agent turn`` with
        the turn's time: one failure for an end that is no ``done`` or for a
        write that did not land, and a refusal because the node changed
        meanwhile as its own kind, naming the node and the asker. Nothing
        for a turn never asked: what stopped it is recorded where it
        happened."""
        if not self.asked:
            return
        failures = []
        meanwhile = self.write not in (None, LANDED) and is_changed_meanwhile(self.node_id, self.reason)
        if meanwhile:
            failures.append((f"{COORD}'s write of node {self.node_id}, asked by {self.member}, was refused: the "
                             "node took other code after the agent read it, though nobody else writes it while "
                             "its agent does", "changed_meanwhile"))
        if self.end is None:
            failures.append((f"its agent's turn on node {self.node_id} never ended: no end "
                             f"{TURN_TIMEOUT_S:.0f}s after it asked, so it was stopped", "agent_turn"))
        elif self.end != "done":
            failures.append((f"its agent's turn on node {self.node_id} ended {self.end}"
                             + (f": {self.error}" if self.error else ""), "agent_turn"))
        elif self.write is None:
            failures.append((f"its agent's turn on node {self.node_id} ended done without writing it",
                             "agent_turn"))
        elif not self.landed and not meanwhile:
            failures.append((f"its agent's write of node {self.node_id} did not land ({self.write}): "
                             f"{self.reason or 'no reason given'}", "agent_turn"))
        seconds = self.seconds if self.seconds is not None else float(TURN_TIMEOUT_S)
        if not failures:
            user.result.samples.append(Sample("agent turn", self.node_id, None, seconds, True))
        for message, kind in failures:
            user.result.samples.append(Sample("agent turn", self.node_id, None, seconds, False, message[:2000], kind))

    def outcome(self) -> dict:
        """The turn for the report: who asked, when and how it ended, and
        its write."""
        write = self.write
        if write not in (None, LANDED):
            write = "changed_meanwhile" if is_changed_meanwhile(self.node_id, self.reason) else "refused"
        return {
            "member": self.member, "node_id": self.node_id, "attachment_id": self.attachment_id,
            "ask_id": self.ask_id if self.asked else None, "asked": self.asked, "early": self.early,
            "end": self.end, "seconds": None if self.seconds is None else round(self.seconds, 2),
            "write": "landed" if write == LANDED else (write or "none"), "reason": self.reason,
            "events": self.events, "broken_streams": self.broken,
        }


# ---------------------------------------------------------------------------
# A room's agents
# ---------------------------------------------------------------------------

class RoomAgents:
    """The agents of a shared canvas's members (``room.agents``): when each
    member asks, the waits that keep every write out of the tabs' compare of
    their docs and ahead of the owner's run, and the checks once the room's
    work is over."""

    def __init__(self, room):
        self.room = room
        self._cond = threading.Condition()
        #: Each member's turn, once it asked; the members that had no node to ask about.
        self.turns: dict[str, MemberTurn] = {}
        self.skipped: set = set()
        #: (member, node id) of each landed write a member's tab lacked, and
        #: (member, ask id) of each turn its tab was never told the end of:
        #: each said once.
        self._unsynced: set = set()
        self._untold: set = set()
        #: The tabs' digests once the room's work was over (:meth:`at_the_end`).
        self._digests: dict = {}
        self.diverged = False
        #: The agents the server still had in the room at the end, by name, as
        #: the room's first tab there read them; None until read.
        self.present_at_end: Optional[list] = None
        self._presence_reader: Optional[str] = None

    @property
    def early(self) -> bool:
        """Whether the members ask as their nodes are in: the room's example
        has a code node to type in (``room.targets``), so nobody types in a
        member's node. Its owner sets those before it invites anyone, so
        every member reads the same."""
        return bool(self.room.targets)

    # -- the owner, before anyone opens the dataflow ---------------------------

    def install(self, user) -> None:
        """The owner installs the agent in its dataflow before it invites
        anyone, so every attach finds it there; an install is idempotent."""
        try:
            _request(user, user.session, "POST", "/api/agents/projects/:id/install",
                     f"/api/agents/projects/{user.project_id}/install", expect=201, json_body={"coord": COORD})
        except UserFailed:
            pass  # its Sample says why; every attach then says so too

    # -- asking -----------------------------------------------------------------

    def ask_early(self, user, tab) -> None:
        """As the member's node is in every tab: ask now where nobody types in
        it (:attr:`early`)."""
        if self.early:
            self._start(user, tab)

    def ask_late(self, user, tab) -> None:
        """As the member starts to play the dataflow, the room's typing over
        and its tabs compared: ask now where people typed in the members'
        nodes."""
        if not self.early:
            self._start(user, tab)

    def _start(self, user, tab) -> None:
        node = getattr(user, "own_node", None)
        if not isinstance(node, dict) or not node.get("id"):
            with self._cond:
                self.skipped.add(user.name)
                self._cond.notify_all()
            return
        turn = MemberTurn(user.name, node["id"], agent_content(user.name, tab.code_of(node["id"])),
                          early=self.early)
        with self._cond:
            self.turns[user.name] = turn
        threading.Thread(target=turn.run, args=(user, self._over), name=f"agent-{user.name}",
                         daemon=True).start()

    def _over(self, _turn: MemberTurn) -> None:
        with self._cond:
            self._cond.notify_all()

    def _wait_for_own(self, user) -> None:
        """Wait for the member's own agent's work to be over."""
        turn = self.turns.get(user.name)
        if turn is not None and not turn.over.wait(TURN_WAIT_S):
            user._fail("agent turn", turn.node_id, f"its agent's work on node {turn.node_id} was still going "
                       f"{TURN_WAIT_S:.0f}s after it began", "agent_turn")

    def wait_over(self, timeout: float) -> None:
        """Every turn's work over, at most *timeout* in all: the users'
        results go to the main process only then, whole."""
        deadline = time.monotonic() + timeout
        with self._cond:
            turns = list(self.turns.values())
        for turn in turns:
            turn.over.wait(max(0.0, deadline - time.monotonic()))

    # -- the waits --------------------------------------------------------------

    def before_compare(self, user, tab) -> None:
        """Before the room's tabs compare their docs, in a room whose members
        asked at once: the member's own turn over, then every member's, a
        member's that left the room among them, then every landed write in
        its tab, so no write lands while they compare."""
        if not self.early:
            return
        self._wait_for_own(user)
        self.room.reach("turns ended", user.name, TURN_WAIT_S)
        self.wait_over(TURN_WAIT_S)
        self._writes_in_tab(user, tab)

    def after_plays(self, user) -> None:
        """Once the member's plays are over: its own turn over too."""
        self._wait_for_own(user)

    def before_the_run(self, user) -> None:
        """The owner, before it runs the dataflow on the server and saves it:
        every member still in the room has asked, and every turn asked is
        over, a member's that left the room among them, so the run reads
        every agent's code and the save holds it."""
        deadline = time.monotonic() + TURN_WAIT_S
        with self._cond:
            while True:
                waiting = sorted({member for member in self.room.members if self.room.present(member)
                                  and member not in self.skipped and member not in self.turns}
                                 | {turn.member for turn in self.turns.values() if not turn.over.is_set()})
                left = deadline - time.monotonic()
                if not waiting or left <= 0:
                    break
                # A member's leave is not told here: look again each second.
                self._cond.wait(min(left, 1.0))
        if waiting:
            user._fail("agent turn", "", f"the owner ran and saved the dataflow with {len(waiting)} member(s)' "
                       f"agent work still going after {TURN_WAIT_S:.0f}s: {', '.join(waiting)}", "agent_turn")

    # -- the checks -------------------------------------------------------------

    def landed(self) -> dict:
        """Each landed write: node id -> (the member, the code it wrote)."""
        with self._cond:
            return {turn.node_id: (turn.member, turn.content) for turn in self.turns.values() if turn.landed}

    def _writes_in_tab(self, user, tab) -> None:
        """Every landed write in the member's tab, waited for up to
        ``sockets.SETTLE_TIMEOUT_S``; each one it lacks is a failure, said
        once per tab and node."""
        landed = self.landed()
        lacking = tab.wait_for_code({node_id: code for node_id, (_member, code) in landed.items()},
                                    sockets.SETTLE_TIMEOUT_S)
        for node_id in sorted(lacking):
            with self._cond:
                if (user.name, node_id) in self._unsynced:
                    continue
                self._unsynced.add((user.name, node_id))
            user.result.samples.append(Sample(
                "agent write", node_id, None, sockets.SETTLE_TIMEOUT_S, False,
                f"{landed[node_id][0]}'s agent's write of node {node_id} was not in its tab "
                f"{sockets.SETTLE_TIMEOUT_S:.0f}s after every turn of the room ended (the tab holds "
                f"{lacking[node_id]!r})"[:2000], "agent_unsynced"))

    def at_the_end(self, user, tab) -> None:
        """Once every member's work is over (``done``), before any tab
        closes: every landed write in the member's tab; the room's tabs
        compare their docs again, every agent's code in them; neither the
        server, as a tab joining then is told, nor the member's tab may have
        an agent in the room; and the tab must have been told the end of
        every turn that ended. Nothing here raises, so the room's locks are
        read after it all the same."""
        record = user.socket_sample
        self._writes_in_tab(user, tab)
        with self._cond:
            self._digests[user.name] = tab.digest()
        self.room.reach("agents compared", user.name, sockets.ROOM_WAIT_S)
        with self._cond:
            reference = next(m for m in self.room.members if m in self._digests)
            differs = self._digests[reference] != self._digests[user.name]
            if differs:
                self.diverged = True
        if differs:
            record("agents converge", 0.0, False,
                   f"once every agent's turn had ended, its nodes, connections, code or places differ from "
                   f"{reference}'s tab's", "diverged")
        with self._cond:
            if self._presence_reader is None:
                self._presence_reader = user.name
            reads = self._presence_reader == user.name
        if reads:
            try:
                snapshot = tab.server_room()
            except sockets.TabFailed:
                snapshot = None  # recorded; the presence stays not read
            if snapshot is not None:
                here = present_in(snapshot.get("activity"))
                self.present_at_end = sorted(here.values())
                if here:
                    record("agents present", 0.0, False,
                           f"the server still had {len(here)} agent(s) in the room once its work was over: "
                           + ", ".join(sorted(here.values())), "agent_present")
        shown = tab.wait_for_no_agents(sockets.SETTLE_TIMEOUT_S)
        if shown:
            record("agents present", sockets.SETTLE_TIMEOUT_S, False,
                   f"its tab still showed {len(shown)} agent(s) in the room {sockets.SETTLE_TIMEOUT_S:.0f}s after "
                   "its work was over: " + ", ".join(sorted(shown.values())), "agent_present")
        with self._cond:
            ended = {turn.ask_id: turn.member for turn in self.turns.values() if turn.end is not None}
        for ask_id in tab.wait_told_ends(list(ended), sockets.SETTLE_TIMEOUT_S):
            record("agent turn told", sockets.SETTLE_TIMEOUT_S, False,
                   f"its tab was never told that {ended[ask_id]}'s agent's turn ({ask_id}) ended, "
                   f"{sockets.SETTLE_TIMEOUT_S:.0f}s after the room's work was over", "agent_unsynced")
            with self._cond:
                self._untold.add((user.name, ask_id))

    def saved_lacks(self, saved: dict) -> list:
        """What the saved dataflow (``backend_probe.saved_specs``) lacks of
        the agents' work: the code each landed write wrote, as it is."""
        nodes = saved.get("nodes") or {}
        return [f"{member}'s agent's code in node {node_id}"
                for node_id, (member, code) in sorted(self.landed().items(), key=lambda item: item[1][0])
                if nodes.get(node_id) != code]

    # -- the report -------------------------------------------------------------

    def outcome(self, tabs: list) -> dict:
        """What the room's agents did, for the report (``report.agents_summary``)."""
        with self._cond:
            turns = [turn.outcome() for turn in self.turns.values()]
            unsynced, untold = len(self._unsynced), len(self._untold)
        asked = [turn for turn in turns if turn["asked"]]
        ends = {"done": 0, "error": 0, "withdrawn": 0, "never": 0}
        writes = {"landed": 0, "changed_meanwhile": 0, "refused": 0, "none": 0}
        for turn in asked:
            ends[turn["end"] or "never"] = ends.get(turn["end"] or "never", 0) + 1
            writes[turn["write"]] = writes.get(turn["write"], 0) + 1
        return {
            "early": self.early,
            "members": len(self.room.members),
            "asked": len(asked),
            "ends": ends,
            "turn_seconds": [turn["seconds"] for turn in asked if turn["seconds"] is not None],
            "writes": writes,
            "unsynced": unsynced + untold,
            "present_at_end": self.present_at_end,
            "tabs_showing_agents": sum(1 for tab in tabs if tab.get("agents_shown")),
            "turn_events_told": sum(tab.get("agent_events", 0) for tab in tabs),
            "diverged": self.diverged,
            "turns": turns,
        }


def on_the_scripted_model(backend_url: str, run):
    """*run* (a tier) with Curio's scripted model as this Curio's default
    (``POST /api/testing/llm-deployment {"scripted": true}``), and the
    launch's models back after it, whatever it did (``DELETE``). A stack
    started without ``--testing`` serves no such route: the run stops, as a
    stage on such a stack would measure nothing."""
    url = f"{backend_url}/api/testing/llm-deployment"
    try:
        resp = requests.post(url, json={"scripted": True}, timeout=API_TIMEOUT_S)
        endpoints = (resp.json() or {}).get("endpoints") if resp.status_code == 200 else None
    except (requests.RequestException, ValueError) as exc:
        raise SystemExit(f"[stress] --agents could not make the scripted model Curio's default: {exc}") from exc
    if not endpoints or [endpoint.get("name") for endpoint in endpoints] != ["Scripted"]:
        raise SystemExit(f"[stress] --agents needs a stack started with --testing: {url} answered "
                         f"{resp.status_code} {resp.text[:200]}")
    print("[stress] Curio's default model is the scripted one for the tier", flush=True)
    try:
        return run()
    finally:
        try:
            requests.delete(url, timeout=API_TIMEOUT_S)
            print("[stress] Curio's own models are back", flush=True)
        except requests.RequestException as exc:
            print(f"[stress] Curio's own models could not be put back: {exc}", flush=True)
