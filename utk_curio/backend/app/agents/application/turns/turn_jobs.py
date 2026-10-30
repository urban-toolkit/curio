"""A chat turn as a job: asked, waiting its turn, run on a thread of the
server, and followed from every tab of the dataflow's editors.

An ask to an attachment's agent (:func:`ask`) is checked in the request that
asks (``prepare.check_runnable``), then runs as a job of its own
(``agent_jobs.start_turn``), as Solve's jobs and the server's runs do: on a
thread of the server, in the request that asked taken on again
(``askers.as_asked``), so it goes on when the tab that asked closes or
reloads, and reads who asked as the request did. One turn runs at a time per
attachment: an ask to a busy attachment waits in order, and starts when the
turn before it ends, reading the conversation as that turn left it. Asks to
different attachments run side by side.

Each event of an ask reaches the tabs of the owner and the editors in the
dataflow's room (:data:`EVENT`, ``roles.tell_editors``), a watcher's never:
that it was asked and by whom, that it started, its reply's text as it is
written, its tool calls and delegations, the changes it lands, and its end.
Each carries the ask's id and its place among the ask's events (``seq``). A
tab that opens meanwhile reads the asks as they stand (:func:`asks_of`): the
message, who wrote it, the reply's text so far and the ask's other events,
then takes the events after them. A tab no room holds, a hosted guest's,
follows an ask over HTTP instead (:func:`follow`).

Whoever asked can withdraw a waiting ask (:func:`withdraw`). Whoever asked,
the owner or any editor can stop a running turn (:func:`stop`): it stops at
its next step (``turn_loop.Stop``), and what it said and landed until then
stays.

Asks live in this process, as every job does: a restart drops the waiting
ones and ends the running ones.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Iterator, Optional

from utk_curio.backend.app.agents.application import askers as agents_askers
from utk_curio.backend.app.agents.application import in_the_room as agents_room
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.application.turns import prepare as agents_prepare
from utk_curio.backend.app.agents.application.turns import turn_loop
from utk_curio.backend.app.agents.infrastructure import agent_jobs
from utk_curio.backend.app.agents.infrastructure import provider_config
from utk_curio.backend.app.agents.infrastructure import testing_provider
from utk_curio.backend.app.collaboration import roles
from utk_curio.common.redaction import redact

log = logging.getLogger(__name__)

#: The room's event that carries an ask's events to the tabs that edit the
#: dataflow: ``{projectId, attachmentId, askId, seq, event, data}``.
EVENT = "agent_turn"

WAITING = "waiting"
RUNNING = "running"
ENDED = "ended"

#: What an ask says of itself, besides its turn's own events.
ASKED = "asked"
STARTED = "started"
WITHDRAWN = "withdrawn"
#: The turn's own events that end it (``AttachmentTurn.stream``).
ENDINGS = frozenset({"done", "error"})
#: An ask's id, which the tab that asks may choose, so the room's events of
#: the ask find the message that tab shows already.
_ASK_ID = re.compile(r"^[0-9a-f]{32}$")
#: How long an ended ask stays readable by its id, for an answer or a
#: follower that comes after its end, as a finished job does.
ENDED_KEPT_S = agent_jobs.FINISHED_TTL_SECONDS
#: How long a blocking ask waits for its turn's thread once the turn ended.
_JOIN_S = 30.0


@dataclass(eq=False)
class Ask:
    """One message asked of an attachment's agent, and its turn."""

    ask_id: str
    user_key: str
    project_id: str
    attachment_id: str
    message: str
    context: Optional[str]
    config: object = field(repr=False)
    #: Whether the reply streams as the model writes it, else it arrives
    #: whole with the turn's end (a blocking ask's).
    streaming: bool
    #: Who wrote the message, as the chat names its writer (``askers.writer``).
    by: Optional[dict]
    #: Who asked, as the room names them: their account, and on the guest
    #: account their sign-in (``in_the_room.asker``).
    who: agents_room.Asker
    #: The request that asked, which the turn runs in again (``askers.as_asked``).
    asking: agents_askers.Asking = field(repr=False)
    #: The app the ask came to, whose context the turn's thread runs in.
    app: object = field(repr=False)
    asked_at: float = field(default_factory=time.time)
    state: str = WAITING
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    #: The place of the ask's last event among its events.
    seq: int = -1
    #: The reply's text so far: every delta of its turn.
    text: str = ""
    #: The turn's other events so far, each as the room had it, the last
    #: ``usage`` alone among them.
    kept: list = field(default_factory=list)
    execution_id: Optional[str] = None
    stop: turn_loop.Stop = field(default_factory=turn_loop.Stop)
    #: What the turn settled with (``AttachmentTurn.result``).
    result: Optional[dict] = None
    #: Why it failed: its message, and the status a blocking ask answers.
    failure: Optional[tuple] = None
    #: What interrupted its turn that is no failure (a ``BaseException``,
    #: such as an evaluation's seam stopping a run it has seen enough of):
    #: raised again to whoever waits for the turn, as it reached the request
    #: the turn used to run in (:func:`settled`).
    interruption: Optional[BaseException] = None
    job: object = field(default=None, repr=False)
    #: Held while one of its events is told, so they are told in order; a
    #: thread may hold it around telling one (:func:`ask`).
    lock: object = field(default_factory=threading.RLock, repr=False)
    followers: list = field(default_factory=list, repr=False)

    @property
    def line(self) -> tuple:
        return (self.user_key, self.project_id, self.attachment_id)

    def view(self) -> dict:
        """The ask as it stands, for a tab that opens now. Under its lock."""
        return {
            "askId": self.ask_id,
            "by": self.by,
            "message": self.message,
            "state": self.state,
            "askedAt": self.asked_at,
            "startedAt": self.started_at,
            "seq": self.seq,
            "text": self.text,
            "events": [dict(event) for event in self.kept],
        }


