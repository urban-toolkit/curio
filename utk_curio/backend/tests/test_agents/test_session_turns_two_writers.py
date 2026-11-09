"""A turn written to a chat while another write of it is under way is kept.

An attachment's chat is one file (``repositories/sessions.py``), and every
write of it read the turns, changed them and wrote the file whole, with no
lock. A delegated task appends its turns to its home attachment's chat from
the delegating agent's turn (``turns/delegates.py``), outside that
attachment's own queue, so it can land while the attachment's own turn
appends, or while a proposal in it is applied: the later write dropped the
other's turn. Two backend processes make it likelier.

Each test forks a write that stops after its read of the turns, then writes
from this process (``_support/two_processes.py``).
"""
from __future__ import annotations

ACCOUNT, PROJECT = "7", "p1"
SESSION = "0123456789abcdef0123456789abcdef"
ATTACHMENT = "att-1"
DELEGATED = "[Delegated by Node Builder] add a line on top of the node's code"


def _stop_after_each_read(monkeypatch, sessions, window) -> None:
    read = sessions.read_turns

    def _read_then_stop(*args, **kwargs):
        turns = read(*args, **kwargs)
        window.stop_here()
        return turns

    monkeypatch.setattr(sessions, "read_turns", _read_then_stop)


def test_two_turns_appended_at_once_are_both_kept(tmp_curio, monkeypatch):
    from utk_curio.backend.app.agents.repositories import sessions
    from utk_curio.backend.tests._support.two_processes import Window, race

    window = Window()
    _stop_after_each_read(monkeypatch, sessions, window)

    raced = race(
        window,
        lambda: sessions.append_turns(ACCOUNT, PROJECT, SESSION, ATTACHMENT, [sessions.make_turn("user", DELEGATED)]),
        lambda: sessions.append_turns(
            ACCOUNT, PROJECT, SESSION, ATTACHMENT, [sessions.make_turn("agent", "the attachment's own reply")],
        ),
        monkeypatch,
    )

    assert raced.child_exit == 0, raced.child_error
    texts = [turn["text"] for turn in sessions.read_turns(ACCOUNT, PROJECT, SESSION)]
    assert texts == [DELEGATED, "the attachment's own reply"], (
        f"a turn appended while another append was under way was lost: {texts}"
    )


def test_a_turn_appended_while_a_proposal_is_applied_is_kept(tmp_curio, monkeypatch):
    from utk_curio.backend.app.agents.repositories import sessions
    from utk_curio.backend.tests._support.two_processes import Window, race

    plan = sessions.make_turn(
        "agent", "a plan", content=[{"type": "proposal", "proposalId": "prop-1", "status": "pending"}],
    )
    sessions.append_turns(ACCOUNT, PROJECT, SESSION, ATTACHMENT, [plan])
    window = Window()
    _stop_after_each_read(monkeypatch, sessions, window)

    raced = race(
        window,
        lambda: sessions.update_proposal_status(ACCOUNT, PROJECT, SESSION, "prop-1", "applied"),
        lambda: sessions.append_turns(ACCOUNT, PROJECT, SESSION, ATTACHMENT, [sessions.make_turn("user", DELEGATED)]),
        monkeypatch,
    )

    assert raced.child_exit == 0, raced.child_error
    turns = sessions.read_turns(ACCOUNT, PROJECT, SESSION)
    assert [turn["text"] for turn in turns] == ["a plan", DELEGATED], (
        f"a turn appended while a proposal was applied was lost: {[turn['text'] for turn in turns]}"
    )
    assert turns[0]["content"][0]["status"] == "applied", turns[0]["content"]
