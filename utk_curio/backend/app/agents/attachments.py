"""Private agent attachments, stored in the project graph spec.

An attachment binds an installed project template to a target (a node, the
canvas, or a connection) and is a private, unversioned instance: it carries an
``attachmentId`` and an optimistic-concurrency ``revision`` only — no SemVer,
release, or publication identity (``DEC-031``). Records live in
``spec["dataflow"]["agentAttachments"]`` alongside nodes/edges (``DEC-040`` —
filesystem/graph-backed, no DB).

These functions are pure over the spec dict; the service layer generates the
``attachmentId``/``sessionId`` and enforces "the template must be installed in
this project" (attach never auto-installs).
"""

from __future__ import annotations

from utk_curio.backend.app.agents.storage import AGENT_DIR_RE

_TARGET_KINDS = ("node", "canvas", "connection")

# Longest stored conversation title (memo dev/25). Manual edits over the cap
# are rejected; auto-generated titles are truncated by the service sanitizer.
TITLE_MAX_CHARS = 40


class AttachmentError(ValueError):
    """Raised when an attachment record or target is malformed."""


def _dataflow(spec: dict) -> dict:
    df = spec.get("dataflow")
    return df if isinstance(df, dict) else {}


def list_attachments(spec: dict | None) -> list[dict]:
    """Return the project's attachment records (empty when none/malformed)."""
    if not isinstance(spec, dict):
        return []
    att = _dataflow(spec).get("agentAttachments")
    return [a for a in att if isinstance(a, dict)] if isinstance(att, list) else []


def get_attachment(spec: dict, attachment_id: str) -> dict | None:
    for a in list_attachments(spec):
        if a.get("attachmentId") == attachment_id:
            return a
    return None


def _node_ids(spec: dict) -> set[str]:
    return {n.get("id") for n in _dataflow(spec).get("nodes", []) if isinstance(n, dict)}


def _edge_ids(spec: dict) -> set[str]:
    return {e.get("id") for e in _dataflow(spec).get("edges", []) if isinstance(e, dict)}


def validate_target(spec: dict, target: object) -> dict:
    """Validate a ``{kind, targetId?}`` target against the spec; return a clean copy."""
    if not isinstance(target, dict):
        raise AttachmentError("target must be an object")
    kind = target.get("kind")
    if kind not in _TARGET_KINDS:
        raise AttachmentError(f"target.kind must be one of {_TARGET_KINDS}, got {kind!r}")
    if kind == "canvas":
        return {"kind": "canvas"}
    target_id = target.get("targetId")
    if not isinstance(target_id, str) or not target_id:
        raise AttachmentError(f"target.targetId is required for a {kind} target")
    valid = _node_ids(spec) if kind == "node" else _edge_ids(spec)
    if target_id not in valid:
        raise AttachmentError(f"target.targetId {target_id!r} does not exist in the {kind} set")
    return {"kind": kind, "targetId": target_id}


def attach(spec: dict, coord: str, target: object, *, attachment_id: str, session_id: str) -> dict:
    """Append a new attachment record to the spec and return it.

    ``coord`` is a ``<agentId>@<version>`` template coordinate; ``target`` is
    validated against the spec. Ids are supplied by the caller.
    """
    if not (isinstance(coord, str) and AGENT_DIR_RE.match(coord)):
        raise AttachmentError(f"invalid agent coordinate {coord!r}")
    clean_target = validate_target(spec, target)
    if not isinstance(spec, dict):
        raise AttachmentError("spec must be a dict")
    df = spec.setdefault("dataflow", {})
    if not isinstance(df, dict):
        raise AttachmentError("spec['dataflow'] must be a dict")
    records = df.setdefault("agentAttachments", [])
    if not isinstance(records, list):
        raise AttachmentError("spec['dataflow']['agentAttachments'] must be a list")
    record = {
        "attachmentId": attachment_id,
        "coord": coord,
        "target": clean_target,
        "sessionId": session_id,
        "revision": 1,
    }
    records.append(record)
    return record


def prune_orphaned_attachments(spec: dict) -> list[dict]:
    """Drop attachments whose target graph element no longer exists.

    A ``node``/``connection`` attachment whose ``targetId`` is not in the spec's
    node/edge set is orphaned (its node/edge was deleted on the canvas) and is
    removed; ``canvas`` attachments and still-valid targets are kept. Malformed
    records (no dict target, unknown kind, missing targetId) are left untouched —
    only a clearly-orphaned node/connection target is pruned. Mutates *spec* and
    returns the removed records (empty when nothing was pruned).
    """
    if not isinstance(spec, dict):
        return []
    records = _dataflow(spec).get("agentAttachments")
    if not isinstance(records, list):
        return []
    node_ids = _node_ids(spec)
    edge_ids = _edge_ids(spec)

    def _orphaned(rec: dict) -> bool:
        target = rec.get("target")
        if not isinstance(target, dict):
            return False
        kind = target.get("kind")
        if kind == "node":
            return target.get("targetId") not in node_ids
        if kind == "connection":
            return target.get("targetId") not in edge_ids
        return False  # canvas / unknown → never pruned here

    removed = [r for r in records if isinstance(r, dict) and _orphaned(r)]
    if not removed:
        return []
    kept = [r for r in records if r not in removed]
    spec["dataflow"]["agentAttachments"] = kept
    return removed