@dataclass(eq=False)
class _Line:
    """An attachment's asks: the one whose turn runs, and those waiting, in order."""

    running: Optional[Ask] = None
    waiting: deque = field(default_factory=deque)


_lock = threading.Lock()
_lines: dict[tuple, _Line] = {}
#: Every ask by its id, until it has been over for :data:`ENDED_KEPT_S`.
_asks: dict[str, Ask] = {}


# ---------------------------------------------------------------------------
# Asking
# ---------------------------------------------------------------------------

def ask(user_key: str, project_id: str, attachment_id: str, message: str, config,
        run_context: Optional[str] = None, *, ask_id: Optional[str] = None, streaming: bool = True,
        follow: bool = False) -> tuple[Ask, Optional[Iterator[dict]]]:
    """Ask *message* of the agent of *attachment_id* on *project_id*, kept in
    *user_key*'s store, for the request's account: checked now (404, 422),
    then run as a job at once, or once the asks before it on the attachment
    are done. *ask_id*, chosen by the tab that asks, names the ask; an ask
    asked again by its id is the same ask. *streaming*: the reply streams as
    the model writes it, else it arrives whole with the turn's end. With
    *follow*, also the ask's events as they come, from before it can start,
    so none is missed. Returns the ask, and its events or None."""
    _sweep()
    if ask_id is not None and not (isinstance(ask_id, str) and _ASK_ID.fullmatch(ask_id)):
        raise AgentServiceError("'askId' must be 32 hexadecimal characters", 400)
    from flask import current_app

    new = Ask(
        ask_id=ask_id or uuid.uuid4().hex, user_key=user_key, project_id=project_id,
        attachment_id=attachment_id, message=message, context=run_context, config=config,
        streaming=streaming, by=agents_askers.writer(), who=agents_room.asker(),
        asking=agents_askers.asking(), app=current_app._get_current_object(),
    )
    with _lock:
        known = _asks.get(new.ask_id)
        if known is None:
            _asks[new.ask_id] = new
    if known is not None:
        if known.line != new.line or not _same_asker(known.who, new.who):
            raise AgentServiceError("another ask has this id", 409)
        return known, _followed(known) if follow else None
    try:
        agents_prepare.check_runnable(user_key, project_id, attachment_id)
    except Exception:
        with _lock:
            _asks.pop(new.ask_id, None)
        raise
    events = _followed(new) if follow else None
    # Its asked is its first event: a turn before it that ends meanwhile
    # starts it only once this is told (``_start`` takes the ask's lock).
    with new.lock:
        with _lock:
            line = _lines.setdefault(new.line, _Line())
            starts = line.running is None
            if starts:
                line.running = new
            else:
                line.waiting.append(new)
        _publish(new, ASKED, {"by": new.by, "message": message, "askedAt": new.asked_at, "waiting": not starts})
    if starts:
        _start(new)
    return new, events


