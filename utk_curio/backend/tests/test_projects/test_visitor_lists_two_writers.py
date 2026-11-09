"""Two new dataflows a hosted guest makes at once are both listed.

A hosted guest's File > New lists the new dataflow in that visitor's list
(``visitor_copies._list``): read the list, add the id, write it whole. A
thread lock kept two writes of the lists apart in one process, but two
backend processes each have their own: two new dataflows of one visitor
listed at once could leave one off the list, and the visitor's gallery no
longer showed it.

The test forks a write that stops after its read of the list, then lists
another dataflow from this process (``_support/two_processes.py``).
"""
from __future__ import annotations

SIGN_IN = "visitor-7f3a"


def test_two_new_dataflows_listed_at_once_are_both_listed(tmp_curio, monkeypatch):
    from utk_curio.backend.app.projects import visitor_copies
    from utk_curio.backend.tests._support.two_processes import Window, race

    window = Window()
    read = visitor_copies._listed

    def _read_then_stop(sign_in):
        listed = read(sign_in)
        window.stop_here()
        return listed

    monkeypatch.setattr(visitor_copies, "_listed", _read_then_stop)

    raced = race(
        window,
        lambda: visitor_copies._list(SIGN_IN, "own-first"),
        lambda: visitor_copies._list(SIGN_IN, "own-second"),
        monkeypatch,
    )

    assert raced.child_exit == 0, raced.child_error
    listed = read(SIGN_IN)
    assert listed == ["own-first", "own-second"], (
        f"a new dataflow listed while another was being listed fell off the visitor's list: {listed}"
    )
