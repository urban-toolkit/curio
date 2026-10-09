/**
 * A grammar after a run, keeping the maps it drew as autk-grammar 4.1.0 does,
 * for the tests of what Curio does with them (adapters/node/autkMapDrawing,
 * autkMapView, autkRasters, autkLegendTitles). `maps` holds the map drawn for
 * each `map` entry of the document, in order. `_mapRegistry`, the grammar's
 * private registry, holds one map for each table a layerRef names: the last
 * map that draws it, so a map whose tables a later map also draws is not in it.
 */
export type GrammarThatRan = { maps: any[]; _mapRegistry: Map<string, any> };

/** The grammar after it ran *spec* and drew *drawn*, one map for each of its `map` entries. */
export function grammarThatRan(spec: any, ...drawn: any[]): GrammarThatRan {
    const entries: any[] = spec?.map ? (Array.isArray(spec.map) ? spec.map : [spec.map]) : [];
    const maps: any[] = [];
    const registry = new Map<string, any>();
    entries.forEach((entry, index) => {
        const map = drawn[index];
        for (const layerRef of entry?.layerRefs ?? []) registry.set(layerRef?.dataRef, map);
        maps[index] = map;
    });
    return { maps, _mapRegistry: registry };
}