def set_intent(spec: dict, attachment_id: str, intent: str | None) -> dict | None:
    """Set or clear an attachment's intent override and bump its revision.

    ``intent`` is the editable "initial intent" pinned in the chat panel. A
    non-empty string overrides the definition's instruction prompt for display
    and runs; ``None``/empty clears the override so the intent falls back to the
    prompt source. Returns the updated record, or ``None`` when the attachment
    does not exist.
    """
    record = get_attachment(spec, attachment_id)
    if record is None:
        return None
    if intent is not None and not isinstance(intent, str):
        raise AttachmentError("intent must be a string or null")
    cleaned = intent.strip() if isinstance(intent, str) else None
    if cleaned:
        record["intent"] = cleaned
    else:
        record.pop("intent", None)
    record["revision"] = int(record.get("revision", 1)) + 1
    return record


def set_title(spec: dict, attachment_id: str, title: str | None, *, edited: bool) -> dict | None:
    """Set or clear the attachment's conversation title and bump its revision.

    The title is the per-instance custom portion displayed as
    ``"<template name>: <title>"`` (memo dev/25); the template name is never
    stored here. Manual writes (``edited=True``) require a non-empty title
    within ``TITLE_MAX_CHARS``, always win, and set ``titleEdited`` so no
    automatic path may touch the title again. Auto writes (``edited=False``)
    are skipped when a title already exists or was manually edited; an auto
    ``None`` clears an auto-generated title only (conversation clear). Returns
    the record — unchanged (no revision bump) when the write was skipped — or
    ``None`` when the attachment does not exist.
    """
    record = get_attachment(spec, attachment_id)
    if record is None:
        return None
    if title is not None and not isinstance(title, str):
        raise AttachmentError("title must be a string or null")
    cleaned = title.strip() if isinstance(title, str) else None
    if edited:
        if not cleaned:
            raise AttachmentError("title must be a non-empty string")
        if len(cleaned) > TITLE_MAX_CHARS:
            raise AttachmentError(f"title must be at most {TITLE_MAX_CHARS} characters")
        record["title"] = cleaned
        record["titleEdited"] = True
    elif record.get("titleEdited"):
        return record  # a manual title always wins
    elif cleaned:
        if record.get("title"):
            return record  # already auto-titled — first writer wins
        record["title"] = cleaned[:TITLE_MAX_CHARS].rstrip()
    elif "title" not in record:
        return record  # nothing to clear
    else:
        record.pop("title", None)
    record["revision"] = int(record.get("revision", 1)) + 1
    return record


def detach(spec: dict, attachment_id: str) -> bool:
    """Remove an attachment by id; return True if it was present."""
    df = spec.setdefault("dataflow", {})
    records = df.get("agentAttachments")
    if not isinstance(records, list):
        return False
    kept = [a for a in records if not (isinstance(a, dict) and a.get("attachmentId") == attachment_id)]
    if len(kept) == len(records):
        return False
    df["agentAttachments"] = kept
    return True


# ── review proposals (memo dev/41) ───────────────────────────────────────────
def set_active_proposal(spec: dict, attachment_id: str, proposal: dict | None) -> dict | None:
    """Set (or clear with ``None``) the attachment's single active proposal.

    The mirror exists for fast lookup + supersede semantics; the transcript's
    proposal part remains the display record. Returns the attachment record,
    or ``None`` when the attachment does not exist."""
    record = get_attachment(spec, attachment_id)
    if record is None:
        return None
    if proposal is None:
        record.pop("activeProposal", None)
    else:
        record["activeProposal"] = proposal
    return record


def get_active_proposal(spec: dict, attachment_id: str) -> dict | None:
    record = get_attachment(spec, attachment_id)
    if record is None:
        return None
    proposal = record.get("activeProposal")
    return proposal if isinstance(proposal, dict) else None


def set_settings(spec: dict, attachment_id: str, settings: dict | None) -> dict | None:
    """Set (or clear with empty/None) the attachment's tighten-only policy
    overrides (memo dev/42) and bump the record's revision.

    The record's single optimistic ``revision`` covers intent, title, and
    settings alike — one record, one token — so any concurrent instance edit
    invalidates a stale settings draft. Returns the record, or ``None`` when
    the attachment does not exist."""
    record = get_attachment(spec, attachment_id)
    if record is None:
        return None
    if settings:
        record["settings"] = settings
    else:
        record.pop("settings", None)  # Clear overrides → project profile
    record["revision"] = int(record.get("revision", 1)) + 1
    return record
