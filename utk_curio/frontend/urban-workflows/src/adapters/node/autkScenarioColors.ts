/**
 * A map layer drawn in its scenario's color (#662). On a map outside every
 * scenario box, a layer whose input comes from a node in a box is handed to the
 * grammar with autk-grammar's `color` set to the box's color, the color of the
 * box on the canvas, as a Vega-Lite chart reading `inputs` draws its rows. The
 * box's color replaces the layer's one color, whether the layerRef writes one
 * or not, and a layer with a `color` shows no legend.
 *
 * A layer colored by its values keeps them: one that reads a value (`getFnv`)
 * with no color of its own over it, or with `isColorMap`, and a raster's, whose
 * cells are always colored by value. autk-grammar would drop such a layer's
 * color map for the one color.
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
 * feeding the input it came in on. *circles* says where each table came in
 * (utils/autkInput): its input's circle, with several inputs wired. With one,
 * every table is that input's, whatever its place among the layers the input
 * carries. None at all for a map in a box.
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
        if (circle === undefined) return null;
        return byPosition[byPosition.length === 1 ? 0 : circle] ?? null;
    };
}

/** Whether *ref* is colored by its values: it reads one, and no color it writes draws it instead. */
function colorsByValue(ref: any): boolean {
    const readsValue = typeof ref?.getFnv === 'string' && ref.getFnv.trim() !== '';
    return readsValue && (ref.color === undefined || ref.isColorMap === true);
}

/**
 * *spec* with each layerRef whose table comes from a box in the box's color,
 * but for a layer colored by its values and a raster's, one of *rasters*.
 */
export function withScenarioColors(spec: any, scenarioOf: LayerScenario, rasters: ReadonlySet<string> = new Set()): any {
    if (!spec?.map) return spec;
    let changed = false;
    const colored = (mapSpec: any) => {
        const layerRefs = Array.isArray(mapSpec?.layerRefs) ? mapSpec.layerRefs : null;
        if (!layerRefs) return mapSpec;
        const refs = layerRefs.map((ref: any) => {
            const table = typeof ref?.dataRef === 'string' ? ref.dataRef : null;
            if (table === null || rasters.has(table) || colorsByValue(ref)) return ref;
            const scenario = scenarioOf(table);
            if (!scenario) return ref;
            changed = true;
            return { ...ref, color: scenario.color };
        });
        return { ...mapSpec, layerRefs: refs };
    };
    const map = Array.isArray(spec.map) ? spec.map.map(colored) : colored(spec.map);
    return changed ? { ...spec, map } : spec;
}
