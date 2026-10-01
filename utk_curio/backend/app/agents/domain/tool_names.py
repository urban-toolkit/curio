"""A tool id on the wire and back: providers allow only letters, digits, ``_`` and ``-`` in a native tool name.

Domain rule of the agents package (memo dev/142; re-derived on enh/agent-catalog): cut from
``application/tools.py`` so the test provider, an infrastructure module, can read it without
reaching up into the application layer.
"""

from __future__ import annotations

from utk_curio.backend.app.agents.domain.manifest import CAPABILITY_ID_RE


def wire_name(tool_id: str) -> str:
    """*tool_id* as a native tool name. Providers allow only letters, digits,
    ``_`` and ``-`` in a name, so each ``.`` becomes ``__``; a tool id has no
    ``_``, so :func:`tool_id_of` reverses it."""
    return tool_id.replace(".", "__")


def tool_id_of(name: object) -> str | None:
    """The tool id a native name encodes, or None when it encodes none."""
    if not isinstance(name, str):
        return None
    tool_id = name.replace("__", ".")
    return tool_id if CAPABILITY_ID_RE.match(tool_id) else None
