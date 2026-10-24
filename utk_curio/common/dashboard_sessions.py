"""The sandbox session that tags what a dashboard viewer's run makes.

A node's artifacts carry the session that made them (``sandbox/util/parsers.py``
``save_to_duckdb``). A run a dashboard's viewer starts has no sign-in, so each
step it runs gets a session of its own, in this shape, and the backend asks
the sandbox to forget that session when the kept output expires. The sandbox
forgets only sessions of this shape, so no mistake can reach a sign-in's
artifacts.
"""

from __future__ import annotations

import re
import uuid

PREFIX = "dashboard-"
_PATTERN = re.compile(r"^dashboard-[0-9a-f]{32}$")


def new_session_id() -> str:
    """A fresh session for one step of a viewer's run."""
    return PREFIX + uuid.uuid4().hex


def is_dashboard_session(value: object) -> bool:
    """Whether *value* is a session :func:`new_session_id` made."""
    return isinstance(value, str) and bool(_PATTERN.match(value))