def ask_at_once(user_key: str, project_id: str, attachment_id: str, message: str, config,
                run_context: Optional[str] = None, *, ask_id: Optional[str] = None) -> dict:
    """Ask a turn whose reply streams (:func:`ask`), answered at once: its
    id, its attachment's, and whether its turn runs or waits. Its events
    reach the room."""
    asked, _events = ask(user_key, project_id, attachment_id, message, config, run_context, ask_id=ask_id)
    with asked.lock:
        return {"askId": asked.ask_id, "attachmentId": asked.attachment_id, "state": asked.state}


def settled(asked: Ask, events: Iterator[dict]) -> dict:
    """What a blocking ask answers once its turn ended, *events* its events:
    what the turn settled with, or its failure as an error with its status.
    It waits for the turn's thread too, so nothing of the turn runs after."""
    for _envelope in events:
        pass
    _join(asked)
    if asked.interruption is not None:
        raise asked.interruption
    if asked.result is not None:
        return asked.result
    message, status = asked.failure or ("agent run failed", 502)
    raise AgentServiceError(message, status)


def own_events(asked: Ask, events: Iterator[dict]) -> Iterator[tuple[str, dict]]:
    """The events of *asked*'s turn alone, ``(name, data)`` as its stream
    has always said them, from its execution handshake to its done: for the
    tab whose request asked and follows the answer. A withdrawn ask ends in
    an error. Waits for the turn's thread, as :func:`settled` does; leaving
    early only stops following."""
    try:
        for envelope in events:
            name = envelope["event"]
            if name in (ASKED, STARTED):
                continue
            if name == WITHDRAWN:
                yield "error", {"error": "the ask was withdrawn before its turn"}
                continue
            yield name, envelope["data"]
    finally:
        close = getattr(events, "close", None)
        if close is not None:
            close()
    _join(asked)


# ---------------------------------------------------------------------------
# Following, stopping and withdrawing
# ---------------------------------------------------------------------------

def asks_of(user_key: str, project_id: str, attachment_id: str) -> list[dict]:
    """The attachment's asks as they stand, its running turn's first, then
    those waiting in order, for a tab that opens now (:meth:`Ask.view`)."""
    with _lock:
        line = _lines.get((user_key, project_id, attachment_id))
        asks = ([line.running] if line is not None and line.running is not None else []) + (
            list(line.waiting) if line is not None else []
        )
    views = []
    for each in asks:
        with each.lock:
            if each.state != ENDED:
                views.append(each.view())
    return views


def follow(user_key: str, project_id: str, attachment_id: str, ask_id: str) -> Iterator[dict]:
    """The ask *ask_id* as it stands, one ``snapshot`` envelope whose data is
    its view, then each of its events as it comes, until it ends: how a tab
    no room holds follows an ask. 404 for an ask the attachment does not
    have."""
    found = _find(user_key, project_id, attachment_id, ask_id)
    followed: queue.Queue = queue.Queue()
    with found.lock:
        first = {**_addressed(found), "seq": found.seq, "event": "snapshot", "data": found.view()}
        over = found.state == ENDED
        if not over:
            found.followers.append(followed)
    return _ended(found, _drained(found, followed, first=first, over=over))


def _ended(asked: Ask, events: Iterator[dict]) -> Iterator[dict]:
    """*events* of *asked*, then a wait for its turn's thread, so nothing of
    the turn runs after the last of them is read."""
    yield from events
    _join(asked)


def _join(asked: Ask) -> None:
    """Wait, a while at most, for *asked*'s turn's thread to be over."""
    thread = getattr(asked.job, "thread", None)
    if thread is not None and thread is not threading.current_thread():
        thread.join(_JOIN_S)


def stop(user_key: str, project_id: str, attachment_id: str, ask_id: str) -> dict:
    """Stop the running turn of *ask_id*, as the request's account: whoever
    asked it, the owner or an editor, since the agents' routes admit no one
    else. It stops at its next step, and its end says who stopped it.
    Refused for an ask whose turn is not running (409): a waiting ask is
    withdrawn by whoever asked it."""
    found = _find(user_key, project_id, attachment_id, ask_id)
    with found.lock:
        running = found.state == RUNNING
    if not running:
        raise AgentServiceError("only a running turn can be stopped", 409)
    found.stop.ask(agents_askers.writer())
    return {"askId": ask_id, "attachmentId": attachment_id, "stopping": True}


