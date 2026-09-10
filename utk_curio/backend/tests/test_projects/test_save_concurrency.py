"""dev/124 — the rule that decides whether a save would delete unseen work.

Every case here is a sentence from the memo: refuse loss, allow editing, and
never look at all unless the client offered a basis.
"""
from __future__ import annotations

import pytest

from utk_curio.backend.app.projects import concurrency


def _spec(nodes=(), edges=()):
    return {"dataflow": {"nodes": list(nodes), "edges": list(edges)}}


def _node(node_id, content=""):
    return {"id": node_id, "type": "curio.builtin/data-loading",
            "x": 0, "y": 0, "content": content}


def _edge(edge_id, source, target):
    return {"id": edge_id, "source": source, "target": target}


def _check(existing, incoming, *, base=1, current=2):
    concurrency.assert_save_keeps_server_work(
        existing, incoming, base_revision=base, current_revision=current
    )


class TestItRefusesLoss:
    def test_a_node_the_client_never_saw_is_not_a_node_it_deleted(self):
        existing = _spec([_node("a"), _node("b")])
        with pytest.raises(concurrency.SaveWouldLoseWork) as refusal:
            _check(existing, _spec())
        assert refusal.value.nodes == 2
        assert "2 nodes" in str(refusal.value)
        assert "Reload the project" in str(refusal.value)

    def test_a_dropped_edge_counts_too(self):
        existing = _spec([_node("a"), _node("b")], [_edge("e1", "a", "b")])
        with pytest.raises(concurrency.SaveWouldLoseWork) as refusal:
            _check(existing, _spec([_node("a"), _node("b")]))
        assert refusal.value.edges == 1
        assert "1 connection" in str(refusal.value)

    def test_blanking_code_solve_wrote_is_loss(self):
        """The second way the canvas erases a run: it keeps the node and sends
        back the empty content it loaded before Solve filled it."""
        existing = _spec([_node("a", content="import pandas as pd")])
        with pytest.raises(concurrency.SaveWouldLoseWork) as refusal:
            _check(existing, _spec([_node("a", content="")]))
        assert refusal.value.content == 1
        assert "the code in 1 node" in str(refusal.value)

    def test_the_sentence_names_everything_at_stake(self):
        existing = _spec(
            [_node("a", content="code"), _node("b"), _node("c")],
            [_edge("e1", "a", "b")],
        )
        with pytest.raises(concurrency.SaveWouldLoseWork) as refusal:
            _check(existing, _spec([_node("a", content="")]))
        message = str(refusal.value)
        assert "2 nodes" in message and "1 connection" in message
        assert "the code in 1 node" in message


class TestItAllowsEditing:
    def test_a_current_basis_is_never_checked(self):
        """Staleness is the precondition: with it, the same save is fine."""
        existing = _spec([_node("a")])
        _check(existing, _spec(), base=2, current=2)
        _check(existing, _spec(), base=3, current=2)

    def test_no_basis_means_no_opinion(self):
        """Scripts, tests and the internal caller send none, as before."""
        concurrency.assert_save_keeps_server_work(
            _spec([_node("a")]), _spec(), base_revision=None, current_revision=9
        )

    def test_deleting_a_node_the_client_did_load(self):
        """Two nodes on disk, the client sends one — but it is not stale, so
        this is a person deleting something they can see."""
        existing = _spec([_node("a"), _node("b")])
        _check(existing, _spec([_node("a")]), base=2, current=2)

    def test_moving_and_renaming_and_adding(self):
        existing = _spec([_node("a")])
        moved = {**_node("a"), "x": 400, "y": 300}
        _check(existing, _spec([moved, _node("new")]))

    def test_replacing_code_with_other_code_is_an_edit_not_a_loss(self):
        existing = _spec([_node("a", content="old code")])
        _check(existing, _spec([_node("a", content="new code")]))

    def test_a_node_that_had_no_code_and_still_has_none(self):
        existing = _spec([_node("a", content="   ")])
        _check(existing, _spec([_node("a", content="")]))

    def test_an_empty_project_on_both_sides(self):
        _check(_spec(), _spec())

    def test_a_malformed_spec_is_not_a_refusal(self):
        _check({}, {})
        _check({"dataflow": None}, {"dataflow": []})
        _check(_spec([{"no": "id"}]), _spec())


class TestTheLossReport:
    def test_it_names_the_ids_so_a_caller_can_say_more(self):
        existing = _spec([_node("a"), _node("b", content="x")],
                         [_edge("e1", "a", "b")])
        loss = concurrency.loss_from_save(existing, _spec([_node("b")]))
        assert loss.nodes == ("a",)
        assert loss.edges == ("e1",)
        assert loss.content == ("b",)
        assert bool(loss) is True

    def test_no_loss_is_falsy(self):
        assert not concurrency.loss_from_save(_spec(), _spec())
