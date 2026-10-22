/**
 * The Interaction node (#662; its type id is still
 * `curio.builtin/edit-features`): features of a layer picked on the Autark
 * map it feeds, or by a condition, removed, restored or given new values.
 *
 * Its code is its only state: one call of the sandbox's
 * `curio_edit_features` (`utils/editFeatures/editFeatures`), which its body
 * reads on every render and writes for each change. A change writes the new
 * code into the node, leaves the dataflow Unsaved, makes the node stale when
 * its last run succeeded, with every node below it that ran
 * (`autoRunTargets`, the nodes an automatic run takes), and adds an entry to
 * the node's Provenance drawer at once, holding the code it left. A run then
 * applies the new edits, in the browser or on the server, as any Python
 * node's code runs, and Commit edits in the body starts one. Undo and Redo put
 * back an entry's code and file none. Nothing is written where nobody can
 * save it: the dashboard, a shared view.
 *
 * Fed by several data nodes, its code hands the step all of them, one per
 * circle, and hands on every layer by name (`editFeaturesCode`'s *circles*).
 */
import React, { useEffect, useMemo, useRef } from "react";
import type { NodeBehaviorHook } from "../../registry/types";
import { useFlowContext } from "../../providers/FlowProvider";
import { useProvenanceContext } from "../../providers/ProvenanceProvider";
import { autoRunTargets } from "../../providers/flow/useAutoRun";
import { EditFeaturesBody, type CodeWrite } from "../../components/editFeatures/EditFeaturesBody";
import { editFeaturesCode, readEditFeaturesCode } from "../../utils/editFeatures/editFeatures";
import { circlesInto, nodeCode } from "../../utils/editFeatures/mapLayerEdits";
import { failureLine } from "../../utils/runFailure";

export const useEditFeaturesBehavior: NodeBehaviorHook = (data, nodeState) => {
  const flow = useFlowContext() as any;
  const { nodeEditProv } = useProvenanceContext();
  // Nothing is written where nobody can save it: the dashboard, a shared view.
  const writable = !flow?.dashboardOn && flow?.viewerMode !== "shared";
  // The code hands the step every circle that feeds the node.
  const circles = circlesInto(data.nodeId, flow?.edges ?? []);

  // The latest writer, so the body (made once per outcome) always writes
  // through the current flow, node state and provenance.
  const write = useRef<(code: string, change?: CodeWrite) => void>(() => {});
  write.current = (code, change = {}) => {
    if (!writable) return;
    const live = (flow?.nodes ?? []).find((n: any) => n.id === data.nodeId)?.data;
    if (!live) return;
    const before = nodeCode(live);
    if (code === before) return;
    // The play reads the node's code from here, before its editor floats it.
    nodeState.setCode(code);
    flow.updateDataNode?.(data.nodeId, { ...live, defaultCode: code, code });
    if (change.quiet) return;
    flow.markDirty?.();
    if (nodeState.output?.code === "success") flow.markNodeStale?.(data.nodeId);
    // What the node hands on changes, so every result below it that ran is
    // out of date until Commit edits, or another run, makes it again.
    const status: Record<string, string> = flow?.nodeExecStatus ?? {};
    for (const id of autoRunTargets([data.nodeId], flow?.nodes ?? [], flow?.edges ?? [])) {
      if (id !== data.nodeId && status[id] === "executed") flow.markNodeStale?.(id);
    }
    if (change.label !== undefined) nodeEditProv(data.nodeId, code, change.label, before);
  };

  // An input connected or taken off: the code hands the step its circles.
  // Only code the node reads is written again, and only for another number of
  // circles; nothing else changes, so it is no entry of the node's history.
  useEffect(() => {
    if (!writable) return;
    const live = (flow?.nodes ?? []).find((n: any) => n.id === data.nodeId)?.data;
    if (!live) return;
    const read = readEditFeaturesCode(nodeCode(live));
    if ("problem" in read || read.circles === undefined || read.circles === circles) return;
    write.current(editFeaturesCode(read.settings, circles, read.comments), { quiet: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [circles]);

  // NodeEditor opens the Output tab whenever the body's identity changes, so
  // it changes with the node's outcome and nothing else.
  const output = nodeState.output;
  const outcome = output?.code === "success" || output?.code === "error"
    ? `${output.code}:${String(output.content ?? "")}`
    : String(output?.code ?? "");
  const runError = output?.code === "error" ? failureLine(output.content) : null;
  const contentComponent = useMemo(
    () => <EditFeaturesBody nodeId={data.nodeId} runError={runError} onWrite={(code, change) => write.current(code, change)} />,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data.nodeId, outcome],
  );
  // A node just dropped has no code yet; it gets the code of an empty list.
  const fresh = typeof data.defaultCode !== "string" || data.defaultCode === "";
  return {
    contentComponent,
    ...(fresh ? { defaultValueOverride: editFeaturesCode(undefined, circles) } : {}),
  };
};
