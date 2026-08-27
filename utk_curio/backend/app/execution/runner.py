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
from utk_curio.backend.app.execution.workflow_spec import (
    PY_CODE_TYPES,
    WorkflowSpec,
    parse_workflow_dict,
)

SANDBOX_CONNECT_TIMEOUT_S = 30
SANDBOX_GET_TIMEOUT_S = int(os.environ.get("CURIO_E2E_SANDBOX_GET_TIMEOUT", "300"))
SANDBOX_EXEC_TIMEOUT_S = 120
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
        timeout=(SANDBOX_CONNECT_TIMEOUT_S, SANDBOX_GET_TIMEOUT_S),
    )
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


def _http_exec(endpoint: str, payload: dict) -> dict:
    """POST one node execution to the sandbox; raises on transport failure
    (the caller maps that to an INFRASTRUCTURE outcome, never a node error)."""
    import requests as _req

    resp = _req.post(
        f"{_sandbox_url()}{endpoint}",
        json=payload,
        timeout=SANDBOX_EXEC_TIMEOUT_S,
    )
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
) -> dict:
    """Execute the dataflow's ancestor slice THROUGH *node_id* and report
    per-node outcomes (memo dev/67-7).

    - ``candidate_content`` overlays the target's content in memory — the
      saved spec is NEVER mutated here; only an approved Apply writes.
    - Every sandbox execution best-effort-writes the runtime journal with
      ``validation=True``.
    - Stops at the first failed node: downstream results would be
      meaningless. An upstream failure reports that node as ``blocker``.
    - Transport failures are INFRASTRUCTURE, never node errors: ``ok`` is
      False with ``infrastructure`` set and no node blamed.

    Returns ``{ok, target, order, nodes: {id: {status, stderrTail,
    stdoutTail, output, executed}}, blocker, infrastructure, error}``.
    """
    exec_fn = exec_fn or _http_exec
    spec = parse_workflow_dict(spec_dict)
    by_id = {n.id: n for n in spec.nodes}
    report: dict = {
        "ok": False,
        "target": node_id,
        "order": [],
        "nodes": {},
        "blocker": None,
        "infrastructure": None,
        "error": None,
    }
    if node_id not in by_id:
        report["error"] = f"node {node_id!r} is not in the saved dataflow"
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
    for index, node in enumerate(ordered):
        if progress is not None:
            progress(node.id, index, len(ordered))
        content_text = node.content
        if candidate_content is not None and node.id == node_id:
            content_text = candidate_content
        is_code = node.category == "code"
        is_py = node.type in PY_CODE_TYPES
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
        endpoint = "/exec" if is_py else "/execJs"
        try:
            result = exec_fn(endpoint, payload)
        except Exception as exc:
            # Sandbox down / transport error: infrastructure, never the node.
            report["infrastructure"] = str(exc)[:300]
            report["error"] = f"sandbox unreachable: {str(exc)[:300]}"
            return report
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
        }
        report["nodes"][node.id] = record
        runtime_journal.record_execution(
            user_key, project_id, node.id,
            code=content_text, stdout=stdout_raw, stderr=stderr_text, output=out,
            started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            duration_ms=0, validation=as_validation,
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
