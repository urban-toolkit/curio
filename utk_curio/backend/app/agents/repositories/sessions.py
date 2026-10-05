"""Per-attachment chat session transcripts (persistent sessions, memo ``dev/20``).

Each attachment record carries a ``sessionId``; its transcript lives in a
private sidecar file OUTSIDE the project spec so the graph spec (and therefore
the share pipeline and canvas saves) never contains conversation content:

    .curio/users/<key>/projects/<pid>/agent-sessions/<sessionId>.json
    {"sessionId": ..., "attachmentId": ..., "turns": [{"role", "text", ...}]}

A transcript lives exactly as long as its attachment (fail-closed interim
retention; final durations remain ``OQ-008``): detach and orphan-prune delete
the file. A missing or unreadable file reads as an empty transcript, so
records that predate this store need no migration.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from utk_curio.backend.app.projects import storage as projects_storage

# Session ids are service-minted ``uuid4().hex``; the pattern keeps any value
# that reaches the filesystem a single safe path segment.
SESSION_ID_RE = re.compile(r"^[0-9a-f]{8,64}$")

# How many prior turns ride along as provider context on each run. A cost /
# context-size guard, not a display limit — the full transcript still renders.
CONTEXT_WINDOW_TURNS = 20

TURN_ROLES = ("user", "agent")


class SessionError(ValueError):
    """Raised for an invalid session id or malformed turn."""


def sessions_dir(user_key: str, project_id: str) -> Path:
    return projects_storage.project_dir(user_key, project_id) / "agent-sessions"


def _session_path(user_key: str, project_id: str, session_id: str) -> Path:
    if not (isinstance(session_id, str) and SESSION_ID_RE.match(session_id)):
        raise SessionError(f"invalid session id {session_id!r}")
    return sessions_dir(user_key, project_id) / f"{session_id}.json"


def read_turns(user_key: str, project_id: str, session_id: str) -> list[dict]:
    """The session's turns, oldest first. Missing/corrupt file → empty list."""
    path = _session_path(user_key, project_id, session_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    turns = data.get("turns") if isinstance(data, dict) else None
    return [t for t in turns if isinstance(t, dict)] if isinstance(turns, list) else []


def make_turn(
    role: str,
    text: str,
    *,
    error: bool = False,
    execution: dict | None = None,
    content: list | None = None,
) -> dict:
    if role not in TURN_ROLES:
        raise SessionError(f"turn role must be one of {TURN_ROLES}, got {role!r}")
    turn: dict = {
        "role": role,
        "text": text,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if error:
        turn["error"] = True
    if execution is not None:
        # Execution record (memo dev/37): the transcript IS the run history —
        # id, DEC-031 pins, duration, status, Actual usage ride the agent turn.
        turn["execution"] = execution
    if content:
        # Typed content parts (memo dev/39): validated structured content —
        # suggested prompts, cards — rides the agent turn it belongs to.
        turn["content"] = content
    return turn


def append_turns(
    user_key: str, project_id: str, session_id: str, attachment_id: str, new_turns: list[dict]
) -> list[dict]:
    """Append turns and persist; returns the full transcript."""
    turns = read_turns(user_key, project_id, session_id) + list(new_turns)
    path = _session_path(user_key, project_id, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"sessionId": session_id, "attachmentId": attachment_id, "turns": turns},
            indent=2,
        ),
        encoding="utf-8",
    )
    return turns


def update_proposal_status(
    user_key: str, project_id: str, session_id: str, proposal_id: str, status: str
) -> bool:
    """Set the status of one persisted proposal part (memo dev/41).

    The transcript stays the display record of a proposal's lifecycle: apply/
    dismiss/supersede update the part in place (the one sanctioned turn edit —
    it changes proposal state, never text). Returns True when a part was
    updated; a missing session/part is False, never an error."""
    turns = read_turns(user_key, project_id, session_id)
    changed = False
    for turn in turns:
        for part in turn.get("content") or []:
            if (
                isinstance(part, dict)
                and part.get("type") == "proposal"
                and part.get("proposalId") == proposal_id
                and part.get("status") != status
            ):
                part["status"] = status
                changed = True
    if not changed:
        return False
    path = _session_path(user_key, project_id, session_id)
    data = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    attachment_id = data.get("attachmentId") if isinstance(data, dict) else None
    path.write_text(
        json.dumps(
            {"sessionId": session_id, "attachmentId": attachment_id, "turns": turns},
            indent=2,
        ),
        encoding="utf-8",
    )
    return True


def clear_turns(user_key: str, project_id: str, session_id: str, attachment_id: str) -> None:
    """Empty the transcript but keep the session file/id."""
    path = _session_path(user_key, project_id, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"sessionId": session_id, "attachmentId": attachment_id, "turns": []}, indent=2),
        encoding="utf-8",
    )


def delete_session(user_key: str, project_id: str, session_id: str) -> None:
    """Remove the transcript file entirely (detach / orphan-prune GC)."""
    try:
        _session_path(user_key, project_id, session_id).unlink(missing_ok=True)
    except (SessionError, OSError):
        # Best-effort GC: a malformed legacy id or racing delete never blocks
        # the detach/prune that triggered it.
        pass


def context_messages(turns: list[dict], limit: int = CONTEXT_WINDOW_TURNS) -> list[dict]:
    """Map the last ``limit`` non-error turns to OpenAI-style chat messages.

    Error markers are display-only history and are excluded from provider
    context.
    """
    usable = [
        t
        for t in turns
        if isinstance(t, dict)
        and t.get("role") in TURN_ROLES
        and isinstance(t.get("text"), str)
        and not t.get("error")
    ]
    role_map = {"user": "user", "agent": "assistant"}
    return [{"role": role_map[t["role"]], "content": t["text"]} for t in usable[-limit:]]
