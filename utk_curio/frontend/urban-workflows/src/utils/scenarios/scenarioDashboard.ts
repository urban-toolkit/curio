/**
 * The dashboard by scenario (#662): which column each pinned tile goes in.
 *
 * - First the tiles the scenarios share: their shared context, and any other
 *   pinned tile outside every scenario that is no shared outcome.
 * - Then one column per scenario, in the scenarios' order, holding its pinned
 *   nodes.
 * - Last the scenarios' shared outcomes (`scenarioParts`), such as a
 *   comparison.
 *
 * In each column, upstream tiles come first (Run All's levels), then by their
 * place on the canvas. Each scenario's column is also a frame, which the page
 * draws with a header in the scenario's color.
 */
import { computeTopologicalLevels } from "../../providers/flow/runLevels";
import type { ScenarioFrame } from "./scenarioCanvasView";
import type { Scenario } from "./scenarioModel";
import { liveScenarios, scenarioParts } from "./scenarioParts";

type FlowNodeLike = {
  id: string;
  type?: string | null;
  position?: { x: number; y: number };
  data?: any;
};
type FlowEdgeLike = {
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
};

export interface ScenarioDashboard {
  /** Pinned tile ids, one list per column, left to right. */
  columns: string[][];
  /** Each scenario with a pinned tile, and its pinned tiles. */
  frames: ScenarioFrame[];
}

/** Where a node sits on the canvas, also once the dashboard has moved it. */
function canvasPlace(node: FlowNodeLike): { x: number; y: number } {
  return node.data?.workflowPosition ?? node.position ?? { x: 0, y: 0 };
}

/**
 * The columns and frames of a dashboard laid out by scenario, or null when no
 * pinned tile belongs to a scenario: the dashboard then keeps its usual layout.
 */
export function scenarioDashboard(
  nodes: readonly FlowNodeLike[],
  edges: readonly FlowEdgeLike[],
  pins: { [id: string]: boolean },
  scenarios: readonly Scenario[] | null | undefined,
): ScenarioDashboard | null {
  if (!scenarios || scenarios.length === 0) return null;
  const live = liveScenarios(scenarios, nodes);

  const memberOf = new Map<string, Scenario>();
  for (const scenario of live) {
    for (const id of scenario.nodes) if (!memberOf.has(id)) memberOf.set(id, scenario);
  }
  const pinned = nodes.filter((node) => pins[node.id]);
  if (!pinned.some((node) => memberOf.has(node.id))) return null;

  // The scenarios' shared outcomes, which go last.
  const outcomes = new Set(live.flatMap((scenario) => scenarioParts(scenario, nodes, edges, live).outcomes));

  const ids = new Set(nodes.map((node) => node.id));
  const between = edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));
  const levels = computeTopologicalLevels(nodes as any, between as any);
  const rank = new Map<string, number>();
  levels.forEach((ids, level) => ids.forEach((id) => rank.set(id, level)));
  const ordered = (group: FlowNodeLike[]) =>
    [...group]
      .sort((a, b) => {
        const byLevel = (rank.get(a.id) ?? levels.length) - (rank.get(b.id) ?? levels.length);
        if (byLevel !== 0) return byLevel;
        const pa = canvasPlace(a);
        const pb = canvasPlace(b);
        return pa.y - pb.y || pa.x - pb.x;
      })
      .map((node) => node.id);

  const shared = pinned.filter((node) => !memberOf.has(node.id) && !outcomes.has(node.id));
  const after = pinned.filter((node) => !memberOf.has(node.id) && outcomes.has(node.id));
  const frames: ScenarioFrame[] = [];
  for (const scenario of live) {
    const members = ordered(pinned.filter((node) => memberOf.get(node.id) === scenario));
    if (members.length > 0) frames.push({ scenario, members });
  }

  const columns = [ordered(shared), ...frames.map((frame) => frame.members), ordered(after)];
  return { columns: columns.filter((column) => column.length > 0), frames };
}
