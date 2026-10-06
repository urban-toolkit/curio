/**
 * The Edit Features node (#662): features of a layer picked on the node's map
 * and removed, given a value or restored, kept as a list of edits at
 * `metadata.editFeatures` (`utils/editFeatures/editFeatures`).
 *
 * Its code is written for it from that list: one call of the sandbox's
 * `curio_edit_features`, which applies the edits by the column that
 * identifies a feature and hands on a new artifact. A change of the list
 * writes the list and the code together and makes the node stale; a run then
 * applies the new list, in the browser or on the server, as any Python node's
 * code runs.
 */
import React, { useMemo, useRef } from "react";
import type { NodeBehaviorHook } from "../../registry/types";
import { useFlowContext } from "../../providers/FlowProvider";
import { EditFeaturesBody } from "../../components/editFeatures/EditFeaturesBody";
import { editFeaturesCode, normalizeEditFeatures, type EditFeaturesSettings } from "../../utils/editFeatures/editFeatures";
import { failureLine } from "./compareScenariosBehavior";

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
