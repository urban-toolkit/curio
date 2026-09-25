"""What a client save may not do to a spec it has not seen (memo dev/124).

A project's spec has two kinds of writer that do not know about each other.
The canvas sends the whole document — React Flow's live nodes and edges,
serialised by ``TrillGenerator`` — and the backend writes the same file on its
own from an agent apply, from each wave of a verified Solve (``DEC-075``), from
a dataset or package install, and from the evaluation service. Neither carries
a basis, so the file is last-writer-wins, and a browser that loaded a project
before a background write erases it on its next save. That is not hypothetical:
it is how an evaluation run finished with a score and an empty canvas.

**The rule refuses loss, not divergence.** Refusing every save whose basis is
stale is the obvious design and the wrong one: a canvas is told about an
agent's apply through a live event without reloading, so its basis goes stale
while its content stays current, and a dataset install bumps the counter
without touching the graph at all. That rule would reject correct saves several
times an hour and teach people to dismiss the message. So:

    a save is refused when its basis is older than what is on disk AND the
    document it sends would drop a node or an edge that exists on disk, or
    blank the content of a node that has content on disk.

Both are things the client cannot have meant, because it never saw them: a node
it never received cannot be a node it deliberately deleted, and code Solve wrote
after the load cannot be code a person deliberately cleared. Moving nodes,
editing code, renaming, adding, and deleting a node the client *did* load all
pass untouched, whatever the basis says.

That is also why no revision has to be plumbed through every endpoint that
writes a spec: staleness alone never refuses, so the client only has to
remember what it last synced with — its load, and its own saves.

A caller that sends no basis is not checked, which is how every script, test
and internal caller keeps working unchanged.

Pure: values in, values out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class SaveWouldLoseWork(Exception):
    """This save would delete something the client never saw.

    Carries the counts so the caller can say what is at stake rather than
    "conflict"; ``str()`` is the sentence a person reads.
    """

    def __init__(self, message: str, *, nodes: int = 0, edges: int = 0, content: int = 0):
        super().__init__(message)
        self.message = message
        self.nodes = nodes
        self.edges = edges
        self.content = content


@dataclass(frozen=True)
class Loss:
    """What a save would delete. Falsy when it would delete nothing."""

    nodes: tuple = ()
    edges: tuple = ()
    content: tuple = ()

    def __bool__(self) -> bool:
        return bool(self.nodes or self.edges or self.content)

    def sentence(self) -> str:
        parts = []
        if self.nodes:
            parts.append(f"{len(self.nodes)} node" + ("s" if len(self.nodes) > 1 else ""))
        if self.edges:
            parts.append(
                f"{len(self.edges)} connection" + ("s" if len(self.edges) > 1 else "")
            )
        if self.content:
            parts.append(
                f"the code in {len(self.content)} node"
                + ("s" if len(self.content) > 1 else "")
            )
        if len(parts) > 1:
            listed = ", ".join(parts[:-1]) + " and " + parts[-1]
        else:
            listed = parts[0] if parts else "work"
        return (
            "This dataflow changed on the server since you opened it — saving "
            f"now would delete {listed} that your canvas does not have. Reload "
            "the project to see the current dataflow, then make your change "
            "again."
        )


def _graph(spec: Mapping) -> tuple:
    dataflow = (spec or {}).get("dataflow")
    if not isinstance(dataflow, Mapping):
        return {}, {}
    nodes = {
        str(n.get("id")): n
        for n in (dataflow.get("nodes") or [])
        if isinstance(n, Mapping) and n.get("id")
    }
    edges = {
        str(e.get("id")): e
        for e in (dataflow.get("edges") or [])
        if isinstance(e, Mapping) and e.get("id")
    }
    return nodes, edges


def loss_from_save(existing_spec: Mapping, incoming_spec: Mapping) -> Loss:
    """What *incoming_spec* would delete from *existing_spec*.

    Ids only for nodes and edges — a node that moved or whose code changed is
    an edit, not a loss. Content counts as lost only when it is **blanked**:
    replacing code with different code is what editing looks like, and only a
    client echoing a node it loaded before Solve filled it turns code into
    nothing.
    """
    have_nodes, have_edges = _graph(existing_spec)
    sent_nodes, sent_edges = _graph(incoming_spec)
    dropped_nodes = tuple(sorted(set(have_nodes) - set(sent_nodes)))
    dropped_edges = tuple(sorted(set(have_edges) - set(sent_edges)))
    blanked = tuple(sorted(
        node_id
        for node_id, node in have_nodes.items()
        if str(node.get("content") or "").strip()
        and node_id in sent_nodes
        and not str(sent_nodes[node_id].get("content") or "").strip()
    ))
    return Loss(nodes=dropped_nodes, edges=dropped_edges, content=blanked)


def assert_save_keeps_server_work(
    existing_spec: Mapping,
    incoming_spec: Mapping,
    *,
    base_revision: int | None,
    current_revision: int,
) -> None:
    """Raise :class:`SaveWouldLoseWork` when this save would delete something
    the client never saw.

    *base_revision* is the counter the client last synced with — ``None`` for a
    caller with no opinion, which is never checked. *current_revision* is the
    project's counter now.
    """
    if base_revision is None:
        return
    if int(base_revision) >= int(current_revision):
        return
    loss = loss_from_save(existing_spec, incoming_spec)
    if not loss:
        return
    raise SaveWouldLoseWork(
        loss.sentence(),
        nodes=len(loss.nodes), edges=len(loss.edges), content=len(loss.content),
    )
