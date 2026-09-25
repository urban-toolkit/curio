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
- ``infrastructure``; ``not-executable`` (dev/118 → dev/119: the target's template has no code the sandbox could run — nothing executed, nothing claimed) — the sandbox was unreachable: never a content failure;
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
    from utk_curio.backend.app.execution import runtime_journal

    absent = (output_data_type or "").strip().lower() in runtime_journal.NULL_OUTPUT_TYPES
    port_type = _RUNTIME_TO_PORT_TYPE.get((output_data_type or "").lower())
    if port_type is None and not absent:
        return None  # unmapped runtime type: fail open
    # dev/138: an ABSENT output is not an unmapped one. `return None` types as
    # "null", which has no port — and taking the fail-open path for it let the
    # owner's `edd71e67` write a node that produced nothing and call it solved.
    # A type this build does not recognize still fails open, just above.
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
        if absent:
            label = (consumer.get("goal") or edge.get("target") or "?")
            return (
                "the code returned no output (None), which downstream node "
                f"{str(label)[:60]!r} cannot accept (it declares "
                f"{', '.join(sorted(declared))}) — return the data this node "
                "produces, or, if it cannot be produced from these inputs, say "
                "so in one line instead of returning code"
            )
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
    dataset_paths: dict | None = None,
    exec_user_key: str | None = None,
    secrets: dict | None = None,
    prior_outputs: dict | None = None,
    templates: dict | None = None,
) -> dict:
    """Run the dataflow through *node_id* with the candidate overlaid and
    return ``{"verdict", "evidence"}`` (see module docstring). dev/115:
    ``dataset_paths`` / ``exec_user_key`` ride through to the runner so the
    Data Catalog's ``curio_dataset_path("<id>")`` loaders resolve exactly as
    on Play."""
    report = runner.run_through_node(
        user_key, project_id, spec_dict, node_id,
        candidate_content=candidate_content,
        session_id=session_id, exec_fn=exec_fn, progress=progress,
        dataset_paths=dataset_paths, exec_user_key=exec_user_key, secrets=secrets,
        prior_outputs=prior_outputs,
        strict_upstream=True,  # dev/118: an empty upstream is a blocker, never None downstream
        templates=templates,  # dev/119: the roster classifies executability
    )
    executed = [nid for nid, rec in report["nodes"].items() if rec.get("executed")]
    reused = [nid for nid, rec in report["nodes"].items() if rec.get("status") == "reused"]
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
    if reused:
        # dev/118 commit 4: which ancestors stood in by their earlier output.
        evidence["reusedNodes"] = reused
    if report.get("infrastructure"):
        evidence.update({"kind": "infrastructure", "detail": report["infrastructure"]})
        return {"verdict": "infrastructure", "evidence": evidence}
    if report.get("notExecutable"):
        # dev/118 (DEC-075): a browser-rendered kind. Not a failure of the
        # content and not a pass — a labeled outcome with nothing executed.
        evidence.update({"kind": "not-executable", "detail": report.get("error")})
        return {"verdict": "not-executable", "evidence": evidence}
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
            if report.get("upstreamEmpty"):
                # dev/118: the upstream has no content — nothing to correct
                # here; the dependent waits for it.
                evidence["upstreamEmpty"] = True
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
    # dev/118 commit 4: the artifact record a dependent's validation may reuse
    # for this node within the same batch (an id in the sandbox store — plain
    # data, never content).
    if isinstance(target_record.get("output"), dict) and target_record["output"].get("path"):
        evidence["output"] = {"path": target_record["output"]["path"], "dataType": output_data_type}
    if target_record.get("durationMs") is not None:
        evidence["durationMs"] = target_record["durationMs"]
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