def withdraw(user_key: str, project_id: str, attachment_id: str, ask_id: str) -> dict:
    """Withdraw the waiting ask *ask_id*, for whoever asked it alone (403 for
    anyone else): its turn never runs, and the chat keeps nothing of it.
    Refused once its turn started (409)."""
    found = _find(user_key, project_id, attachment_id, ask_id)
    if not _same_asker(found.who, agents_room.asker()):
        raise AgentServiceError("only whoever asked can withdraw an ask", 403)
    with _lock:
        line = _lines.get(found.line)
        waiting = line is not None and found in line.waiting
        if waiting:
            line.waiting.remove(found)
    if not waiting:
        raise AgentServiceError("the ask is no longer waiting: its turn started", 409)
    _publish(found, WITHDRAWN, {"by": agents_askers.writer()})
    return {"askId": ask_id, "attachmentId": attachment_id, "withdrawn": True}


def stop_all() -> list:
    """End every ask, as a reset between tests does: the scripted model's
    holds released, every waiting ask withdrawn, so no turn starts after,
    and every running turn stopped. The running turns' jobs, for the reset
    to wait for."""
    testing_provider.release_holds()
    with _lock:
        waiting = [each for line in _lines.values() for each in line.waiting]
        for line in _lines.values():
            line.waiting.clear()
        running = [line.running for line in _lines.values() if line.running is not None]
    for each in waiting:
        _publish(each, WITHDRAWN, {"by": None})
    for each in running:
        each.stop.ask(None)
    return [each.job for each in running if each.job is not None]


def forget_all() -> None:
    """Test seam: forget every ask and line; their turns' threads are the
    caller's to stop and wait for first (:func:`stop_all`)."""
    with _lock:
        _lines.clear()
        _asks.clear()


# ---------------------------------------------------------------------------
# The turn's job
# ---------------------------------------------------------------------------

def _start(asked: Ask) -> None:
    """Run *asked*'s turn as a job, now its line's turn is free; the next ask
    waiting starts once the job is over (:func:`_after`)."""
    _publish(asked, STARTED, {"startedAt": time.time()})
    try:
        asked.job = agent_jobs.start_turn(
            user_key=asked.user_key, project_id=asked.project_id, attachment_id=asked.attachment_id,
            job_id=asked.ask_id, events=_turn(asked), app_context=asked.app.app_context,
            redact_values=_secrets(asked), on_finish=lambda _job: _after(asked),
        )
    except agent_jobs.JobRefused as exc:
        # A turn of the attachment no line holds is still live: this ask
        # ends, and the line moves on.
        _publish(asked, "error", {"error": str(exc)}, status=exc.status)
        _after(asked)


def _after(asked: Ask) -> None:
    """*asked*'s turn is over: the next ask waiting on its line starts."""
    with _lock:
        line = _lines.get(asked.line)
        if line is None or line.running is not asked:
            return
        following = line.waiting.popleft() if line.waiting else None
        line.running = following
        if following is None:
            del _lines[asked.line]
    if following is not None:
        _start(following)


def _turn(asked: Ask) -> Iterator[tuple]:
    """*asked*'s turn, on its job's thread, in the request that asked taken
    on again: prepared now, so it reads the conversation as the turns before
    it left it, and each of its events told as it comes. It always ends: a
    failure is its error."""
    try:
        with agents_askers.as_asked(asked.asking):
            yield from _turn_events(asked)
    except Exception as exc:  # noqa: BLE001 - a turn's failure is its end, never its line's
        secrets = _secrets(asked)
        log.error("turn %s of attachment %s failed:\n%s", asked.ask_id, asked.attachment_id,
                  redact(traceback.format_exc(), secrets))
        text = redact(f"agent run failed: {provider_config.redact_error(exc, asked.config)}", secrets)
        yield "error", _publish(asked, "error", {"error": text}, status=502)
    except GeneratorExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - an interruption, not a failure: whoever waits gets it
        asked.interruption = exc
        yield "error", _publish(asked, "error", {"error": "agent run failed: the turn was interrupted"}, status=502)
    finally:
        with asked.lock:
            over = asked.state == ENDED
        if not over:
            _publish(asked, "error", {"error": "agent run failed: the turn ended early"}, status=502)


def _turn_events(asked: Ask) -> Iterator[tuple]:
    try:
        turn = turn_loop.AttachmentTurn(
            asked.user_key, asked.project_id, asked.attachment_id, asked.message, asked.config,
            asked.context, streaming=asked.streaming, stop=asked.stop,
        )
    except AgentServiceError as exc:
        yield "error", _publish(asked, "error", {"error": str(exc)}, status=exc.status)
        return
    for name, payload in turn.stream():
        if name == "done":
            asked.result = turn.result
        data = {"text": payload} if name == "delta" else {"error": payload} if name == "error" else payload
        yield name, _publish(asked, name, data, status=502 if name == "error" else None)


