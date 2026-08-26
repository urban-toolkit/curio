"""Deterministic node validation over the headless runner (memo dev/67-7).

Three roles, never blurred: the RUNNER executes, THIS module decides with
boring deterministic checks, the model only corrects (services' round loop)
and the user approves. The goal/intent is reported as evidence for human
judgment — never machine-judged.

Verdicts:
- ``pass`` — the upstream slice ran through the target; the target produced
  an output whose runtime data type is compatible with every consumer's
  declared input types (fail-open when a consumer's template is out of scope).
- ``fail`` — the target (``execution-error``), an upstream node
  (``upstream-blocker``), a precondition (cycle/bound/missing node), or a
  ``type-mismatch`` with a named consumer.
- ``infrastructure`` — the sandbox was unreachable: never a content failure;
  the caller leaves the node's state untouched.
"""

from __future__ import annotations

from utk_curio.backend.app.execution import runner

# Sandbox runtime dataType → template port type vocabulary. Unmapped types
# skip the compatibility check (fail-open — honesty over false alarms).
_RUNTIME_TO_PORT_TYPE = {
    "dataframe": "DATAFRAME",
    "geodataframe": "GEODATAFRAME",
    "list": "LIST",
    "dict": "JSON",
    "json": "JSON",
    "int": "VALUE",
    "float": "VALUE",
    "str": "VALUE",
    "bool": "VALUE",
    "raster": "RASTER",
}


def _strip_type_version(node_type: str) -> str:
    return node_type.split("@", 1)[0] if isinstance(node_type, str) else node_type


def _consumer_type_mismatch(
    spec_dict: dict, node_id: str, output_data_type: str, available: dict | None
) -> str | None:
    """A named mismatch between the target's RUNTIME output type and a
    consumer's DECLARED input types (dev/67-3 arity metadata), or None."""
    if not available:
        return None
    port_type = _RUNTIME_TO_PORT_TYPE.get((output_data_type or "").lower())
    if port_type is None:
        return None  # unmapped runtime type: fail open
    dataflow = (spec_dict or {}).get("dataflow") or {}
    nodes = {n.get("id"): n for n in dataflow.get("nodes") or [] if isinstance(n, dict)}
    for edge in dataflow.get("edges") or []:
        if not isinstance(edge, dict) or edge.get("source") != node_id:
            continue
        if edge.get("type") == "Interaction":
            continue
        consumer = nodes.get(edge.get("target")) or {}
        entry = available.get(_strip_type_version(str(consumer.get("type") or "")))
        if entry is None:
            continue  # out-of-scope template: fail open
        declared: set[str] = set()
        for port in entry.get("inputs") or []:
            declared.update(t.upper() for t in port.get("types") or [])
        if not declared:
            continue
        if port_type not in declared:
            label = (consumer.get("goal") or edge.get("target") or "?")
            return (
                f"the output type {output_data_type!r} is not accepted by "
                f"downstream node {str(label)[:60]!r} (declares "
                f"{', '.join(sorted(declared))})"
            )
    return None


def validate_candidate(
    user_key: str,
    project_id: str,
    spec_dict: dict,
    node_id: str,
    candidate_content: str,
    *,
    session_id: str | None = None,
    exec_fn=None,
    progress=None,
    available_templates: dict | None = None,
) -> dict:
    """Run the dataflow through *node_id* with the candidate overlaid and
    return ``{"verdict", "evidence"}`` (see module docstring)."""
    report = runner.run_through_node(
        user_key, project_id, spec_dict, node_id,
        candidate_content=candidate_content,
        session_id=session_id, exec_fn=exec_fn, progress=progress,
    )
    executed = [nid for nid, rec in report["nodes"].items() if rec.get("executed")]
    dataflow = (spec_dict or {}).get("dataflow") or {}
    node = next(
        (n for n in dataflow.get("nodes") or []
         if isinstance(n, dict) and n.get("id") == node_id),
        {},
    )
    evidence: dict = {
        "order": report["order"],
        "executedNodes": executed,
        "goal": str(node.get("goal") or "")[:300],
    }
    if report.get("infrastructure"):
        evidence.update({"kind": "infrastructure", "detail": report["infrastructure"]})
        return {"verdict": "infrastructure", "evidence": evidence}
    target_record = report["nodes"].get(node_id) or {}
    if not report["ok"]:
        blocker = report.get("blocker")
        if blocker and blocker != node_id:
            blocker_record = report["nodes"].get(blocker) or {}
            blocker_node = next(
                (n for n in dataflow.get("nodes") or []
                 if isinstance(n, dict) and n.get("id") == blocker),
                {},
            )
            evidence.update({
                "kind": "upstream-blocker",
                "blocker": blocker,
                "blockerLabel": str(blocker_node.get("goal") or blocker)[:60],
                "stderrTail": blocker_record.get("stderrTail", ""),
                "detail": report.get("error"),
            })
        elif blocker == node_id:
            evidence.update({
                "kind": "execution-error",
                "stderrTail": target_record.get("stderrTail", ""),
                "detail": report.get("error"),
            })
        else:
            evidence.update({"kind": "precondition", "detail": report.get("error")})
        return {"verdict": "fail", "evidence": evidence}
    output_data_type = (target_record.get("output") or {}).get("dataType", "")
    evidence["outputDataType"] = output_data_type
    # Successful runs may still carry benign warnings — evidence, not verdict.
    if target_record.get("stderrTail"):
        evidence["warnings"] = target_record["stderrTail"][-1000:]
    mismatch = _consumer_type_mismatch(
        spec_dict, node_id, output_data_type, available_templates
    )
    if mismatch:
        evidence.update({"kind": "type-mismatch", "detail": mismatch})
        return {"verdict": "fail", "evidence": evidence}
    evidence["kind"] = "executed"
    return {"verdict": "pass", "evidence": evidence}
