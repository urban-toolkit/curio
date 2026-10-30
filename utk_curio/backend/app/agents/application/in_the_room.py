"""An agent's runs in its dataflow's room: who asked, joining, and what a write holds.

Every run of an agent on a dataflow is in the dataflow's room as its agent
(``collaboration/agent_peers.py``): a chat turn, a delegate's run, a Solve of
one node or of a plan, and Build & validate's steps. Each joins as the agent of
its attachment, named after its manifest, with who asked and the skills its
run holds, and leaves before its reply ends. A run nested in another of the
same attachment shares its peer.

Each write of a node's code, spec, widgets or settings is held by the agent the
change is by, its attachment's (``changes.land``): it waits for anyone else in
the node, takes the node's lock, names the node in its ``editing`` and what it
writes in ``writes``, writes, and keeps them a second while a tab is bound.

Who asked is read in the request that asked (:func:`asker`), since a job's
thread holds no request and reads no account row: their account and name, as
the room names them, and on the guest account, which every guest signs in to,
their sign-in, which tells their own locks from another guest's.
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, Optional

from utk_curio.backend.app.agents.application import askers as agents_askers
from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.collaboration import agent_peers
from utk_curio.backend.app.execution import workflow_spec


@dataclass(frozen=True)
class Asker:
    """Who asked a run, as its agent in the room names them."""

    #: ``{account, name}``: the agent's ``askedBy`` (``agent_peers.asker``).
    asked_by: dict = field(default_factory=lambda: {"account": None, "name": None})
    #: On the guest account, the sign-in that asked; None for any other
    #: account, whose own locks are theirs by account.
    sign_in: Optional[str] = None


def asker(user=None, *, sign_in: Optional[str] = None) -> Asker:
    """Who asked: *user*, else the request's account, with the request's
    sign-in (*sign_in*, else read now) when the account is the guest
    account's. Read in the request, before a job's thread takes over."""
    user = user if user is not None else agents_askers.person()
    if user is None or getattr(user, "id", None) is None:
        return Asker()
    signed = sign_in if sign_in is not None else agents_askers.sign_in()
    return Asker(agent_peers.asker(user), signed if getattr(user, "is_guest", False) else None)


def asker_of(loop_ctx: Optional[dict]) -> Asker:
    """Who asked the run *loop_ctx* is of: the asker a job took when it
    started (``room_asker``), else the request's."""
    taken = (loop_ctx or {}).get("room_asker")
    return taken if isinstance(taken, Asker) else asker()


@contextmanager
def at_work(user_key: str, project_id: Optional[str], attachment_id: Optional[str], *,
            spec: Optional[dict] = None, coord: Optional[str] = None, manifest=None,
            who: Optional[Asker] = None, skills=()) -> Iterator[Optional[agent_peers.Peer]]:
    """The agent of *attachment_id* at work in *project_id*'s room for the
    block (``agent_peers.at_work``): it joins, or shares the peer a run of it
    already has there. It is named after its manifest (*manifest*, else the
    one *coord* names, else the coord of the attachment in *spec*), asked by
    *who* (else the request's asker), and holds *skills*. ``None`` when there
    is no attachment to name it by."""
    if not project_id or not attachment_id:
        yield None
        return
    peer = agent_peers.peer_of(project_id, attachment_id)
    if peer is not None:
        agent = peer.user["agent"]
        named = {"coord": agent["coord"], "name": peer.name, "category": agent["category"],
                 "asked_by": agent["askedBy"], "asker_sign_in": peer.asker_sign_in}
    else:
        if coord is None:
            record = attachments.get_attachment(spec, attachment_id) if spec else None
            coord = str((record or {}).get("coord") or "")
        if manifest is None:
            manifest = agents_spec_reads._definition(user_key, coord)
        who = who if who is not None else asker()
        named = {"coord": coord, "name": getattr(manifest, "name", None) or coord or "An agent",
                 "category": getattr(manifest, "category", None) or None,
                 "asked_by": who.asked_by, "asker_sign_in": who.sign_in}
    with agent_peers.at_work(user_key, project_id, attachment_id=str(attachment_id), skills=skills,
                             **named) as joined:
        yield joined


def held_skills(run_skills) -> list[str]:
    """The skills a run holds in its system turn (``skill_runs.RunSkills``):
    those it is handed, those it kept from earlier turns, those its message
    named."""
    if run_skills is None:
        return []
    return [skill.name for skill in (*run_skills.handed, *run_skills.kept, *run_skills.named)]


def uses_skills(project_id: Optional[str], attachment_id: Optional[str], names) -> None:
    """The agent of *attachment_id* at work in the room holds or loaded the
    skills *names*: its peer lists them."""
    peer = agent_peers.peer_of(project_id, attachment_id) if project_id and attachment_id else None
    if peer is not None and names:
        peer.use_skills(names)


def content_writes(spec: Optional[dict], node_id) -> str:
    """What a write of *node_id*'s content writes, as an agent's lock and
    state name it: ``spec`` for a document's (a grammar node), else
    ``code``."""
    node = next((n for n in ((spec or {}).get("dataflow") or {}).get("nodes") or []
                 if isinstance(n, dict) and n.get("id") == node_id), None)
    kind = workflow_spec.content_kind(str((node or {}).get("type") or ""))
    return "spec" if kind == workflow_spec.CONTENT_KIND_GRAMMAR else "code"


def settings_writes(settings: Optional[dict]) -> str:
    """What a change of a node's settings writes: ``widgets`` when it gives
    widgets values, which the node's Widgets tab shows, else ``settings``."""
    return "widgets" if isinstance(settings, dict) and "widgets" in settings else "settings"


def writing(peer: agent_peers.Peer, hold: agent_peers.Holding) -> dict:
    """What the agent wrote, as its state in the room named it while it wrote
    (``user``, ``editing``, ``writes``): a run's ``change`` event carries it,
    so a canvas no doc binds shows it as the room's tabs did."""
    return {"user": copy.deepcopy(peer.user), "editing": copy.deepcopy(hold.node), "writes": hold.writes}