# ---------------------------------------------------------------------------
# Telling an ask's events
# ---------------------------------------------------------------------------

def _publish(asked: Ask, name: str, data, *, status: Optional[int] = None) -> Optional[dict]:
    """Tell event *name* with *data* of *asked*: to its followers and to the
    tabs in its room that edit the dataflow, in the order of its events, and
    keep what a tab that opens later reads of it. An ask says nothing after
    its end. Its envelope, or None."""
    with asked.lock:
        if asked.state == ENDED:
            return None
        asked.seq += 1
        envelope = {**_addressed(asked), "seq": asked.seq, "event": name, "data": data}
        _keep(asked, envelope, status)
        for followed in list(asked.followers):
            followed.put(envelope)
        try:
            roles.tell_editors(asked.project_id, EVENT, envelope, app=asked.app)
        except Exception:  # noqa: BLE001 - the room missing an event never fails the turn
            log.exception("the room of %s could not be told turn %s's %s", asked.project_id, asked.ask_id, name)
    return envelope


def _keep(asked: Ask, envelope: dict, status: Optional[int]) -> None:
    """What *envelope* changes of *asked* as a later tab reads it."""
    name, data = envelope["event"], envelope["data"]
    kept = {"seq": envelope["seq"], "event": name, "data": data}
    if name == STARTED:
        asked.state, asked.started_at = RUNNING, data.get("startedAt")
    elif name == "delta":
        asked.text += data.get("text") or ""
    elif name == "usage":
        asked.kept = [event for event in asked.kept if event["event"] != "usage"] + [kept]
    elif name != ASKED:
        if name == "execution":
            asked.execution_id = data.get("executionId")
        asked.kept.append(kept)
    if name in ENDINGS or name == WITHDRAWN:
        asked.state, asked.ended_at = ENDED, time.time()
        if name == "error":
            asked.failure = (data.get("error"), status or 502)
        elif name == WITHDRAWN:
            asked.failure = ("the ask was withdrawn before its turn", 409)


def _secrets(asked: Ask) -> dict:
    """What no event or log line of *asked*'s turn may carry: the model's key
    and the asker's sign-in token."""
    return {name: value for name, value in (
        ("llm-api-key", getattr(asked.config, "api_key", None)), ("session", asked.asking.token),
    ) if value}


def _addressed(asked: Ask) -> dict:
    return {"projectId": asked.project_id, "attachmentId": asked.attachment_id, "askId": asked.ask_id}


def _followed(asked: Ask) -> Iterator[dict]:
    """*asked*'s events from now on, as they come, until it ends."""
    followed: queue.Queue = queue.Queue()
    with asked.lock:
        over = asked.state == ENDED
        if not over:
            asked.followers.append(followed)
    return _drained(asked, followed, over=over)


def _drained(asked: Ask, followed: queue.Queue, *, first: Optional[dict] = None,
             over: bool = False) -> Iterator[dict]:
    try:
        if first is not None:
            yield first
        while not over:
            envelope = followed.get()
            yield envelope
            over = envelope["event"] in ENDINGS or envelope["event"] == WITHDRAWN
    finally:
        with asked.lock:
            if followed in asked.followers:
                asked.followers.remove(followed)


# ---------------------------------------------------------------------------
# Finding asks
# ---------------------------------------------------------------------------

def _find(user_key: str, project_id: str, attachment_id: str, ask_id: str) -> Ask:
    with _lock:
        found = _asks.get(ask_id)
    if found is None or found.line != (user_key, project_id, attachment_id):
        raise AgentServiceError("no such ask for this attachment", 404)
    return found


def _same_asker(asked: agents_room.Asker, now: agents_room.Asker) -> bool:
    """Whether *now* is who asked as *asked*: their account, and on the guest
    account, which every guest signs in to, their sign-in."""
    account = (asked.asked_by or {}).get("account")
    return account is not None and account == (now.asked_by or {}).get("account") and asked.sign_in == now.sign_in


def _sweep(now: Optional[float] = None) -> None:
    """Forget the asks over for longer than :data:`ENDED_KEPT_S`."""
    now = time.time() if now is None else now
    with _lock:
        for ask_id in [ask_id for ask_id, each in _asks.items()
                       if each.ended_at is not None and now - each.ended_at > ENDED_KEPT_S]:
            del _asks[ask_id]
