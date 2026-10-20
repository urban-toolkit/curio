/**
 * The Interaction node (#662; its type id is still
 * `curio.builtin/edit-features`): features of a layer picked on the node's
 * map, or by a condition, removed, restored or given new values, kept as an
 * edit log at `metadata.editFeatures` (`utils/editFeatures/editFeatures`).
 *
 * Its code is written for it from that log: one call of the sandbox's
 * `curio_edit_features`, which applies the edits by the column that
 * identifies a feature and hands on a new artifact. A change of the log
 * writes the log and the code together and makes the node stale, with every
 * node below it that ran (`autoRunTargets`, the nodes an automatic run
 * takes); a run then applies the new log, in the browser or on the server,
 * as any Python node's code runs, and Update results in the body starts one.
 */
import React, { useMemo, useRef } from "react";
import type { NodeBehaviorHook } from "../../registry/types";
import { useFlowContext } from "../../providers/FlowProvider";
import { autoRunTargets } from "../../providers/flow/useAutoRun";
import { EditFeaturesBody } from "../../components/editFeatures/EditFeaturesBody";
import { editFeaturesCode, normalizeEditFeatures, type EditFeaturesSettings } from "../../utils/editFeatures/editFeatures";
import { failureLine } from "../../utils/runFailure";

export const useEditFeaturesBehavior: NodeBehaviorHook = (data, nodeState) => {
  const flow = useFlowContext() as any;
  // Nothing is written where nobody can save it: the dashboard, a shared view.
  const writable = !flow?.dashboardOn && flow?.viewerMode !== "shared";

  // The latest writer, so the body (made once per outcome) always writes
  // through the current flow and node state.
  const write = useRef<(next: EditFeaturesSettings | undefined) => void>(() => {});
  write.current = (next) => {
    if (!writable) return;
    const live = (flow?.nodes ?? []).find((n: any) => n.id === data.nodeId)?.data;
    if (!live) return;
    const settings = normalizeEditFeatures(next);
    const code = editFeaturesCode(settings);
    // The play reads the node's code from here, before its editor floats it.
    nodeState.setCode(code);
    flow.updateDataNode?.(data.nodeId, { ...live, editFeatures: settings, defaultCode: code, code });
    if (nodeState.output?.code === "success") flow.markNodeStale?.(data.nodeId);
    // What the node hands on changes, so every result below it that ran is
    // out of date until Update results, or another run, makes it again.
    const status: Record<string, string> = flow?.nodeExecStatus ?? {};
    for (const id of autoRunTargets([data.nodeId], flow?.nodes ?? [], flow?.edges ?? [])) {
      if (id !== data.nodeId && status[id] === "executed") flow.markNodeStale?.(id);
    }
  };

  // NodeEditor opens the Output tab whenever the body's identity changes, so
  // it changes with the node's outcome and nothing else.
  const output = nodeState.output;
  const outcome = output?.code === "success" || output?.code === "error"
    ? `${output.code}:${String(output.content ?? "")}`
    : String(output?.code ?? "");
  const runError = output?.code === "error" ? failureLine(output.content) : null;
  const contentComponent = useMemo(
    () => <EditFeaturesBody nodeId={data.nodeId} runError={runError} onChange={(next) => write.current(next)} />,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data.nodeId, outcome],
  );
  // A node just dropped has no code yet; it gets the code of an empty list.
  const fresh = typeof data.defaultCode !== "string" || data.defaultCode === "";
  return {
    contentComponent,
    ...(fresh ? { defaultValueOverride: editFeaturesCode(undefined) } : {}),
  };
};
