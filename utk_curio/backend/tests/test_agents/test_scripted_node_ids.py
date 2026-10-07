"""Scripted ids for the nodes an apply creates.

The applied turn prints a created node's id ("Applied: node created (<id>)."),
and the e2e chat capture shows that turn. A fresh uuid4 wraps the line or not
by how wide its letters render, so the capture moved by a line from run to run.
A test run scripts the id, as it scripts the reply; a deployment never does.
"""
from __future__ import annotations

import uuid

import pytest

from utk_curio.backend.app.agents.application.proposals import apply
from utk_curio.backend.app.agents.infrastructure import testing_provider

SCRIPTED = "0b6c3c1e-5d1f-5a8e-9c3d-2f4b6a8c0e12"
SECOND = "7e1d2c3b-4a59-4687-b6c5-d4e3f2a1b0c9"


def _spec(*nodes):
    return {"dataflow": {"nodes": list(nodes), "edges": []}}


@pytest.fixture(autouse=True)
def _testing_run(monkeypatch):
    monkeypatch.setattr(testing_provider, "enabled", lambda: True)
    testing_provider.reset()
    yield
    testing_provider.reset()


class TestQueue:
    def test_ids_come_back_in_order_then_none(self):
        testing_provider.push_node_ids(SCRIPTED, SECOND)
        assert testing_provider.next_node_id() == SCRIPTED
        assert testing_provider.next_node_id() == SECOND
        assert testing_provider.next_node_id() is None

    def test_reset_drops_queued_ids(self):
        testing_provider.push_node_ids(SCRIPTED)
        testing_provider.reset()
        assert testing_provider.next_node_id() is None

    def test_none_outside_a_test_run(self, monkeypatch):
        """A deployment mints its own ids whatever was queued."""
        testing_provider.push_node_ids(SCRIPTED)
        monkeypatch.setattr(testing_provider, "enabled", lambda: False)
        assert testing_provider.next_node_id() is None


class TestInsertNode:
    def test_a_created_node_takes_the_scripted_id(self):
        testing_provider.push_node_ids(SCRIPTED)
        created = apply._insert_node(_spec(), "curio.builtin/data-loading", "", None)
        assert created["id"] == SCRIPTED

    def test_each_scripted_id_is_used_once(self):
        testing_provider.push_node_ids(SCRIPTED)
        spec = _spec()
        first = apply._insert_node(spec, "curio.builtin/data-loading", "", None)
        second = apply._insert_node(spec, "curio.builtin/data-loading", "", None)
        assert first["id"] == SCRIPTED
        assert uuid.UUID(second["id"]).version == 4

    def test_an_id_already_on_the_canvas_is_never_reused(self):
        testing_provider.push_node_ids(SCRIPTED)
        spec = _spec({"id": SCRIPTED, "x": 0, "y": 0})
        created = apply._insert_node(spec, "curio.builtin/data-loading", "", None)
        assert created["id"] != SCRIPTED
        assert uuid.UUID(created["id"]).version == 4

    def test_without_a_script_the_id_is_a_fresh_uuid4(self):
        spec = _spec()
        ids = {apply._insert_node(spec, "curio.builtin/data-loading", "", None)["id"]
               for _ in range(3)}
        assert len(ids) == 3
        assert all(uuid.UUID(i).version == 4 for i in ids)

    def test_outside_a_test_run_a_queued_id_is_ignored(self, monkeypatch):
        testing_provider.push_node_ids(SCRIPTED)
        monkeypatch.setattr(testing_provider, "enabled", lambda: False)
        created = apply._insert_node(_spec(), "curio.builtin/data-loading", "", None)
        assert created["id"] != SCRIPTED
