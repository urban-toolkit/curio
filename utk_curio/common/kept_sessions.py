"""The sandbox session that tags what a kept run makes.

A node's artifacts carry the session that made them (``sandbox/util/parsers.py``
``save_to_duckdb``). A run whose outputs are kept (``backend/app/runs/kept.py``),
a dashboard viewer's among them, runs each step in a session of its own, in
this shape, and the backend asks the sandbox to forget that session when the
kept output expires. The sandbox forgets only sessions of this shape, so no
mistake can reach a sign-in's artifacts.
"""

from __future__ import annotations

import re
import uuid

PREFIX = "kept-"
_PATTERN = re.compile(r"^kept-[0-9a-f]{32}$")


def new_session_id() -> str:
    """A fresh session for one step of a kept run."""
    return PREFIX + uuid.uuid4().hex


def is_kept_session(value: object) -> bool:
    """Whether *value* is a session :func:`new_session_id` made."""
    return isinstance(value, str) and bool(_PATTERN.match(value))
