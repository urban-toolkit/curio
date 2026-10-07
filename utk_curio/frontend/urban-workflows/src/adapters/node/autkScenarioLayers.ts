/**
 * A map layer drawn in a scenario's color, with one discrete legend naming
 * each scenario a map draws (Curio's own `scenario` key on a layerRef; the
 * Autark grammar has none).
 *
 * The grammar colors a layer only through a named scheme (`schemeTableau10`,
 * `interpolateBuGn`, ...), so a layer cannot wear the color its scenario wears
 * in the dataflow and in Compare Scenarios' charts. autk-map does take a fixed
 * color for a layer that is not color-mapped (`layerRenderInfo.color`), so a
 * layerRef that names a scenario is drawn in that scenario's color, and the
 * map gets a legend of its own listing every such layer by its scenario's
 * name. autk-map's legend shows one color-mapped layer at a time and these
 * layers are not color-mapped, so it stays hidden for them.
 */
import type { Scenario } from '../../utils/scenarios/scenarioModel';

export const SCENARIO_LEGEND_ATTR = 'data-curio-scenario-legend';

/** One layer drawn in a scenario's color. */
export interface ScenarioLayer {
    dataRef: string;
    color: string;
    label: string;
}

/** The layers of each map that name a scenario this dataflow has, in the
 *  document's order, one list per map. */
export function scenarioLayers(spec: any, scenarios: readonly Scenario[]): ScenarioLayer[][] {
    const maps = spec?.map ? (Array.isArray(spec.map) ? spec.map : [spec.map]) : [];
    return maps.map((mapSpec: any) => {
        const layers: ScenarioLayer[] = [];
        for (const ref of mapSpec?.layerRefs ?? []) {
            if (!ref?.dataRef || typeof ref.scenario !== 'string') continue;
            const scenario = scenarios.find((s) => s.id === ref.scenario);
            if (!scenario) continue;
            layers.push({ dataRef: ref.dataRef, color: scenario.color, label: scenario.name });
        }
        return layers;
    });
}

function rgb(hex: string): { r: number; g: number; b: number; alpha: number } | null {
    const match = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
    if (!match) return null;
    const value = parseInt(match[1], 16);
    return { r: (value >> 16) & 255, g: (value >> 8) & 255, b: value & 255, alpha: 1 };
}

/** The legend: a swatch and a name per scenario, styled as autk-map's own. */
function legendElement(layers: ScenarioLayer[]): HTMLDivElement {
    const legend = document.createElement('div');
    legend.setAttribute(SCENARIO_LEGEND_ATTR, 'true');
    Object.assign(legend.style, {
        position: 'absolute',
        right: '10px',
        bottom: '10px',
        zIndex: '11',
        padding: '8px 12px',
        backgroundColor: '#fff',
        borderRadius: '10px',
        boxShadow: '0 4px 16px rgba(0,0,0,0.15)',
        fontFamily: 'system-ui, sans-serif',
        fontSize: '12px',
        color: '#333',
        pointerEvents: 'none',
    });
    for (const layer of layers) {
        const row = document.createElement('div');
        Object.assign(row.style, { display: 'flex', alignItems: 'center', gap: '8px', lineHeight: '20px' });
        const swatch = document.createElement('span');
        Object.assign(swatch.style, {
            display: 'inline-block',
            width: '18px',
            height: '4px',
            borderRadius: '2px',
            backgroundColor: layer.color,
        });
        const name = document.createElement('span');
        name.textContent = layer.label;
        row.append(swatch, name);
        legend.appendChild(row);
    }
    return legend;
}

/** Draw each layer that names a scenario in its color, and give its map the
 *  scenarios' legend. The grammar keeps each map by the dataRefs it draws
 *  (`_mapRegistry`). */
export function colorScenarioLayers(grammar: any, spec: any, scenarios: readonly Scenario[]): void {
    const registry: Map<string, any> | undefined = grammar?._mapRegistry;
    if (!registry) return;
    for (const layers of scenarioLayers(spec, scenarios)) {
        const drawn = layers.filter((layer) => {
            const map = registry.get(layer.dataRef);
            const color = rgb(layer.color);
            if (!map || !color || typeof map.updateRenderInfo !== 'function') return false;
            map.updateRenderInfo(layer.dataRef, { isColorMap: false, color });
            return true;
        });
        if (drawn.length === 0) continue;
        const host: HTMLElement | null | undefined = registry.get(drawn[0].dataRef)?.canvas?.parentElement;
        if (!host) continue;
        host.querySelector(`[${SCENARIO_LEGEND_ATTR}]`)?.remove();
        // Anchored to the map's own box, as autk-map's legend is.
        if (getComputedStyle(host).position === 'static') host.style.position = 'relative';
        host.appendChild(legendElement(drawn));
    }
}
