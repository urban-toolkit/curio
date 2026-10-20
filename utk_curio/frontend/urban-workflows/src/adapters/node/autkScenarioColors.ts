/**
 * A map layer drawn in its scenario's color (#662). On a map outside every
 * scenario box, a layer whose input comes from a node in a box is handed to the
 * grammar with autk-grammar's `color` set to the box's color, the color of the
 * box on the canvas, as a Vega-Lite chart reading `inputs` draws its rows. The
 * box's color wins over a `color` the layerRef writes, and a layer with a
 * `color` shows no legend.
 *
 * A map inside a box draws its layers as written, so a scenario's own maps keep
 * their colors; so does a layer whose input comes from no box, or whose table
 * is no input's.
 */
import type { Scenario } from '../../utils/scenarios/scenarioModel';
import { inputScenarios, scenarioOfNode } from '../../utils/scenarios/inputScenarios';

type FlowNodeLike = { id: string; type?: string | null; data?: any };
type FlowEdgeLike = { source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null };

/** The box a map layer's table comes from, by the table's name, or null. */
export type LayerScenario = (table: string) => Scenario | null;

/**
 * The box each table of the map node *nodeId* comes from: the box of the node
 * feeding the input it came in on, *circles* saying which input that is
 * (utils/autkInput). None at all for a map in a box.
 */
export function layerScenarios(
    nodeId: string,
    nodes: readonly FlowNodeLike[],
    edges: readonly FlowEdgeLike[],
    scenarios: readonly Scenario[],
    circles: Readonly<Record<string, number>>,
): LayerScenario {
    if (scenarios.length === 0 || scenarioOfNode(nodeId, nodes, scenarios)) return () => null;
    // In the order the input's circles arrive in: one per wired circle.
    const byPosition = inputScenarios(nodeId, nodes, edges, scenarios).map((input) => input.scenario);
    return (table) => {
        const circle = Object.prototype.hasOwnProperty.call(circles, table) ? circles[table] : undefined;
        return circle === undefined ? null : byPosition[circle] ?? null;
    };
}

/** *spec* with each layerRef whose table comes from a box in the box's color. */
export function withScenarioColors(spec: any, scenarioOf: LayerScenario): any {
    if (!spec?.map) return spec;
    let changed = false;
    const colored = (mapSpec: any) => {
        const layerRefs = Array.isArray(mapSpec?.layerRefs) ? mapSpec.layerRefs : null;
        if (!layerRefs) return mapSpec;
        const refs = layerRefs.map((ref: any) => {
            const scenario = typeof ref?.dataRef === 'string' ? scenarioOf(ref.dataRef) : null;
            if (!scenario) return ref;
            changed = true;
            return { ...ref, color: scenario.color };
        });
        return { ...mapSpec, layerRefs: refs };
    };
    const map = Array.isArray(spec.map) ? spec.map.map(colored) : colored(spec.map);
    return changed ? { ...spec, map } : spec;
}
