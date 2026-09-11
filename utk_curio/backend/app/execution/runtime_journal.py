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

dev/135: a run is a run wherever it happens. Until now this module had three
writers and all three were the sandbox, so a Vega-Lite chart, an AUTK map, a
Data Pool, a Merge Flow, a Simple View, a Spatial Join and a Data Export — every
kind that runs in the BROWSER or through its own service — left no trace at all,
and every agent reading the journal was told ``never-executed`` about a node the
user had just watched fail (the owner's `a29d1ad8`). Two facts make room for
them: an explicit ``status``, because ``output.path == ""`` is a SANDBOX
predicate (a chart that rendered perfectly produces no artifact and would be
journaled as an error), and an ``origin`` — ``sandbox`` | ``validation`` |
``browser`` — so a reader can always tell what produced the record. A browser
record is evidence like any other and authority like none: it carries no
artifact path, and nothing downstream treats it as one.
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

#: dev/135: where a record came from. ``sandbox`` is an interactive run through
#: the execution routes, ``validation`` a run the agent runtime drove, and
#: ``browser`` an outcome a node reported from the client (a render, a compile,
#: a service call it made itself).
ORIGIN_SANDBOX = "sandbox"
ORIGIN_VALIDATION = "validation"
ORIGIN_BROWSER = "browser"
ORIGINS = (ORIGIN_SANDBOX, ORIGIN_VALIDATION, ORIGIN_BROWSER)

#: The statuses a record may carry. ``running`` exists so a long browser render
#: can say so; nothing derives a failure from it.
STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_RUNNING = "running"
STATUSES = (STATUS_OK, STATUS_ERROR, STATUS_RUNNING)

#: A browser message is a sentence, not a traceback: bounded on arrival here as
#: well as at the route, so no caller can grow the record.
BROWSER_MESSAGE_CHARS = 2000

#: dev/136: an outcome's kind, when the reporter knows one (``empty-render``).
#: Free-form and bounded: an unrecognized kind is a label, never a branch.
_KIND_CHARS = 40
KIND_EMPTY_RENDER = "empty-render"
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
    status: str | None = None,
    origin: str | None = None,
    kind: str = "",
) -> None:
    """Persist one execution outcome. Best-effort: never raises.

    ``status`` (dev/135) overrides the sandbox predicate for a caller whose run
    produces no artifact — a browser render, a compile, a service call. When it
    is None the canonical rule stands, so every existing caller is unchanged.
    ``origin`` defaults to ``validation``/``sandbox`` from the ``validation``
    flag, which is what the two sandbox writers have always meant.
    """
    try:
        out = output if isinstance(output, dict) else {}
        if status in STATUSES:
            ok = status == STATUS_OK
            recorded_status = status
        else:
            ok = bool(str(out.get("path") or ""))  # the canonical predicate
            recorded_status = STATUS_OK if ok else STATUS_ERROR
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
            "status": recorded_status,
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
            # dev/135: what produced this record. Read as evidence, never as
            # authority — a browser record carries no artifact path.
            "origin": (
                origin if origin in ORIGINS
                else (ORIGIN_VALIDATION if validation else ORIGIN_SANDBOX)
            ),
            # dev/136: what KIND of outcome this is, when the reporter knows —
            # `empty-render` is the one the harness branches on.
            **({"kind": str(kind)[:_KIND_CHARS]} if kind else {}),
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        directory = projects_storage.ensure_project_dir(user_key, project_id) / "runtime"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{_node_segment(node_id)}.json"
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    except Exception:
        # Observational store: an execution must never fail over its journal.
        pass


def record_browser_execution(
    user_key: str,
    project_id: str,
    node_id: str,
    *,
    status: str,
    message: str = "",
    output_type: str = "",
    duration_ms: float = 0,
    code: str = "",
    started_at: str | None = None,
    kind: str = "",
) -> bool:
    """Journal an outcome a node reported from the CLIENT (memo dev/135).

    The browser's vocabulary is a message, not a stream: a render error, a
    grammar compile failure, a service call's reason. It is written into the
    same record every other run writes — ``stderrTail`` for the message, so
    ``last_failure`` and ``node.runtime.read`` need no special case — with
    ``origin: "browser"`` and NO artifact path, because a client cannot mint
    one. Returns whether a write was attempted (a bad status is refused);
    never raises, like every write here.
    """
    if status not in STATUSES:
        return False
    text = str(message or "")[-BROWSER_MESSAGE_CHARS:]
    # dev/137: its OWN file. dev/135 wrote through `record_execution`, which is
    # latest-per-node — and the client always writes LAST (the sandbox responds,
    # React settles the output, the reporter posts), so every code node's run
    # record was being overwritten by a render report carrying no artifact, no
    # dataType and no traceback. The owner's `7a27b702` had six records and all
    # six said `origin: browser`, including four Python nodes. Two origins, two
    # files: a run keeps its own facts forever.
    try:
        previous = read_render_record(user_key, project_id, node_id)
        try:
            seq = int((previous or {}).get("executionSeq") or 0) + 1
        except (TypeError, ValueError):
            seq = 1
        record = {
            "nodeId": node_id,
            "status": status,
            "stderrTail": text if status == STATUS_ERROR else "",
            "stdoutTail": "" if status == STATUS_ERROR else text[-_STDOUT_TAIL_CHARS:],
            # A browser run produces no artifact; the declared type is what it
            # can honestly report about its output.
            "output": {"path": "", "dataType": str(output_type or "")},
            "startedAt": started_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "durationMs": int(duration_ms or 0),
            "executionSeq": seq,
            "executedCodeSha256": normalized_code_sha256(str(code or "")),
            "validation": False,
            "origin": ORIGIN_BROWSER,
            **({"kind": str(kind)[:_KIND_CHARS]} if kind else {}),
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        directory = projects_storage.ensure_project_dir(user_key, project_id) / "runtime"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{_node_segment(node_id)}{_RENDER_SUFFIX}").write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8",
        )
    except Exception:
        # Observational store: a render must never fail over its journal.
        pass
    return True


