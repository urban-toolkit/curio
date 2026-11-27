"""A paced word whose next wait cannot start leaves its dataflow free to be told again.

``roles.PacedWord`` tells the tabs that edit a dataflow a word at once, then
waits on a timer's thread before it tells another: what changed during the
wait is told when it ends, and the next wait starts. When that timer's thread
cannot start (``RuntimeError: can't start new thread``, a process at its
limit of threads), the dataflow's wait ends with it. Kept, it would never end,
and the room would never again be told of the dataflow's chats, nor of its
agents' attachments, until the process restarts: both words run on this code
(``agent_chat_changed``, ``agent_attachments_changed``).

The timers are stand-ins: a wait ends when the test ends it, on a thread of
its own, as its timer's thread would run it, and a stand-in whose start fails
raises as ``threading.Thread.start`` does. The room is a list of what it was
told.

On main, the wait whose next timer could not start stays, and the change
after it is never told.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

from utk_curio.backend.app.collaboration import roles

EVENT = "agent_chat_changed"


class _Timers:
    """Stand-ins for ``threading.Timer``: each one started is kept for the
    test to end; while *failing*, a start raises as a thread the process
    cannot start does."""

    def __init__(self) -> None:
        self.started: list = []
        self.failing = False
        timers = self

        class Timer:
            def __init__(self, interval, function, args=None, kwargs=None):
                self.function, self.args, self.daemon = function, tuple(args or ()), False

            def start(self):
                if timers.failing:
                    raise RuntimeError("can't start new thread")
                timers.started.append(self)

        self.Timer = Timer

    def end_the_last_wait(self) -> None:
        """The last wait started ends, on a thread of its own, as its timer's
        thread would end it."""
        timer = self.started.pop()
        ends = threading.Thread(target=timer.function, args=timer.args)
        ends.start()
        ends.join()


def test_a_wait_whose_next_timer_cannot_start_ends_so_the_next_change_is_told_at_once(monkeypatch):
    told: list[dict] = []

    def tell_editors(project_id, event, payload, *, app=None):
        told.append(payload)
        return 1

    monkeypatch.setattr(roles, "tell_editors", tell_editors)
    timers = _Timers()
    monkeypatch.setattr(roles, "threading", SimpleNamespace(Timer=timers.Timer, Lock=threading.Lock))
    word = roles.PacedWord(EVENT, lambda: 0.25, names="attachmentIds")

    # A change is told at once, and its wait starts; one made during the wait
    # is told when it ends.
    word.tell("p1", "att-one")
    word.tell("p1", "att-two")
    assert told == [{"projectId": "p1", "attachmentIds": ["att-one"]}]

    # The wait ends, and the timer of the wait after it cannot start.
    timers.failing = True
    timers.end_the_last_wait()

    # Threads start again: the next change is told at once, as on a dataflow
    # with no wait.
    timers.failing = False
    word.tell("p1", "att-three")
    assert {"projectId": "p1", "attachmentIds": ["att-three"]} in told, (
        f"the room was never told the change after a wait whose next timer could not start: {told}")
    assert told == [
        {"projectId": "p1", "attachmentIds": ["att-one"]},
        {"projectId": "p1", "attachmentIds": ["att-two"]},
        {"projectId": "p1", "attachmentIds": ["att-three"]},
    ], f"the change made during the wait was not told when the wait ended: {told}"
