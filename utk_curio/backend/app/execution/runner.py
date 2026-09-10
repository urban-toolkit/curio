"""The headless dataflow runner (memo dev/67-7) — promoted from the Playwright
test utilities, generalized from raise-on-first-failure to accumulate-and-
report so agents can validate candidate content by ACTUALLY running the
dataflow through a node.

Execution semantics are byte-equivalent with the e2e runner (which imports
this module through a shim): topological order over data-flow edges, merge
``in_N`` input assembly, widget-placeholder resolution, deterministic
seeding, pass-through for browser-only node types, and the canonical failure
predicate ``output.path == ""`` (benign warnings land in stderr on successful
runs — stderr-nonempty is NEVER the predicate).

``run_through_node`` adds the validation entry: the target's ancestor slice
only, an in-memory candidate-content overlay (the saved spec is never
mutated), per-node runtime-journal records (marked ``validation``), and
honest structured failure — including naming an UPSTREAM blocker instead of
blaming the node under validation.
"""

from __future__ import annotations

import os
import re
import textwrap
import time

from utk_curio.backend.app.execution import runtime_journal
from utk_curio.backend.app.execution.sandbox_auth import sandbox_headers
from utk_curio.backend.app.execution.workflow_spec import (
    PY_CODE_TYPES,
    WorkflowSpec,
    parse_workflow_dict,
)

SANDBOX_CONNECT_TIMEOUT_S = 30
SANDBOX_GET_TIMEOUT_S = int(os.environ.get("CURIO_E2E_SANDBOX_GET_TIMEOUT", "300"))
# dev/115: ONE execution timeout for validation runs, aligned to the sandbox's
# own wall clock (supervisor DEFAULT_WALL_TIMEOUT_SECONDS = 300) — the old
# hardcoded 120 s cut every real data fetch short of the limit the sandbox
# itself would have enforced. Env-overridable; the interactive route's 600 s
# stays the upper reference.
DEFAULT_EXEC_TIMEOUT_S = 300
SANDBOX_EXEC_TIMEOUT_S = DEFAULT_EXEC_TIMEOUT_S  # kept name; read via exec_timeout_s()


def exec_timeout_s() -> int:
    """The per-node sandbox execution timeout for validation runs, in seconds
    (``CURIO_VALIDATION_EXEC_TIMEOUT``; an unusable value falls back to the
    default rather than raising — a bad env var must not break every run)."""
    raw = os.environ.get("CURIO_VALIDATION_EXEC_TIMEOUT")
    if raw is None or not str(raw).strip():
        return DEFAULT_EXEC_TIMEOUT_S
    try:
        value = int(str(raw).strip())
    except ValueError:
        return DEFAULT_EXEC_TIMEOUT_S
    return value if value > 0 else DEFAULT_EXEC_TIMEOUT_S


class ExecutionTimeout(Exception):
    """dev/115: the sandbox did not answer within the execution timeout.

    Distinct from a transport failure on purpose: a node that hangs (a fetch
    without a timeout, an endpoint that never answers) is the CANDIDATE's
    behaviour and must be reported as the node's failure so the correction
    loop can fix it — never as ``infrastructure``, which leaves the node
    untouched and teaches nothing."""

    def __init__(self, seconds: int):
        super().__init__(f"the node did not finish within {seconds} s")
        self.seconds = seconds


# A validation run is a bounded, interactive slice — not a batch platform.
VALIDATION_NODE_LIMIT = 25
_STDERR_TAIL_CHARS = 4000


def _sandbox_url() -> str:
    host = os.environ.get("FLASK_SANDBOX_HOST", "127.0.0.1")
    port = int(os.environ.get("FLASK_SANDBOX_PORT", "2000"))
    return f"http://{host}:{port}"


