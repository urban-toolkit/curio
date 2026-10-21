/**
 * The Map Edits node (its type id is still `curio.builtin/edit-features`): the
 * features picked on its map removed, put back or given new values. Its code
 * is its only state, one call of the sandbox's `curio_map_edits`
 * (utils/mapEdits/mapEdits), which its body reads and writes
 * (components/mapEdits/MapEditsBody).
 *
 * An edit works like a Parameter value change: it writes the new code into
 * the node, leaves the dataflow unsaved, makes the node stale when its last
 * run succeeded, with every node below it that ran (`autoRunTargets`, the
 * nodes an automatic run takes), and asks for an automatic run. Each Apply,
 * Remove and put back also adds an entry to the node's Provenance drawer at
 * once, holding the code it left, with no run. A new layer or id column only
 * writes the code: what the node hands on is the same. Nothing is written
 * where nobody can save it: the dashboard, a shared view.
 */
import React, { useMemo, useRef } from "react";
import type { NodeBehaviorHook } from "../../registry/types";
import { useFlowContext } from "../../providers/FlowProvider";
import { useProvenanceContext } from "../../providers/ProvenanceProvider";
import { autoRunTargets } from "../../providers/flow/useAutoRun";
import { MapEditsBody } from "../../components/mapEdits/MapEditsBody";
import { mapEditsCode } from "../../utils/mapEdits/mapEdits";
import { failureLine } from "../../utils/runFailure";

export const useMapEditsBehavior: NodeBehaviorHook = (data, nodeState) => {
  const flow = useFlowContext() as any;
  const { nodeEditProv } = useProvenanceContext();
  const writable = !flow?.dashboardOn && flow?.viewerMode !== "shared";

  // The latest writer, so the body (made once per outcome) always writes
  // through the current flow, node state and provenance.
  const write = useRef<(code: string, label?: string) => void>(() => {});
  write.current = (code, label) => {
    if (!writable) return;
    const live = (flow?.nodes ?? []).find((n: any) => n.id === data.nodeId)?.data;
    if (!live) return;
    // The play reads the node's code from here, before its editor floats it.
    nodeState.setCode(code);
    flow.updateDataNode?.(data.nodeId, { ...live, defaultCode: code, code });
    flow.markDirty?.();
    if (nodeState.output?.code === "success") flow.markNodeStale?.(data.nodeId);
    if (label === undefined) return;
    // What the node hands on changes, so every result below it that ran is
    // out of date until a run makes it again.
    const status: Record<string, string> = flow?.nodeExecStatus ?? {};
    for (const id of autoRunTargets([data.nodeId], flow?.nodes ?? [], flow?.edges ?? [])) {
      if (id !== data.nodeId && status[id] === "executed") flow.markNodeStale?.(id);
    }
    // With View > Run stale nodes automatically on, they run on their own.
    flow.requestAutoRun?.([data.nodeId]);
    nodeEditProv(data.nodeId, code, label);
  };

  // NodeEditor opens the Output tab whenever the body's identity changes, so
  // it changes with the node's outcome and nothing else.
  const output = nodeState.output;
  const outcome = output?.code === "success" || output?.code === "error"
    ? `${output.code}:${String(output.content ?? "")}`
    : String(output?.code ?? "");
  const runError = output?.code === "error" ? failureLine(output.content) : null;
  const contentComponent = useMemo(
    () => <MapEditsBody nodeId={data.nodeId} runError={runError} onWrite={(code, label) => write.current(code, label)} />,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data.nodeId, outcome],
  );
  // A node just dropped has no code yet; it gets the code of no edits.
  const fresh = typeof data.defaultCode !== "string" || data.defaultCode === "";
  return {
    contentComponent,
    ...(fresh ? { defaultValueOverride: mapEditsCode({ remove: [], change: [] }) } : {}),
  };
};
