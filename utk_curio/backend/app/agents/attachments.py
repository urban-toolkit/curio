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