def load_artifact_as_dict(artifact_id: str) -> dict:
    """Fetch a stored artifact from the sandbox and return its parsed representation."""
    import requests as _req

    resp = _req.get(
        f"{_sandbox_url()}/get",
        params={"fileName": artifact_id},
        headers=sandbox_headers(),
        timeout=(SANDBOX_CONNECT_TIMEOUT_S, SANDBOX_GET_TIMEOUT_S),
    )
    if resp.status_code == 401:
        raise RuntimeError(_SANDBOX_REJECTED.format(path="/get"))
    if not resp.ok:
        raise AssertionError(
            f"sandbox /get fileName={artifact_id} -> {resp.status_code}\n"
            f"{resp.text[:2000]}"
        )
    result = resp.json()
    # No `json.loads(json.dumps(result, default=str))` round-trip: it is a no-op
    # that costs two extra copies of the whole artifact. `resp.json()` has
    # already parsed the body, so every value is JSON-native and `default` can
    # never fire. It matters here because this runs on the agent node-validation
    # path, against whatever a user's node produced - the e2e harness had the
    # same line and died with MemoryError on the largest example dataflow.
    result.pop("filename", None)  # artifact ID varies per execution run
    return result


#: dev/127: how much of a preview the BACKEND will hold. The sandbox bounds
#: rows; this bounds bytes, because a geodataframe's GeoJSON can be large even
#: at five rows and the comment on ``load_artifact_as_dict`` records what an
#: unbounded read once cost (MemoryError on the largest example dataflow).
ARTIFACT_PREVIEW_MAX_BYTES = 512_000
ARTIFACT_PREVIEW_MAX_ROWS = 5


