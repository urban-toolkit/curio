"""What a dataflow shows when its owner opens it: the results it was left with.

Each node a run executes (``run_plan.node_role`` ``run``) shows the newest
output the owner's runs kept (``runs/kept.py``) under the key the saved
dataflow gives its step: its code as a run sends it, its input as the nodes
above it are restored, the owner's packages and the datasets its code reads.
A node with no such output shows its saved output, as before; past the kept
outputs' days, or after Curio changes version, every node does.

The nodes are walked in a run's order (``run_engine.plan_run``), so a node's
input is what the nodes above it show: one a run forwards hands its input on,
and one only the browser makes (an Autark compute node, a Spatial Join) leaves
the nodes below it nothing to key, its data being the tab's. Nothing runs and
nothing is written.
"""
from __future__ import annotations

import json

from utk_curio.backend.app.runs import kept


def _datasets_by_node(codes: dict, project_id: str, owner) -> dict:
    """``{node id: dataset identities}`` (``kept.datasets_read``) for each
    code in *codes*, every dataset they name resolved in one pass, as a run
    resolves a node's (``node_exec.resolve_dataset_paths``)."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code
    from utk_curio.backend.app.datasets.infrastructure import left_out_files
    from utk_curio.backend.app.execution.node_exec import MAX_EXEC_DATASET_IDS, resolve_dataset_ids

    named = {node_id: dataset_ids_in_code(code, limit=MAX_EXEC_DATASET_IDS) for node_id, code in codes.items()}
    # A shipped dataset a pip install leaves out is fetched as it resolves;
    # one that cannot be is left out, as a run leaves it.
    with left_out_files.failures():
        paths = resolve_dataset_ids(
            sorted({dataset_id for ids in named.values() for dataset_id in ids}), project_id, owner,
        )
    return {
        node_id: kept.datasets_read(
            codes[node_id], project_id, owner,
            paths={dataset_id: paths[dataset_id] for dataset_id in ids if dataset_id in paths},
        )
        for node_id, ids in named.items()
    }


def last_results(owner, user_key: str, project_id: str, spec: dict, saved: list) -> list:
    """The outputs *project_id* opens with for its owner, as ``OutputRef``s:
    *saved*, each node that the owner's runs kept a result for under its key
    showing the newest such result instead."""
    from utk_curio.backend.app.execution.node_names import template_labels
    from utk_curio.backend.app.execution.run_engine import (
        PlanError,
        node_input,
        passed_on,
        plan_run,
        sent_code,
    )
    from utk_curio.backend.app.packages.service import roster_templates
    from utk_curio.backend.app.projects.schemas import OutputRef
    from utk_curio.backend.app.projects.template_grammars import TemplateGrammars

    entries = kept.owner_outputs_by_key(project_id)
    if not entries or not isinstance(spec, dict):
        return list(saved)
    try:
        plan = plan_run(
            spec, templates=roster_templates(user_key, project_id),
            labels=template_labels(user_key, project_id),
            packages=TemplateGrammars.for_account(user_key),
        )
    except PlanError:
        return list(saved)

    sent, codes = {}, {}
    for node_id, step in plan.steps.items():
        if step.role != "run":
            continue
        try:
            sent[node_id] = sent_code(plan, step)
            # An Autark document is keyed by the JavaScript it compiles to.
            codes[node_id] = kept.step_call(plan, step, sent[node_id], None).code
        except Exception:  # noqa: BLE001 - a node whose code does not resolve or compile is not keyed
            sent.pop(node_id, None)
    datasets = _datasets_by_node(codes, project_id, owner)
    packages = kept.packages_fingerprint(user_key)
    saved_by_node = {ref.node_id: ref for ref in saved}
    outputs: dict = {}
    shown: dict = {}
    for level in plan.levels:
        for node_id in level:
            step = plan.steps[node_id]
            input_ref = None if step.autk_data else node_input(plan.spec, node_id, outputs)
            if step.role == "forward":
                if input_ref is not None:
                    outputs[node_id] = input_ref
                continue
            if step.role != "run":
                continue
            entry = None
            # A node waiting on a missing input has nothing to key.
            if node_id in sent and (input_ref is not None or step.autk_data or not plan.spec.upstream_nodes(node_id)):
                call = kept.step_call(plan, step, sent[node_id], input_ref)
                entry = entries.get(kept.call_key(
                    call, packages=packages, node_type=step.node_type, datasets=datasets[node_id],
                ))
            if entry is not None:
                output = json.loads(entry.output or "{}")
                shown[node_id] = OutputRef(
                    node_id=node_id, filename=entry.output_path, data_type=output.get("dataType") or "",
                )
                outputs[node_id] = passed_on(output)
            elif node_id in saved_by_node:
                ref = saved_by_node[node_id]
                outputs[node_id] = {"path": ref.filename, "dataType": ref.data_type or ""}
    restored = [shown.get(ref.node_id, ref) for ref in saved]
    return restored + [ref for node_id, ref in shown.items() if node_id not in saved_by_node]
