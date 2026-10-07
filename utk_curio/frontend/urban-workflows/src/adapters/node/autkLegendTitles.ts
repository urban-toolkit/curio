/**
 * A map legend's title, from a layerRef's `legendTitle`, and whether it shows
 * at all, from its `legend` (Curio's own keys; the Autark grammar has neither).
 *
 * autk-map titles its legend with the layer's id, which on an Autark node is
 * the table its input became (`input_0`), so every legend read "input_0".
 * A layerRef that names a `legendTitle` gets it instead: the map's UI writes
 * the legend over whenever the layer, its domain or its visibility changes
 * (`updateLegendContent`), so the title is put back each time it does. The
 * grammar keeps each map by the dataRefs it draws (`_mapRegistry`).
 *
 * autk-map shows a legend for every layer colored by a value, and the grammar
 * has no fixed color, so a layer colored only to tell it apart from the
 * others (one route of several) still gets a scale nobody reads. A layerRef
 * with `"legend": false` keeps its colors and hides its legend.
 */

const TITLES = Symbol.for('curio.autk.legendTitles');

/** What a document says about each layer's legend, by dataRef. */
interface LegendSettings {
    title?: string;
    hidden?: boolean;
}

function legendSettings(spec: any): Map<string, LegendSettings> {
    const settings = new Map<string, LegendSettings>();
    const maps = spec?.map ? (Array.isArray(spec.map) ? spec.map : [spec.map]) : [];
    for (const mapSpec of maps) {
        for (const ref of mapSpec?.layerRefs ?? []) {
            if (!ref?.dataRef) continue;
            const title = typeof ref.legendTitle === 'string' ? ref.legendTitle.trim() : '';
            const hidden = ref.legend === false;
            if (!title && !hidden) continue;
            settings.set(ref.dataRef, { ...(title ? { title } : {}), ...(hidden ? { hidden } : {}) });
        }
    }
    return settings;
}

/** The legend titles a document names, by dataRef. */
export function legendTitles(spec: any): Map<string, string> {
    const titles = new Map<string, string>();
    for (const [dataRef, { title }] of legendSettings(spec)) {
        if (title) titles.set(dataRef, title);
    }
    return titles;
}

/** Title each legend of the grammar's maps as its layerRef's `legendTitle`
 *  says, and hide the ones whose layerRef says `"legend": false`. */
export function titleLegends(grammar: any, spec: any): void {
    const registry: Map<string, any> | undefined = grammar?._mapRegistry;
    const settings = legendSettings(spec);
    if (!registry || settings.size === 0) return;
    for (const [dataRef, setting] of settings) {
        const ui = registry.get(dataRef)?.ui;
        if (!ui || typeof ui.updateLegendContent !== 'function') continue;
        let byLayer: Map<string, LegendSettings> | undefined = ui[TITLES];
        if (!byLayer) {
            byLayer = new Map();
            const own = byLayer;
            const update = ui.updateLegendContent.bind(ui);
            // autk-map sets the legend's visibility before it writes the
            // legend (`syncLegendVisibility`), so hiding it here, after the
            // write, is the last word.
            ui.updateLegendContent = (...args: any[]) => {
                const result = update(...args);
                const layer = own.get(ui._activeLayer?.layerInfo?.id);
                const legend: HTMLElement | null | undefined = ui._legend;
                const heading = legend?.firstElementChild;
                if (layer?.title && heading) heading.textContent = layer.title;
                if (layer?.hidden && legend) legend.style.visibility = 'hidden';
                return result;
            };
            ui[TITLES] = byLayer;
        }
        byLayer.set(dataRef, setting);
        ui.updateLegendContent();
    }
}
