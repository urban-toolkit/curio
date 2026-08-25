"""Tests for the pure attachment functions over the project spec."""

from __future__ import annotations

import pytest

from utk_curio.backend.app.agents import attachments
from utk_curio.backend.app.agents.attachments import AttachmentError


def _spec():
    return {"dataflow": {"nodes": [{"id": "n1"}], "edges": [{"id": "e1"}], "agents": []}}


class TestListGet:
    def test_empty(self):
        assert attachments.list_attachments(None) == []
        assert attachments.list_attachments({}) == []
        assert attachments.list_attachments({"dataflow": {}}) == []

    def test_get_missing(self):
        assert attachments.get_attachment(_spec(), "nope") is None


class TestValidateTarget:
    def test_canvas_ok(self):
        assert attachments.validate_target(_spec(), {"kind": "canvas"}) == {"kind": "canvas"}

    def test_node_requires_existing_id(self):
        assert attachments.validate_target(_spec(), {"kind": "node", "targetId": "n1"}) == {
            "kind": "node",
            "targetId": "n1",
        }
        with pytest.raises(AttachmentError, match="does not exist"):
            attachments.validate_target(_spec(), {"kind": "node", "targetId": "ghost"})

    def test_connection_targets_an_edge(self):
        assert attachments.validate_target(_spec(), {"kind": "connection", "targetId": "e1"})["kind"] == "connection"
        with pytest.raises(AttachmentError):
            attachments.validate_target(_spec(), {"kind": "connection", "targetId": "n1"})  # not an edge

    def test_missing_target_id(self):
        with pytest.raises(AttachmentError, match="required"):
            attachments.validate_target(_spec(), {"kind": "node"})

    def test_bad_kind(self):
        with pytest.raises(AttachmentError, match="kind"):
            attachments.validate_target(_spec(), {"kind": "widget"})


class TestAttachDetach:
    def test_attach_appends_record(self):
        spec = _spec()
        rec = attachments.attach(
            spec, "agent.node-explainer@1.0.0", {"kind": "node", "targetId": "n1"},
            attachment_id="att1", session_id="sess1",
        )
        assert rec == {
            "attachmentId": "att1",
            "coord": "agent.node-explainer@1.0.0",
            "target": {"kind": "node", "targetId": "n1"},
            "sessionId": "sess1",
            "revision": 1,
        }
        assert attachments.list_attachments(spec) == [rec]
        assert attachments.get_attachment(spec, "att1") == rec

    def test_attach_bad_coord(self):
        with pytest.raises(AttachmentError, match="coordinate"):
            attachments.attach(_spec(), "curio.builtin@1", {"kind": "canvas"},
                               attachment_id="a", session_id="s")

    def test_detach(self):
        spec = _spec()
        attachments.attach(spec, "agent.x@1.0.0", {"kind": "canvas"}, attachment_id="a", session_id="s")
        assert attachments.detach(spec, "a") is True
        assert attachments.list_attachments(spec) == []
        assert attachments.detach(spec, "a") is False


class TestSetIntent:
    def _attached(self):
        spec = _spec()
        attachments.attach(spec, "agent.x@1.0.0", {"kind": "canvas"}, attachment_id="a", session_id="s")
        return spec

    def test_set_and_bump_revision(self):
        spec = self._attached()
        rec = attachments.set_intent(spec, "a", "explain gently")
        assert rec["intent"] == "explain gently"
        assert rec["revision"] == 2

    def test_clear_with_none_and_empty(self):
        spec = self._attached()
        attachments.set_intent(spec, "a", "custom")
        rec = attachments.set_intent(spec, "a", None)
        assert "intent" not in rec
        attachments.set_intent(spec, "a", "again")
        rec = attachments.set_intent(spec, "a", "   ")
        assert "intent" not in rec
        assert rec["revision"] == 5

    def test_unknown_attachment_returns_none(self):
        assert attachments.set_intent(self._attached(), "ghost", "x") is None

    def test_non_string_intent_raises(self):
        with pytest.raises(AttachmentError, match="intent"):
            attachments.set_intent(self._attached(), "a", 42)