#: dev/137: the file a BROWSER report writes, beside the run's own. Two origins
#: describe two different things about one node — what its code did, and what
#: its render drew — and neither may erase the other.
_RENDER_SUFFIX = ".render.json"


def _read_json(user_key: str, project_id: str, filename: str) -> dict | None:
    try:
        path = (
            projects_storage.project_dir(user_key, project_id) / "runtime" / filename
        )
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def read_record(user_key: str, project_id: str, node_id: str) -> dict | None:
    """The node's latest RUN outcome, or None (never executed / unreadable).

    dev/137: "run" means the sandbox or a validation pass — what the node's
    CODE did. A browser render has its own record (:func:`read_render_record`),
    so this one keeps exactly the meaning every caller since dev/67-2 has read
    it with.
    """
    return _read_json(user_key, project_id, f"{_node_segment(node_id)}.json")


def read_render_record(user_key: str, project_id: str, node_id: str) -> dict | None:
    """What this node's last RENDER did, or None (memo dev/137).

    A grammar node has only this; a code node may have both, and then they
    describe different things — the code's run and the picture it produced.
    """
    return _read_json(
        user_key, project_id, f"{_node_segment(node_id)}{_RENDER_SUFFIX}"
    )


def read_outcome(user_key: str, project_id: str, node_id: str) -> dict | None:
    """The record that best describes this node's last activity (dev/137).

    The RUN when there is one — it carries the artifact, the dataType and the
    traceback — else the render. Callers that want one specific origin ask for
    it by name.
    """
    return (
        read_record(user_key, project_id, node_id)
        or read_render_record(user_key, project_id, node_id)
    )


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
    # dev/137: the RUN's failure first — a traceback is the stronger evidence
    # and the repair loop's historical input — then the render's, which is the
    # only one a grammar node can have (dev/136's branch reads it).
    record = read_record(user_key, project_id, node_id)
    if not isinstance(record, dict) or record.get("status") != "error":
        record = read_render_record(user_key, project_id, node_id)
    if not isinstance(record, dict) or record.get("status") != "error":
        return None
    stderr = str(record.get("stderrTail") or "")
    return {
        "codeSha256": str(record.get("executedCodeSha256") or ""),
        "stderr": stderr[-_FAILURE_STDERR_CHARS:],
        "ranAt": str(record.get("startedAt") or record.get("updatedAt") or ""),
        # dev/135: the record says where it came from; the legacy word "play"
        # is what a sandbox run has always been called in this projection.
        "origin": (
            ORIGIN_BROWSER if record.get("origin") == ORIGIN_BROWSER
            else "validation" if record.get("validation") else "play"
        ),
        # dev/136: so a reader can tell a render that FAILED from one that drew
        # nothing — the corrections differ.
        **({"kind": str(record["kind"])} if record.get("kind") else {}),
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
        # dev/137: a run record wins over a render record for the same node —
        # the runs are read after, so they overwrite the renders' entries.
        renders = sorted(directory.glob(f"*{_RENDER_SUFFIX}"))
        runs = [p for p in sorted(directory.glob("*.json")) if p not in set(renders)]
        for path in [*renders, *runs]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            node_id = data.get("nodeId") if isinstance(data, dict) else None
            if isinstance(node_id, str):
                out[node_id] = {
                    "status": data.get("status"),
                    "updatedAt": data.get("updatedAt"),
                    # dev/135: so a reader can say WHERE a node last ran.
                    "origin": data.get("origin") or (
                        ORIGIN_VALIDATION if data.get("validation") else ORIGIN_SANDBOX
                    ),
                }
    except Exception:
        pass
    return out
