/**
 * A map layer drawn in its scenario's color. A layerRef that names a scenario
 * of the dataflow (`"scenario": "<its id>"`, Curio's own key) is handed to the
 * grammar with autk-grammar's `color` set to the scenario's, the color of its
 * box on the canvas, as Compare Scenarios' charts draw it. The scenario's color
 * wins over a `color` the layerRef writes, and a layer with a `color` shows no
 * legend. A layerRef that names no scenario of the dataflow is handed on as
 * written.
 */
import type { Scenario } from '../../utils/scenarios/scenarioModel';

/** *spec* with each layerRef that names one of *scenarios* in its color. */
export function withScenarioColors(spec: any, scenarios: readonly Scenario[]): any {
    if (!spec?.map || scenarios.length === 0) return spec;
    const colors = new Map(scenarios.map((scenario) => [scenario.id, scenario.color]));
    let changed = false;
    const colored = (mapSpec: any) => {
        const layerRefs = Array.isArray(mapSpec?.layerRefs) ? mapSpec.layerRefs : null;
        if (!layerRefs) return mapSpec;
        const refs = layerRefs.map((ref: any) => {
            const color = typeof ref?.scenario === 'string' ? colors.get(ref.scenario) : undefined;
            if (!color) return ref;
            changed = true;
            return { ...ref, color };
        });
        return { ...mapSpec, layerRefs: refs };
    };
    const map = Array.isArray(spec.map) ? spec.map.map(colored) : colored(spec.map);
    return changed ? { ...spec, map } : spec;
}
