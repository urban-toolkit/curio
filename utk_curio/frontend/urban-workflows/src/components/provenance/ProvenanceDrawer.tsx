import React from "react";
import { HeaderDrawer } from "../layout/HeaderDrawer";
import { useFlowContext } from "../../providers/FlowProvider";
import type { NodeProvenanceTarget } from "../../providers/provenanceDrawerContext";
import { resolveNodeDisplayLabel } from "../../utils/palettePackageFactoryDraft";
import { DataflowProvenance } from "./DataflowProvenance";
import { NodeRunsProvenance } from "./NodeRunsProvenance";

/** Whose history the drawer shows: the dataflow's versions, or a node's runs. */
export type ProvenanceTarget = { kind: "dataflow" } | ({ kind: "node" } & NodeProvenanceTarget);

export interface ProvenanceDrawerProps {
  presented: boolean;
  onRequestClose: () => void;
  onExitComplete: () => void;
  target: ProvenanceTarget;
}

/**
 * The provenance drawer: a dataflow's versions or a node's runs, on the right
 * with the catalog drawers' pin and width, listed as Curio's Nest lists work.
 */
export function ProvenanceDrawer({ presented, onRequestClose, onExitComplete, target }: ProvenanceDrawerProps) {
  const { workflowNameRef, nodes } = useFlowContext();
  const node = target.kind === "node" ? target : null;
  // The node's name as its header shows it now, so a rename shows at once;
  // the one it opened with while the canvas holds no data for it.
  const live = node ? nodes?.find((n) => n.id === node.nodeId)?.data : undefined;
  const nodeName = live?.nodeType ? resolveNodeDisplayLabel({ nodeType: live.nodeType, title: live.title }) : node?.title;
  return (
    <HeaderDrawer
      presented={presented}
      onRequestClose={onRequestClose}
      onExitComplete={onExitComplete}
      title={node ? "Node provenance" : "Dataflow provenance"}
      titleId="provenance-drawer-title"
      name="provenance"
      subtitle={node ? `Runs of ${nodeName}` : `Versions of ${workflowNameRef.current || "Untitled dataflow"}`}
      pinnable
      wide={false}
    >
      {node ? (
        <NodeRunsProvenance
          key={node.nodeId}
          nodeId={node.nodeId}
          restore={node.restore}
          showCode={node.showCode}
          onNodeGone={onRequestClose}
        />
      ) : (
        <DataflowProvenance key="dataflow" />
      )}
    </HeaderDrawer>
  );
}

export default ProvenanceDrawer;
