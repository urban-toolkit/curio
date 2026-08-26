"""Unit tests for ``attachments.prune_orphaned_attachments`` — drop attachments
whose target node/edge was deleted, keep canvas and still-valid targets."""

from utk_curio.backend.app.agents.attachments import prune_orphaned_attachments


def _att(att_id, target):
    return {"attachmentId": att_id, "coord": "agent.x@1.0.0", "target": target, "revision": 1}


def _spec(nodes, edges, attachments):
    return {
        "dataflow": {
            "nodes": [{"id": n} for n in nodes],
            "edges": [{"id": e} for e in edges],
            "agentAttachments": attachments,
        }
    }


def test_prunes_node_and_connection_targets_that_are_gone():
    spec = _spec(
        nodes=["n1"],
        edges=["e1"],
        attachments=[
            _att("keep-canvas", {"kind": "canvas"}),
            _att("keep-node", {"kind": "node", "targetId": "n1"}),
            _att("drop-node", {"kind": "node", "targetId": "n-gone"}),
            _att("keep-edge", {"kind": "connection", "targetId": "e1"}),
            _att("drop-edge", {"kind": "connection", "targetId": "e-gone"}),
        ],
    )
    removed = prune_orphaned_attachments(spec)
    assert {r["attachmentId"] for r in removed} == {"drop-node", "drop-edge"}
    kept = [a["attachmentId"] for a in spec["dataflow"]["agentAttachments"]]
    assert kept == ["keep-canvas", "keep-node", "keep-edge"]


def test_noop_when_all_targets_valid():
    spec = _spec(["n1"], [], [_att("a", {"kind": "node", "targetId": "n1"}), _att("b", {"kind": "canvas"})])
    assert prune_orphaned_attachments(spec) == []
    assert len(spec["dataflow"]["agentAttachments"]) == 2


def test_leaves_malformed_records_untouched():
    spec = _spec(["n1"], [], [_att("weird", {"kind": "mystery"}), _att("noTarget", "nope")])
    assert prune_orphaned_attachments(spec) == []
    assert len(spec["dataflow"]["agentAttachments"]) == 2


def test_noop_on_empty_or_missing():
    assert prune_orphaned_attachments({"dataflow": {"nodes": [], "edges": []}}) == []
    assert prune_orphaned_attachments({}) == []
    assert prune_orphaned_attachments(None) == []
