import React, { useMemo } from "react";

import { useFlowContext } from "../../providers/FlowProvider";
import type { ScenarioCanvasView } from "../../utils/scenarios/scenarioCanvasView";
import { ScenarioLayers } from "./ScenarioLayers";
import { nodeLabel, outputStatus } from "./scenarioLabels";
import { useScenarioActions } from "./useScenarioActions";

/** The layers on the canvas, reading the flow for labels and outputs. */
export function CanvasScenarioLayers({ view, editable }: { view: ScenarioCanvasView<any, any>; editable: boolean }) {
  const { nodes, nodeExecStatus } = useFlowContext();
  const actions = useScenarioActions();
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  return (
    <ScenarioLayers
      view={view}
      editable={editable}
      labelOf={(id) => nodeLabel(byId.get(id), id)}
      statusOf={(id) => outputStatus(byId.get(id), nodeExecStatus ?? {})}
      onExpand={(id) => actions.setCollapsed(id, false)}
      onCollapse={(id) => actions.setCollapsed(id, true)}
      onMoveBox={actions.moveBox}
    />
  );
}
