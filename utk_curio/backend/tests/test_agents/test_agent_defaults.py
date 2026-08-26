"""Tests for the pure project-agent-default helpers (memo dev/23)."""

from __future__ import annotations

import pytest

from utk_curio.backend.app.agents import project_agents as pa

COORD = "agent.node-explainer@1.0.0"


class TestAgentDefaults:
    def test_missing_and_malformed_read_empty(self):
        assert pa.agent_defaults(None) == {}
        assert pa.agent_defaults({}) == {}
        assert pa.agent_defaults({"dataflow": {"agentDefaults": "junk"}}) == {}
        # Malformed coords/records are filtered out.
        spec = {"dataflow": {"agentDefaults": {"not a coord": {}, COORD: "junk"}}}
        assert pa.agent_defaults(spec) == {}

    def test_materialize_creates_and_is_idempotent(self):
        spec = {"dataflow": {}}
        rec = pa.materialize_defaults(spec, COORD, {"profileId": "p1"})
        assert rec == {"revision": 1, "settings": {"profileId": "p1"}}
        # Reinstall never resets: a second materialize returns the same record.
        rec["revision"] = 4
        again = pa.materialize_defaults(spec, COORD, {"profileId": "other"})
        assert again["revision"] == 4
        assert again["settings"] == {"profileId": "p1"}

    def test_materialize_rejects_bad_coord(self):
        with pytest.raises(ValueError, match="coordinate"):
            pa.materialize_defaults({"dataflow": {}}, "curio.builtin@1")

    def test_drop(self):
        spec = {"dataflow": {}}
        pa.materialize_defaults(spec, COORD)
        assert pa.drop_defaults(spec, COORD) is True
        assert pa.agent_defaults(spec) == {}
        assert pa.drop_defaults(spec, COORD) is False

    def test_records_are_per_coord(self):
        spec = {"dataflow": {}}
        pa.materialize_defaults(spec, COORD)
        pa.materialize_defaults(spec, "agent.debug-agent@1.0.0")
        assert set(pa.agent_defaults(spec)) == {COORD, "agent.debug-agent@1.0.0"}
