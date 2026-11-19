"""How far the downloads of a Play the browser runs have come, for the page that waits for it.

A Play in the browser (a hosted guest's, a shared viewer's, one with no
project) posts ``/processPythonCode``, whose answer comes once the node has
run, and a node's first run downloads what it reads first
(``datasets/infrastructure/left_out_files.py``), SAM 3's 3.4 GB of weights
among them. While it waits, the page asks ``GET /processPythonCode/progress``
how far they have come (``api/routes.py``) and shows it on the node, as a run
on the server shows its ``step_progress`` (``utils/nodeRunRequest.ts``).

What a Play's downloads said last is kept here, by the process that runs it,
under the sign-in that posted it and the id the page gave it, until the Play
ends. The page asks with the same ``X-Curio-Dataflow`` header as the Play, so
in a start of several backend processes the router sends both to the same
one.
"""
from __future__ import annotations

import contextlib
import threading

#: The most Plays whose progress is kept at once: one past it says nothing.
MAX_KEPT = 1024
#: The longest id a page may give its Play.
MAX_ID_CHARS = 64

_lock = threading.Lock()
_said: dict[tuple[str, str], dict] = {}


def _key(sign_in: str | None, play_id: object) -> tuple[str, str] | None:
    if not sign_in or not isinstance(play_id, str) or not play_id or len(play_id) > MAX_ID_CHARS:
        return None
    return sign_in, play_id


@contextlib.contextmanager
def kept(sign_in: str | None, play_id: object):
    """Keep, under *sign_in* and *play_id*, what each download on first use
    of the Play run inside the block says (:func:`left_out_files.reporting`),
    until the block ends; nothing for a Play with no id."""
    key = _key(sign_in, play_id)
    if key is None:
        yield
        return
    from utk_curio.backend.app.datasets.infrastructure import left_out_files

    def report(progress) -> None:
        with _lock:
            if key in _said or len(_said) < MAX_KEPT:
                _said[key] = left_out_files.progress_fields(progress)

    try:
        with left_out_files.reporting(report):
            yield
    finally:
        with _lock:
            _said.pop(key, None)


def said(sign_in: str | None, play_id: object) -> dict:
    """What the downloads of the Play *play_id* that *sign_in* posted said
    last (:func:`left_out_files.progress_fields`): an empty message when
    they have said nothing, are over, or the Play is not running."""
    key = _key(sign_in, play_id)
    with _lock:
        found = _said.get(key) if key is not None else None
    return dict(found) if found else {"message": ""}
