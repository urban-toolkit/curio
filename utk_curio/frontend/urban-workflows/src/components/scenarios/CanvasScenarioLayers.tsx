import React, { useMemo } from "react";

import { useFlowContext } from "../../providers/FlowProvider";
import type { ScenarioCanvasView } from "../../utils/scenarios/scenarioCanvasView";
import { CanvasCursors } from "../collab/CanvasCursors";
import { ScenarioLayers } from "./ScenarioLayers";
import { nodeKind, nodeLabel, outputStatus } from "./scenarioLabels";
import { useScenarioActions } from "./useScenarioActions";

/** The layers on the canvas: the scenarios', reading the flow for labels and
 *  outputs, and everyone else's pointer. On a read-only canvas (not
 *  *editable*) scenarios and shared groups stay as they are drawn: nothing
 *  collapses, expands or moves them. */
export function CanvasScenarioLayers({ view, editable }: { view: ScenarioCanvasView<any, any>; editable: boolean }) {
  const { nodes, nodeExecStatus, scenarioSets } = useFlowContext();
  const setNames = useMemo(() => new Map((scenarioSets ?? []).map((s) => [s.id, s.name])), [scenarioSets]);
  const actions = useScenarioActions();
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  return (
    <>
      <ScenarioLayers
        view={view}
        editable={editable}
        labelOf={(id) => nodeLabel(byId.get(id), id)}
        typeOf={(id) => nodeKind(byId.get(id))}
        statusOf={(id) => outputStatus(byId.get(id), nodeExecStatus ?? {})}
        onExpand={editable ? (id) => actions.setCollapsed(id, false) : undefined}
        onCollapse={editable ? (id) => actions.setCollapsed(id, true) : undefined}
        onMoveBox={actions.moveBox}
        setNameOf={(id) => (id ? setNames.get(id) : undefined)}
        onSharedCollapse={editable ? actions.setSharedCollapsed : undefined}
        onSharedMove={actions.moveSharedBox}
      />
      <CanvasCursors />
    </>
  );
}
