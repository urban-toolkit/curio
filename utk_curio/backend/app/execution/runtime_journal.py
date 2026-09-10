"""Per-node runtime journal (memo dev/67-2, DEC-052).

The sandbox already reports machine-readable outcomes — the full traceback in
``stderr`` and the canonical failure predicate ``output.path == ""`` (benign
warnings also land in stderr, so stderr-nonempty is NEVER the predicate) — but
until dev/67-2 the result lived only in one HTTP response and a transient React
string. This module persists the LATEST outcome per node so agents (debug,
explainer, content builder, validators) can answer "what ran, what failed, and
why" after the fact.

Design rules:
- **Observational, never authoritative**: the saved spec is the structural
  truth; the journal is a best-effort record. Writes never raise and never
  block an execution response; reads fail open (malformed/missing → "never
  executed").
- **Latest-per-node** (one file per node, overwritten) — history is
  provenance's job.
- Storage rides the project directory (`DEC-040` filesystem posture):
  ``<project dir>/runtime/<nodeId>.json``.
"""

from __future__ import annotations

import hashlib
import json
import re
import textwrap
import time

from utk_curio.backend.app.projects import storage as projects_storage

_STDERR_TAIL_CHARS = 4000
_STDOUT_TAIL_CHARS = 2000
# Node ids come from specs (untrusted for path purposes): filename-safe only.
_NODE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]")


def _node_segment(node_id: str) -> str:
    cleaned = _NODE_SEGMENT_RE.sub("_", node_id)[:80]
    return cleaned or "node"


def normalized_code_sha256(code: str) -> str:
    """Digest of code normalized against transport indentation.

    The execution route receives the node's code re-indented for the sandbox
    wrapper; the spec stores it flush. Dedent+strip before hashing so the same
    logical content digests identically on both sides (best-effort staleness
    signal, not a security boundary)."""
    normalized = textwrap.dedent(code or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def record_execution(
    user_key: str,
    project_id: str,
    node_id: str,
    *,
    code: str,
    stdout,
    stderr,
    output,
    started_at: str,
    duration_ms: float,
    validation: bool = False,
) -> None:
    """Persist one execution outcome. Best-effort: never raises."""
    try:
        out = output if isinstance(output, dict) else {}
        ok = bool(str(out.get("path") or ""))  # the canonical predicate
        if isinstance(stdout, list):
            stdout_text = "\n".join(str(line) for line in stdout)
        else:
            stdout_text = str(stdout or "")
        stderr_text = str(stderr or "")
        previous = read_record(user_key, project_id, node_id)
        try:
            seq = int((previous or {}).get("executionSeq") or 0) + 1
        except (TypeError, ValueError):
            seq = 1
        record = {
            "nodeId": node_id,
            "status": "ok" if ok else "error",
            "stderrTail": stderr_text[-_STDERR_TAIL_CHARS:],
            "stdoutTail": stdout_text[-_STDOUT_TAIL_CHARS:],
            "output": {
                "path": str(out.get("path") or ""),
                "dataType": str(out.get("dataType") or ""),
            },
            "startedAt": started_at,
            "durationMs": int(duration_ms),
            "executionSeq": seq,
            "executedCodeSha256": normalized_code_sha256(str(code or "")),
            "validation": bool(validation),
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        directory = projects_storage.ensure_project_dir(user_key, project_id) / "runtime"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{_node_segment(node_id)}.json"
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    except Exception:
        # Observational store: an execution must never fail over its journal.
        pass


def read_record(user_key: str, project_id: str, node_id: str) -> dict | None:
    """The node's latest outcome, or None (never executed / unreadable)."""
    try:
        path = (
            projects_storage.project_dir(user_key, project_id)
            / "runtime"
            / f"{_node_segment(node_id)}.json"
        )
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


#: dev/129: how much of a recorded failure the repair loop is handed. The
#: bounds mirror the ``node.runtime.read`` tool's, so the loop and the model
#: read the same size of truth.
_FAILURE_STDERR_CHARS = 4000


def last_failure(user_key: str, project_id: str, node_id: str) -> dict | None:
    """The node's last recorded FAILURE, whatever ran it, or None.

    Memo dev/129, from the owner's instruction — *"the dataflow resolution must
    be able to read errors raised by any execution and properly act to fix
    it."* Every real run journals its outcome (``DEC-052``): a Play run through
    the interactive route and a validation run through the runner both land
    here. Until now the journal had exactly one reader — the model-chosen
    ``node.runtime.read`` tool — so a node that failed at Play was re-solved
    from scratch, as if the traceback on disk did not exist.

    Returns ``{codeSha256, stderr, ranAt, origin}`` where ``origin`` is
    ``"validation"`` or ``"play"``; ``None`` when the node never ran, ran
    successfully, or has no readable record. The record stores the code's
    DIGEST rather than its text (the node's own content is the text), so the
    caller compares ``codeSha256`` with ``normalized_code_sha256(content)`` and
    knows whether the failure is about the code that is still there.
    """
    record = read_record(user_key, project_id, node_id)
    if not isinstance(record, dict) or record.get("status") != "error":
        return None
    stderr = str(record.get("stderrTail") or "")
    return {
        "codeSha256": str(record.get("executedCodeSha256") or ""),
        "stderr": stderr[-_FAILURE_STDERR_CHARS:],
        "ranAt": str(record.get("startedAt") or record.get("updatedAt") or ""),
        "origin": "validation" if record.get("validation") else "play",
    }


def failure_matches(failure: dict | None, content: object) -> bool:
    """Whether a recorded failure is about the code the node still holds."""
    if not isinstance(failure, dict) or not failure.get("codeSha256"):
        return False
    if not isinstance(content, str) or not content.strip():
        return False
    return failure["codeSha256"] == normalized_code_sha256(content)


def status_map(user_key: str, project_id: str) -> dict[str, dict]:
    """``{nodeId: {status, updatedAt}}`` for the dataflow.read projection."""
    out: dict[str, dict] = {}
    try:
        directory = projects_storage.project_dir(user_key, project_id) / "runtime"
        if not directory.is_dir():
            return out
        for path in sorted(directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            node_id = data.get("nodeId") if isinstance(data, dict) else None
            if isinstance(node_id, str):
                out[node_id] = {
                    "status": data.get("status"),
                    "updatedAt": data.get("updatedAt"),
                }
    except Exception:
        pass
    return out
