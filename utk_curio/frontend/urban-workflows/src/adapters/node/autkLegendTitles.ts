/**
 * A map legend's title, from a layerRef's `legendTitle` (Curio's own key; the
 * Autark grammar has none).
 *
 * autk-map titles its legend with the layer's id, which on an Autark node is
 * the table its input became (`input_0`), so every legend read "input_0".
 * A layerRef that names a `legendTitle` gets it instead. A layer of an input
 * that names none is titled with the column it is coloured by (`getFnv`), as
 * a Vega-Lite legend is titled with its field; a table the document names
 * (`table_osm_roads`) keeps its name. The map's UI writes the legend over
 * whenever the layer, its domain or its visibility changes
 * (`updateLegendContent`), so the title is put back each time it does. The
 * grammar keeps each map by the dataRefs it draws (`_mapRegistry`).
 */
import { INPUT_TABLE_PREFIX } from '../../generated/autkGrammar';

const TITLES = Symbol.for('curio.autk.legendTitles');

/** Whether *dataRef* is the table a node's input became: `input_0`, `input_1`, ... */
function isInputTable(dataRef: string): boolean {
    const position = dataRef.startsWith(INPUT_TABLE_PREFIX) ? dataRef.slice(INPUT_TABLE_PREFIX.length) : '';
    return /^\d+$/.test(position);
}

/** The column a layer of an input is coloured by, when it shows a legend. */
function mappedColumn(ref: any): string {
    if (ref?.isColorMap === false || typeof ref?.getFnv !== 'string') return '';
    if (typeof ref.dataRef !== 'string' || !isInputTable(ref.dataRef)) return '';
    return ref.getFnv.trim().replace(/^properties\./, '');
}

/** The legend titles a document names, by dataRef. */
export function legendTitles(spec: any): Map<string, string> {
    const titles = new Map<string, string>();
    const maps = spec?.map ? (Array.isArray(spec.map) ? spec.map : [spec.map]) : [];
    for (const mapSpec of maps) {
        for (const ref of mapSpec?.layerRefs ?? []) {
            const title = (typeof ref?.legendTitle === 'string' ? ref.legendTitle.trim() : '') || mappedColumn(ref);
            if (ref?.dataRef && title) titles.set(ref.dataRef, title);
        }
    }
    return titles;
}

/** Title each legend of the grammar's maps as its layerRef's `legendTitle` says. */
export function titleLegends(grammar: any, spec: any): void {
    const registry: Map<string, any> | undefined = grammar?._mapRegistry;
    const titles = legendTitles(spec);
    if (!registry || titles.size === 0) return;
    for (const [dataRef, title] of titles) {
        const ui = registry.get(dataRef)?.ui;
        if (!ui || typeof ui.updateLegendContent !== 'function') continue;
        let byLayer: Map<string, string> | undefined = ui[TITLES];
        if (!byLayer) {
            byLayer = new Map();
            const own = byLayer;
            const update = ui.updateLegendContent.bind(ui);
            ui.updateLegendContent = (...args: any[]) => {
                const result = update(...args);
                const name = own.get(ui._activeLayer?.layerInfo?.id);
                const heading = ui._legend?.firstElementChild;
                if (name && heading) heading.textContent = name;
                return result;
            };
            ui[TITLES] = byLayer;
        }
        byLayer.set(dataRef, title);
        ui.updateLegendContent();
    }
}
