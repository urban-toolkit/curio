"""An agent's change to the dataflow: made at once, as a person's edit is, and undone by kind.

A mutate tool that changes the dataflow lands as soon as its checks pass:
``node.content.write``, ``node.settings.write``, ``node.create`` and
``dataflow.plan.write``, and the runtime's own writes of them (a delegated
node's code, notes, a validated node's code). Each lands through the
dataflow's doc (``dataflow_docs.write``), the agent the origin of its
transaction, so every tab bound to the doc gets it at once and the history
records it as the agent's (``collaboration/history.py``: "Node Builder, asked by
Ana"). A node's code or settings and a new node are one write; a plan is one
write a step, each under the change's id (``plans._land_dataflow_plan``). A new
node is dragged in from its template's tile as a person drags it, and lands as
the drop ends, the agent's one action then (``in_the_room.act``). A tab no doc
binds takes the change from the run's stream (:func:`take_landed`), playing
its drags first.
Before a change lands on nodes a person holds (their focus in the node,
``room_state``'s soft lock), it waits for them, up to :data:`LOCK_WAIT_S`: for
anyone but the person who asked (``agent_peers.wait_for_people``). A node's
code, spec, widgets or settings land held by the agent the change is by, in the
dataflow's room (``in_the_room``): it takes the node's lock, names the node in
its state, writes, and keeps both a second while a tab is bound, so every tab
shows the node's code as it lands. Its ``change`` event says what the agent's
state said (``writing``), for a tab no doc binds.

The attachment keeps its changes (``changes``, the last :data:`CHANGES_KEPT`),
each with what its Undo needs, and the turn carries each one's card (a part of
type ``change``). Undo (:func:`undo`) is a person's change, by kind, through the
history's checked writes:

* a node's code gets its before back, only while the node holds the agent's
  code (``history.write_code``);
* a new node goes, with its connections, only while it holds what the agent
  gave it;
* settings get their old values back, as a new point, only while they hold
  what the agent set;
* a plan puts back the version before its first write (``history.put_back``),
  only while nobody changed the dataflow between its writes and nothing
  outside its own nodes changed since: so a node it removed comes back with
  its connections.

Refused, nothing changes, and the answer says who changed it.
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
import uuid

from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.application import in_the_room as agents_room
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application.proposals import apply as agents_apply
from utk_curio.backend.app.agents.application.proposals import plans as agents_plans
from utk_curio.backend.app.agents.domain import agent_text
from utk_curio.backend.app.agents.domain import node_settings
from utk_curio.backend.app.agents.domain import widget_grammar
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.collaboration import agent_peers
from utk_curio.backend.app.collaboration import dataflow_docs
from utk_curio.backend.app.collaboration import history
from utk_curio.backend.app.execution.code_references import normalize_widgets
from utk_curio.common import shared_constants

#: The kinds of change, by the tool that makes each.
CONTENT, SETTINGS, NODE, PLAN = "content", "settings", "node", "plan"
KIND_OF_TOOL = {
    "node.content.write": CONTENT,
    "node.settings.write": SETTINGS,
    "node.create": NODE,
    "dataflow.plan.write": PLAN,
}
#: The tools whose work lands as the agent's change, as
#: ``src/contracts/agentChanges.json`` names them, which the review card reads
#: too: a review of one saved before agents changed the dataflow directly can
#: no longer be applied (``apply.apply_proposal``), only dismissed.
CHANGE_TOOLS = frozenset(shared_constants.read("agentChanges")["tools"])
#: The status a landed change has, and the one its Undo gives it.
APPLIED, UNDONE = "applied", "undone"
#: The tool status a landed change answers the model with.
LANDED = "applied"
#: How many of its changes an attachment keeps, newest last.
CHANGES_KEPT = 50
#: Seconds an agent's change waits while a person holds a node it changes.
LOCK_WAIT_S = 30.0
_LOCK_POLL_S = 0.25


# ── waiting on a person ──────────────────────────────────────────────────────

def wait_for_people(project_id: str, node_ids: list, asker=None, *, sign_in: str | None = None,
                    peer: agent_peers.Peer | None = None) -> str | None:
    """Wait while someone other than *asker*, the account that asked, holds
    one of *node_ids*, as one person waits for another to leave a node, up to
    :data:`LOCK_WAIT_S`: the name of who still holds one then, or None. A run
    outside a request (a job's thread) names its asker; a request's is its
    user. On the guest account, *sign_in* is the sign-in that asked: another
    guest's lock holds the agent back. *peer*, the agent at work, never holds
    itself back; another agent's lock holds it (``agent_peers.wait_for_people``)."""
    if asker is None:
        asker = getattr(agents_spec_reads._acting_user(), "id", None)
    return agent_peers.wait_for_people(
        project_id, node_ids, asker, asker_sign_in=sign_in, peer=peer,
        within=LOCK_WAIT_S, poll=_LOCK_POLL_S, clock=time.monotonic, sleep=time.sleep,
    )


# ── landing ──────────────────────────────────────────────────────────────────

def land(user_key: str, project_id: str, loop_ctx: dict, spec: dict, proposal: dict, part: dict):
    """Land the change *proposal* holds, which its mint checked against
    *spec*, the dataflow it read; *part* is what its card shows. Waits first
    while a person holds a node it changes. A node's content or settings land
    held by the change's agent in the room (:func:`_land_held`); a new node
    and a plan land as that agent's actions, one at a time, each new node
    dragged in (:func:`_land_played`). Returns the tool's ``(status, text
    for the model, the change's card)``: :data:`LANDED`, or ``refused`` with
    no card when nothing changed."""
    kind = KIND_OF_TOOL[proposal["tool"]]
    if kind == CONTENT:
        return _land_held(user_key, project_id, loop_ctx, spec, proposal, part, agents_apply.land_content)
    if kind == SETTINGS:
        return _land_held(user_key, project_id, loop_ctx, spec, proposal, part, agents_apply.land_settings)
    lander = agents_apply.land_node if kind == NODE else agents_plans._land_dataflow_plan
    return _land_played(user_key, project_id, loop_ctx, spec, proposal, part, lander)


def _land_played(user_key: str, project_id: str, loop_ctx: dict, spec: dict, proposal: dict, part: dict, lander):
    """Land a new node or a plan as the agent the change is by, at work in
    the room (joined for the landing, or the run's own): after anyone else in
    a node it removes, its actions one at a time (``in_the_room.act``)."""
    who = agents_room.asker_of(loop_ctx)
    with agents_room.at_work(user_key, project_id, loop_ctx.get("attachment_id"), spec=spec, who=who) as peer:
        held = wait_for_people(project_id, _nodes_it_changes(proposal), loop_ctx.get("asker_id"),
                               sign_in=who.sign_in, peer=peer)
        if held:
            return "refused", agent_text.message("change.person-editing", name=held), None
        return lander(user_key, project_id, loop_ctx, spec, proposal, part, peer=peer)


def _land_held(user_key: str, project_id: str, loop_ctx: dict, spec: dict, proposal: dict, part: dict, lander):
    """Land a node's content or settings as the agent the change is by, the
    agent of its attachment, at work in the room (joined for the write, or
    the run's own): after anyone else in the node, it takes the node's lock,
    names the node in its state, writes, and keeps both a second while a tab
    is bound. Each ``change`` event of the write carries what its state said
    (``writing``)."""
    nodes = _nodes_it_changes(proposal)
    who = agents_room.asker_of(loop_ctx)
    with agents_room.at_work(user_key, project_id, loop_ctx.get("attachment_id"), spec=spec, who=who) as peer:
        held = wait_for_people(project_id, nodes, loop_ctx.get("asker_id"), sign_in=who.sign_in, peer=peer)
        if held:
            return "refused", agent_text.message("change.person-editing", name=held), None
        if peer is None:
            return lander(user_key, project_id, loop_ctx, spec, proposal, part)
        writes = (agents_room.content_writes(spec, proposal["nodeId"]) if proposal["tool"] == "node.content.write"
                  else agents_room.settings_writes(proposal.get("settings")))
        # The wait is done: the lock now, or the name of who took it meanwhile.
        with agent_peers.holding(peer, nodes, writes, within=0) as hold:
            if hold.held_by is not None:
                return "refused", agent_text.message("change.person-editing", name=hold.held_by), None
            before = len(loop_ctx.get("_landed") or [])
            outcome = lander(user_key, project_id, loop_ctx, spec, proposal, part)
            if outcome[0] != LANDED:
                hold.keep = False  # nothing landed: nothing to show a second
                return outcome
            hold.did = tuple(("changed", "node", node_id) for node_id in nodes)
            writing = agents_room.writing(peer, hold)
            for entry in (loop_ctx.get("_landed") or [])[before:]:
                entry["writing"] = writing
            return outcome


def _nodes_it_changes(proposal: dict) -> list:
    """The nodes already on the canvas a change changes: the one whose code
    or settings it writes, the ones a plan removes."""
    if proposal["tool"] in ("node.content.write", "node.settings.write"):
        return [proposal["nodeId"]]
    if proposal["tool"] == "dataflow.plan.write":
        return list((proposal.get("plan") or {}).get("removeNodes") or [])
    return []


def new_change(tool: str, summary: str, **fields) -> dict:
    """A change record of *tool*, applied, with a new id and *fields*."""
    return {"changeId": uuid.uuid4().hex, "tool": tool, "kind": KIND_OF_TOOL[tool],
            "summary": summary, "status": APPLIED, **fields}


def keep(spec: dict, attachment_id: str | None, change: dict) -> None:
    """Keep *change* on the attachment that made it, in *spec*, which the
    change's own write writes. A change kept already, such as a plan landing
    a step at a time, is kept as it is now, where it was."""
    record = attachments.get_attachment(spec, attachment_id) if attachment_id else None
    if record is None:
        return
    kept = [c for c in record.get("changes") or [] if isinstance(c, dict)]
    at = next((i for i, c in enumerate(kept) if c.get("changeId") == change["changeId"]), None)
    if at is None:
        kept.append(copy.deepcopy(change))
    else:
        kept[at] = copy.deepcopy(change)
    record["changes"] = kept[-CHANGES_KEPT:]


def forget(spec: dict, attachment_id: str | None, change_id: str) -> None:
    """Take the change *change_id* off its attachment, in *spec*: its write
    was refused, so nothing of it is the dataflow's."""
    record = attachments.get_attachment(spec, attachment_id) if attachment_id else None
    if record is not None and isinstance(record.get("changes"), list):
        record["changes"] = [c for c in record["changes"] if not (isinstance(c, dict) and c.get("changeId") == change_id)]


def actor(user_key: str, spec: dict, loop_ctx: dict, what: str) -> dataflow_docs.Actor:
    """Who a change is by: the agent of the attachment that made it, asked
    by the account that asked it (``spec_reads._agent_actor``): on a job's
    thread, the person the job took when it started (``loop_ctx["asker"]``)."""
    return agents_spec_reads._agent_actor(user_key, spec, loop_ctx.get("attachment_id"), what,
                                          loop_ctx.get("asker"))


def card(part: dict, change: dict, lines: list[str]) -> dict:
    """The turn's card of *change*: what its mint showed (*part*: summary,
    preview, settings, plan, source, validation), as a change that landed."""
    out = {key: value for key, value in part.items() if key not in ("type", "proposalId", "pins", "status")}
    pins = part.get("pins") or {}
    # A new node's kind, and whether the sandbox can run it, which its card says.
    out.update({key: pins[key] for key in ("nodeType", "executable") if key in pins})
    out.update({"type": "change", "changeId": change["changeId"], "kind": change["kind"],
                "summary": change["summary"], "status": APPLIED, "lines": list(lines)})
    if change.get("nodeId"):
        out["nodeId"] = change["nodeId"]
    if change.get("planId"):
        # The plan's rows read its ledger, on the attachment, by this id.
        out["planId"] = change["planId"]
    return out


def landed(loop_ctx: dict, change: dict, canvas: dict | list, *, steps: list | None = None) -> None:
    """Note that *change* landed, for the run's stream: a tab no doc binds
    takes *canvas*, its canvas mutation, through its canvas bridge. *steps*,
    for a change played as the agent's actions, say how the room's tabs saw it
    land, in order: each step's canvas mutation, with ``dragged``, the drag
    played before it (``in_the_room.dragged``), when it had one; a tab no doc
    binds plays them in place of *canvas*."""
    entry = {
        "changeId": change["changeId"],
        "attachmentId": loop_ctx.get("attachment_id"),
        "tool": change["tool"],
        "canvas": canvas,
    }
    if steps:
        entry["steps"] = [{key: value for key, value in step.items() if value is not None} for step in steps]
    loop_ctx.setdefault("_landed", []).append(entry)


def take_landed(loop_ctx: dict) -> list[dict]:
    """The changes that landed since the last take, for the stream."""
    out = list(loop_ctx.get("_landed") or [])
    if out:
        loop_ctx["_landed"].clear()
    return out


def settings_basis(node: dict, change: dict) -> str:
    """The digest of what *change* touches on *node*, as the node reads it:
    its type, each setting the change names as the node does it
    (``node_settings.saved``) and each widget it gives a value to."""
    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    values = change.get("widgets") or {}
    touched = {
        "type": node.get("type"),
        "settings": {key: setting for key, setting in node_settings.saved(metadata).items() if key in change},
        "widgets": [widget for widget in normalize_widgets(metadata.get("widgets")) if widget["name"] in values],
    }
    return hashlib.sha256(json.dumps(touched, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def write_settings(node: dict, change: dict) -> None:
    """Write the settings *change* gives into the saved *node*: each setting
    as the node stores it once picked, and each widget's value."""
    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    node_settings.write(metadata, change)
    if "widgets" in change:
        metadata["widgets"] = widget_grammar.with_values(normalize_widgets(metadata.get("widgets")), change["widgets"])
    if metadata:
        node["metadata"] = metadata
    else:
        node.pop("metadata", None)


def settings_undone(node: dict, change: dict) -> list[dict]:
    """What puts back the settings *change* would change on *node*, read
    before it does: each setting it names back to its default, then to the
    node's own, and each widget it sets back to its value, as settings
    changes the canvas's setters take in turn. A setting's default is the
    change ``{}`` makes as its node's select picks it
    (``node_settings.parse_change``: a Data Pool's two modes at OVERWRITE,
    a join's defaults, a view's every image column), which the node's write
    takes too: a bare ``{}`` there keeps what the node holds."""
    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    saved = node_settings.saved(metadata)
    keys = [key for key in change if key != "widgets"]
    first, _problems = node_settings.parse_change({key: {} for key in keys}, "undo")
    if "widgets" in change:
        first["widgets"] = {
            widget["name"]: widget.get("value", widget.get("default"))
            for widget in normalize_widgets(metadata.get("widgets")) if widget["name"] in change["widgets"]
        }
    steps = [first] if first else []
    then = {key: copy.deepcopy(saved[key]) for key in keys if saved.get(key)}
    if then:
        steps.append(then)
    return steps


# ── undo ─────────────────────────────────────────────────────────────────────

def _by(user) -> dict:
    """*user* as the history names a person."""
    return {"kind": "person", "account": str(user.id), "name": getattr(user, "name", None) or getattr(user, "username", None)}


def _agent_name(user_key: str, record: dict) -> str:
    return agents_spec_reads._agent_name(user_key, str(record.get("coord") or "")) or "the agent"


def _node(spec: dict, node_id: str) -> dict | None:
    return next((n for n in (spec.get("dataflow") or {}).get("nodes") or []
                 if isinstance(n, dict) and n.get("id") == node_id), None)


def _refused(by: dict | None, what: str = "node") -> AgentServiceError:
    name = (by or {}).get("name") or "Someone"
    return AgentServiceError(f"{name} changed this {what} after; nothing was undone.", 409)


def _last_by(user_key: str, project_id: str, node_id: str) -> dict | None:
    """Who made the node *node_id*'s newest entry, as the history names them."""
    try:
        found = history.entries(user_key, project_id, node_id)["entries"]
    except Exception:  # noqa: BLE001 - a refusal names someone even with no history
        return None
    return (found[-1] or {}).get("by") if found else None


def undo(user_key: str, project_id: str, attachment_id: str, change_id: str, user) -> dict:
    """Undo the change *change_id* the attachment's agent made, as *user*'s
    own change, by its kind (the module's docstring). Answers the change's
    new status and the canvas mutations a tab no doc binds takes; refused
    with a 409 whose message names who changed what it changed."""
    spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    change = next((c for c in record.get("changes") or [] if isinstance(c, dict) and c.get("changeId") == change_id), None)
    if change is None:
        raise AgentServiceError(f"change {change_id!r} not found", 404)
    if change.get("status") != APPLIED:
        raise AgentServiceError("this change was undone already", 409)
    by = _by(user)
    label = f"Undid {_agent_name(user_key, record)}'s change"
    undo_kind = {CONTENT: _undo_content, NODE: _undo_node, SETTINGS: _undo_settings, PLAN: _undo_plan}[change["kind"]]
    canvas = undo_kind(user_key, project_id, attachment_id, change, by, label)
    fresh = agents_spec_reads._live_spec_or_404(user_key, project_id)
    fresh_record = agents_spec_reads._record_or_404(fresh, attachment_id)
    for kept in fresh_record.get("changes") or []:
        if isinstance(kept, dict) and kept.get("changeId") == change_id:
            kept["status"] = UNDONE
    dataflow_docs.write(user_key, project_id, fresh, agents_spec_reads._person(user_key, "undo"))
    if isinstance(fresh_record.get("sessionId"), str):
        sessions.update_change_status(user_key, project_id, fresh_record["sessionId"], change_id, UNDONE)
    return {"attachmentId": attachment_id, "changeId": change_id, "status": UNDONE, "canvas": canvas}


def _undo_content(user_key, project_id, attachment_id, change, by, label) -> list[dict]:
    try:
        history.write_code(user_key, project_id, by, change["nodeId"], expect=change["content"],
                           code=change["before"], label=label)
    except history.HistoryError as exc:
        raise AgentServiceError(str(exc), exc.status) from exc
    # The node's history in the tab names the entry as the server's does.
    return [{"kind": "node-content-applied", "nodeId": change["nodeId"], "content": change["before"], "agent": label}]


def _undo_node(user_key, project_id, attachment_id, change, by, label) -> list[dict]:
    spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
    dataflow = spec.setdefault("dataflow", {})
    gone = []
    for created in change.get("created") or []:
        node = _node(spec, created["id"])
        if node is None:
            continue
        if node.get("type") != created.get("type") or (node.get("content") or "") != (created.get("content") or ""):
            raise _refused(_last_by(user_key, project_id, created["id"]))
        gone.append(created["id"])
    if not gone:
        raise AgentServiceError("the node this change added is not on the canvas any more; nothing was undone.", 409)
    edges = [e for e in dataflow.get("edges") or [] if isinstance(e, dict)]
    removed_edges = [str(e.get("id")) for e in edges if e.get("source") in gone or e.get("target") in gone]
    dataflow["edges"] = [e for e in edges if str(e.get("id")) not in removed_edges]
    dataflow["nodes"] = [n for n in dataflow.get("nodes") or [] if not (isinstance(n, dict) and n.get("id") in gone)]
    pruned = attachments.prune_orphaned_attachments(spec)
    dataflow_docs.write(user_key, project_id, spec, agents_spec_reads._person(user_key, "undo"),
                        point={"kind": history.GRAPH, "what": label, "by": by})
    sessions.delete_sessions_of(user_key, project_id, pruned)
    return [{"kind": "plan-removals", "planId": f"undo:{change['changeId']}", "removedNodeIds": gone,
             "removedEdgeIds": removed_edges}]


def _undo_settings(user_key, project_id, attachment_id, change, by, label) -> list[dict]:
    spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
    node = _node(spec, change["nodeId"])
    if node is None:
        raise AgentServiceError("the node this change set is not on the canvas any more; nothing was undone.", 409)
    if settings_basis(node, change["settings"]) != change.get("basisAfter"):
        raise _refused(_last_by(user_key, project_id, change["nodeId"]))
    for step in change.get("undo") or []:
        write_settings(node, step)
    dataflow_docs.write(user_key, project_id, spec, agents_spec_reads._person(user_key, "undo"),
                        point={"kind": history.EDIT, "what": label, "by": by})
    return [{"kind": "node-settings-applied", "nodeId": change["nodeId"], "settings": step}
            for step in change.get("undo") or []]


def _undo_plan(user_key, project_id, attachment_id, change, by, label) -> list[dict]:
    return agents_plans._undo_plan(user_key, project_id, attachment_id, change, by)
