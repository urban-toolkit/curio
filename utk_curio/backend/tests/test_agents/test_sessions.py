"""Tests for the per-attachment chat session store (memo dev/20)."""

from __future__ import annotations

import pytest

from utk_curio.backend.app.agents import sessions
from utk_curio.backend.app.agents.sessions import SessionError

UKEY = "42"
PID = "proj-1"
SID = "a" * 32
ATT = "att-1"


class TestReadAppend:
    def test_missing_file_reads_empty(self, tmp_curio):
        assert sessions.read_turns(UKEY, PID, SID) == []

    def test_append_read_round_trip_in_order(self, tmp_curio):
        t1 = sessions.make_turn("user", "hi")
        t2 = sessions.make_turn("agent", "hello")
        sessions.append_turns(UKEY, PID, SID, ATT, [t1, t2])
        t3 = sessions.make_turn("user", "more")
        all_turns = sessions.append_turns(UKEY, PID, SID, ATT, [t3])
        assert [t["text"] for t in all_turns] == ["hi", "hello", "more"]
        assert [t["text"] for t in sessions.read_turns(UKEY, PID, SID)] == ["hi", "hello", "more"]

    def test_corrupt_file_reads_empty(self, tmp_curio):
        sessions.append_turns(UKEY, PID, SID, ATT, [sessions.make_turn("user", "hi")])
        sessions._session_path(UKEY, PID, SID).write_text("{not json", encoding="utf-8")
        assert sessions.read_turns(UKEY, PID, SID) == []

    def test_invalid_session_id_raises(self, tmp_curio):
        with pytest.raises(SessionError):
            sessions.read_turns(UKEY, PID, "../escape")
        with pytest.raises(SessionError):
            sessions.read_turns(UKEY, PID, "UPPER-not-hex")


class TestClearDelete:
    def test_clear_empties_but_keeps_file(self, tmp_curio):
        sessions.append_turns(UKEY, PID, SID, ATT, [sessions.make_turn("user", "hi")])
        sessions.clear_turns(UKEY, PID, SID, ATT)
        assert sessions._session_path(UKEY, PID, SID).exists()
        assert sessions.read_turns(UKEY, PID, SID) == []

    def test_delete_removes_file(self, tmp_curio):
        sessions.append_turns(UKEY, PID, SID, ATT, [sessions.make_turn("user", "hi")])
        sessions.delete_session(UKEY, PID, SID)
        assert not sessions._session_path(UKEY, PID, SID).exists()
        assert sessions.read_turns(UKEY, PID, SID) == []

    def test_delete_is_best_effort(self, tmp_curio):
        # Missing file and malformed id both no-op instead of raising.
        sessions.delete_session(UKEY, PID, SID)
        sessions.delete_session(UKEY, PID, "../not-a-session")


class TestTurnsAndContext:
    def test_make_turn_validates_role(self):
        with pytest.raises(SessionError):
            sessions.make_turn("system", "nope")

    def test_context_maps_roles_and_skips_errors(self):
        turns = [
            sessions.make_turn("user", "q1"),
            sessions.make_turn("agent", "(error) boom", error=True),
            sessions.make_turn("agent", "a1"),
        ]
        msgs = sessions.context_messages(turns)
        assert msgs == [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
        ]

    def test_context_window_takes_last_n(self):
        turns = [sessions.make_turn("user", f"m{i}") for i in range(30)]
        msgs = sessions.context_messages(turns, limit=5)
        assert [m["content"] for m in msgs] == ["m25", "m26", "m27", "m28", "m29"]

    def test_context_skips_malformed(self):
        msgs = sessions.context_messages(
            [{"role": "user"}, {"role": "widget", "text": "x"}, "junk",  # type: ignore[list-item]
             {"role": "agent", "text": "ok"}]
        )
        assert msgs == [{"role": "assistant", "content": "ok"}]