def load_artifact_preview(
    artifact_id: str,
    *,
    max_rows: int = ARTIFACT_PREVIEW_MAX_ROWS,
    max_bytes: int = ARTIFACT_PREVIEW_MAX_BYTES,
) -> dict | None:
    """A BOUNDED preview of a stored artifact, or None (memo dev/127).

    ``GET /get?fileName=…&maxRows=n`` is the sandbox's own preview path (it
    reads the row cap out of duckdb for tabular artifacts). The response is
    streamed and abandoned past *max_bytes*, so whatever the sandbox chooses to
    serialize cannot cost the backend its memory: an oversized preview is
    reported as no preview, which the caller states as an absent schema rather
    than as a guess.

    Never raises: an unreachable sandbox, a 401, a 500 or a body that is not
    JSON all return None.
    """
    import json as _json

    import requests as _req

    try:
        with _req.get(
            f"{_sandbox_url()}/get",
            params={"fileName": artifact_id, "maxRows": int(max_rows)},
            headers=sandbox_headers(),
            timeout=(SANDBOX_CONNECT_TIMEOUT_S, SANDBOX_GET_TIMEOUT_S),
            stream=True,
        ) as resp:
            if not resp.ok:
                return None
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_content(chunk_size=32_768):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    return None  # too big to describe cheaply: no schema
                chunks.append(chunk)
        payload = _json.loads(b"".join(chunks).decode("utf-8", "replace"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


_SEED_PREFIX = (
    "import numpy as _np; _np.random.seed({seed}); "
    "import random as _rnd; _rnd.seed({seed})\n"
)


def seed_node_code(code: str, seed: int = 42) -> str:
    """Prepend deterministic random-seed lines to *code*.

    Underscore-prefixed aliases (``_np``, ``_rnd``) never shadow the user's
    own ``import numpy as np``.
    """
    return _SEED_PREFIX.format(seed=seed) + code


_WIDGET_RE = re.compile(r"\[!!\s*(.*?)\s*!!\]")


def resolve_widget_placeholders(code: str) -> str:
    """Replace ``[!! name$type$default !!]`` widget markers with defaults —
    exactly as the frontend does before posting to the sandbox."""

    def _replace(m):
        parts = m.group(1).split("$")
        if len(parts) >= 3:
            return parts[2]
        return m.group(0)

    return _WIDGET_RE.sub(_replace, code)


#: The sandbox answered 401: the two processes disagree about the shared
#: secret. Named, so the infrastructure verdict tells the operator what to fix
#: instead of a bare ``401 Client Error``.
_SANDBOX_REJECTED = (
    "the sandbox rejected the backend on {path}: the two processes disagree "
    "about CURIO_SANDBOX_TOKEN — this usually means one of them was started "
    "outside 'curio start' or was restarted without the other"
)


def _http_exec(endpoint: str, payload: dict) -> dict:
    """POST one node execution to the sandbox; raises on transport failure
    (the caller maps that to an INFRASTRUCTURE outcome, never a node error).
    Carries the sandbox shared secret like the API bridge does."""
    import requests as _req

    seconds = exec_timeout_s()
    try:
        resp = _req.post(
            f"{_sandbox_url()}{endpoint}",
            json=payload,
            headers=sandbox_headers(),
            timeout=(SANDBOX_CONNECT_TIMEOUT_S, seconds),
        )
    except _req.exceptions.Timeout as exc:  # dev/115: the node's behaviour, not ours
        raise ExecutionTimeout(seconds) from exc
    if resp.status_code == 401:
        raise RuntimeError(_SANDBOX_REJECTED.format(path=endpoint))
    resp.raise_for_status()
    return resp.json()


def _resolve_input(spec: WorkflowSpec, node_id: str, outputs: dict) -> tuple[str, str]:
    """Mirror ``process_python_code``'s input resolution (single upstream =
    direct ref; fan-in = stringified outputs list the worker evals back)."""
    upstreams = spec.upstream_nodes(node_id)
    if not upstreams:
        return "", ""
    if len(upstreams) == 1:
        up = outputs.get(upstreams[0]) or {}
        if up.get("dataType") == "outputs":
            return str(up.get("path")), "outputs"
        return up.get("path", ""), up.get("dataType", "")
    return str([outputs[uid] for uid in upstreams if uid in outputs]), "outputs"


def _ancestor_slice(spec: WorkflowSpec, target_id: str) -> set[str]:
    """The target + every data-flow ancestor (reverse BFS — the server twin
    of ``playNodesUpTo``'s subgraph selection)."""
    predecessors: dict[str, list[str]] = {}
    for edge in spec.edges:
        if edge.get("type") == "Interaction":
            continue
        predecessors.setdefault(edge["target"], []).append(edge["source"])
    wanted = {target_id}
    frontier = [target_id]
    while frontier:
        node_id = frontier.pop()
        for source in predecessors.get(node_id, []):
            if source not in wanted:
                wanted.add(source)
                frontier.append(source)
    return wanted


def run_through_node(
    user_key: str,
    project_id: str,
    spec_dict: dict,
    node_id: str,
    *,
    candidate_content: str | None = None,
    seed: int = 42,
    session_id: str | None = None,
    exec_fn=None,
    node_limit: int = VALIDATION_NODE_LIMIT,
    progress=None,
    as_validation: bool = True,
    dataset_paths: dict | None = None,
    exec_user_key: str | None = None,
    secrets: dict | None = None,
    prior_outputs: dict | None = None,
    strict_upstream: bool = False,
    templates: dict | None = None,
) -> dict:
    """Execute the dataflow's ancestor slice THROUGH *node_id* and report
    per-node outcomes (memo dev/67-7).

    dev/115: ``dataset_paths`` (``{datasetId: absolutePath}`` for the code's
    ``curio_dataset_path("<id>")`` calls) and ``exec_user_key`` ride the
    payload exactly as the interactive ``/processPythonCode`` sends them —
    without them the Data Catalog's portable loader form failed under
    validation while working on Play. A sandbox execution timeout is the
    NODE's failure (``ExecutionTimeout`` → error record, blocker), never
    infrastructure.

    - ``candidate_content`` overlays the target's content in memory — the
      saved spec is NEVER mutated here; only an approved Apply writes.
    - Every sandbox execution best-effort-writes the runtime journal with
      ``validation=True``.
    - Stops at the first failed node: downstream results would be
      meaningless. An upstream failure reports that node as ``blocker``.
    - Transport failures are INFRASTRUCTURE, never node errors: ``ok`` is
      False with ``infrastructure`` set and no node blamed.

    Returns ``{ok, target, order, nodes: {id: {status, stderrTail,
    stdoutTail, output, executed}}, blocker, infrastructure, error,
    notExecutable}``. ``notExecutable`` (dev/118): the TARGET's kind runs in
    the browser, not the sandbox — nothing was executed and nothing is
    claimed; the caller reports a labeled outcome, never a pass.
    """
    exec_fn = exec_fn or _http_exec
    spec = parse_workflow_dict(spec_dict, templates=templates)
    by_id = {n.id: n for n in spec.nodes}
    report: dict = {
        "ok": False,
        "target": node_id,
        "order": [],
        "nodes": {},
        "blocker": None,
        "infrastructure": None,
        "error": None,
        "notExecutable": False,
    }
    if node_id not in by_id:
        report["error"] = f"node {node_id!r} is not in the saved dataflow"
        return report
    target = by_id[node_id]
    if target.category != "code":
        # dev/118: the overlay used to be computed and then skipped with the
        # rest of the pass-through handling, ending ``ok: True`` — a "pass" on
        # content nobody ran. Refuse first, by name.
        report["notExecutable"] = True
        report["error"] = (
            f"node {node_id!r} ({target.raw_type}) has no code the sandbox could run — "
            "it works in the browser or through its own service; Play the dataflow to see it"
        )
        return report
    wanted = _ancestor_slice(spec, node_id)
    ordered = [n for n in spec.topo_sorted_nodes() if n.id in wanted]
    # Kahn appends cycle remnants at the end — a remnant with unexecuted
    # data dependencies means a cycle in the slice: refuse honestly.
    seen: set[str] = set()
    for node in ordered:
        for upstream in spec.upstream_nodes(node.id):
            if upstream in wanted and upstream not in seen:
                report["error"] = (
                    f"the upstream slice contains a cycle through {node.id!r} — "
                    "validation needs an acyclic dataflow"
                )
                return report
        seen.add(node.id)
    if len(ordered) > node_limit:
        report["error"] = (
            f"the upstream slice has {len(ordered)} nodes (validation bound "
            f"{node_limit}) — run the dataflow manually instead"
        )
        return report
    report["order"] = [n.id for n in ordered]
    outputs: dict[str, dict] = {}
    prior_outputs = dict(prior_outputs or {})
    for index, node in enumerate(ordered):
        if progress is not None:
            progress(node.id, index, len(ordered))
        if node.id != node_id and node.id in prior_outputs and isinstance(prior_outputs[node.id], dict):
            # dev/118 (DEC-075) commit 4: an ancestor that PASSED earlier in
            # this batch — its recorded output stands in for a re-run. The
            # target itself always runs. A vanished artifact surfaces on the
            # target's input load; the caller retries once without reuse.
            outputs[node.id] = dict(prior_outputs[node.id])
            report["nodes"][node.id] = {"status": "reused", "executed": False, "output": outputs[node.id]}
            continue
        content_text = node.content
        if candidate_content is not None and node.id == node_id:
            content_text = candidate_content
        is_code = node.category == "code"
        is_py = node.engine != "javascript"  # dev/119: the template's engine routes the run
        if strict_upstream and is_code and node.id != node_id and not (content_text or "").strip():
            # dev/118 live fix (2026-09-09), VALIDATION runs only: an upstream
            # code node with NO content used to run as a seed-only body, hand
            # None downstream, and let a dependent "pass" by coding around
            # None — a hollow pass. It is a blocker, by name, before anything
            # runs. A plain Run (dev/71) keeps Play's semantics: it runs what
            # is there.
            report["nodes"][node.id] = {"status": "empty", "executed": False}
            report["blocker"] = node.id
            report["upstreamEmpty"] = True
            report["error"] = (
                f"upstream node {node.id!r} has no content yet — solve or fill it first"
            )
            return report
        if not is_code:
            # Pass-through semantics (merge/vis/pool) — same as the e2e runner.
            upstreams = spec.upstream_nodes(node.id)
            if len(upstreams) == 1 and upstreams[0] in outputs:
                outputs[node.id] = outputs[upstreams[0]]
            elif len(upstreams) > 1:
                outputs[node.id] = {
                    "path": [outputs[uid] for uid in upstreams if uid in outputs],
                    "dataType": "outputs",
                }
            report["nodes"][node.id] = {"status": "pass-through", "executed": False}
            continue
        file_path, data_type = _resolve_input(spec, node.id, outputs)
        resolved = resolve_widget_placeholders(content_text)
        seeded = seed_node_code(resolved, seed)
        payload = {
            "code": textwrap.indent(seeded, "    "),
            "file_path": file_path,
            "nodeType": node.raw_type,
            "dataType": data_type,
            # Validation runs never auto-install computed datasets.
            "save_dataset": False,
        }
        if session_id:
            payload["session_id"] = session_id
        if dataset_paths:
            payload["dataset_paths"] = dict(dataset_paths)
        if exec_user_key:
            payload["user_key"] = exec_user_key
        if secrets:
            # dev/116: the connection keys the candidate names, resolved by the
            # caller in the request thread; the sandbox injects curio_secret().
            payload["secrets"] = dict(secrets)
        endpoint = "/exec" if is_py else "/execJs"
        started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        t0 = time.monotonic()
        try:
            result = exec_fn(endpoint, payload)
        except ExecutionTimeout as exc:
            # dev/115: a hang is the candidate's behaviour — reported as the
            # node's own failure so the correction loop sees it.
            result = {
                "stdout": [],
                "stderr": (
                    f"{exc} (sandbox execution timeout) — the code hung or the "
                    "request has no timeout; add one and bound the fetch"
                ),
                "output": {"path": "", "dataType": ""},
            }
        except Exception as exc:
            # Sandbox down / transport error: infrastructure, never the node.
            report["infrastructure"] = str(exc)[:300]
            report["error"] = f"sandbox unreachable: {str(exc)[:300]}"
            return report
        duration_ms = int((time.monotonic() - t0) * 1000)
        out = result.get("output") or {}
        ok = bool(str(out.get("path") or ""))
        stderr_text = str(result.get("stderr") or "")
        stdout_raw = result.get("stdout")
        stdout_text = (
            "\n".join(str(line) for line in stdout_raw)
            if isinstance(stdout_raw, list)
            else str(stdout_raw or "")
        )
        record = {
            "status": "ok" if ok else "error",
            "executed": True,
            "stderrTail": stderr_text[-_STDERR_TAIL_CHARS:],
            "stdoutTail": stdout_text[-2000:],
            "output": {
                "path": str(out.get("path") or ""),
                "dataType": str(out.get("dataType") or ""),
            },
            "durationMs": duration_ms,
        }
        report["nodes"][node.id] = record
        runtime_journal.record_execution(
            user_key, project_id, node.id,
            code=content_text, stdout=stdout_raw, stderr=stderr_text, output=out,
            started_at=started_at,
            duration_ms=duration_ms, validation=as_validation,
        )
        if not ok:
            report["blocker"] = node.id
            report["error"] = (
                f"node {node.id!r} failed"
                if node.id == node_id
                else f"upstream node {node.id!r} failed before the target ran"
            )
            return report
        outputs[node.id] = {"path": out["path"], "dataType": out["dataType"]}
    report["ok"] = True
    return report
