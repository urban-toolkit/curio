/**
 * An Autark node's views, as its run reads them: a list of maps and a list of
 * plots, each known by the key autk-grammar knows it by.
 *
 * A document's `map` and `plot` are each one object or a list; either way the
 * run reads a list (`mapEntries`, `plotEntries`), in the document's order,
 * which is the order autk-grammar draws them in (its `maps`). A map's key is
 * its `id`, else its index, autk-grammar's `MapId`: its `map:picking` events
 * name a map by it, and its calls that address one map (`highlightOnMap`,
 * `mapLayer`, ...) take it, a string by `id` and a number by index. A plot's
 * key is its `id`, else its `dataRef`, which its `plot:selection` events name
 * it by and its plot calls take (`plotKey`).
 *
 * Every per-view step of a run reads them here: each map's layers lit on that
 * map alone (`lightMaps`), a pick read from the map that picked
 * (`autkMapState.pickOn`), a brush from the plot that brushed (`plotEntryOf`),
 * the views a redraw keeps (`autkMapView.keepMapViews`) and a raster's edges
 * bled on each map (`autkRasters.bleedRasterEdges`).
 */

/** *value* as a list: none is an empty list, and one object a list of one. */
function asList(value: unknown): any[] {
    if (value === undefined || value === null) return [];
    return Array.isArray(value) ? value : [value];
}

/** The maps *spec* draws, in its order: a `map` written as one object is the one entry. */
export function mapEntries(spec: any): any[] {
    return asList(spec?.map);
}

/** The plots *spec* draws, in its order: a `plot` written as one object is the one entry. */
export function plotEntries(spec: any): any[] {
    return asList(spec?.plot);
}

/** The key autk-grammar knows the map *entry*, at *index* of its document, by: its `id`, else its index. */
export function mapKey(entry: any, index: number): string | number {
    return typeof entry?.id === 'string' ? entry.id : index;
}

/** The key autk-grammar knows the plot *entry* by: its `id`, else its `dataRef`. */
export function plotKey(entry: any): string {
    return typeof entry?.id === 'string' && entry.id !== '' ? entry.id : entry?.dataRef;
}

/**
 * The index of the map *mapId* names in *spec*, as autk-grammar addresses one:
 * a number by its index, a string by its `id`; -1 when it names none.
 */
export function mapIndexOf(spec: any, mapId: unknown): number {
    const entries = mapEntries(spec);
    if (typeof mapId === 'number') return Number.isInteger(mapId) && mapId >= 0 && mapId < entries.length ? mapId : -1;
    if (typeof mapId === 'string') return entries.findIndex((entry, index) => mapKey(entry, index) === mapId);
    return -1;
}

/** The plot *plotId* names in *spec* (its `id`, else its `dataRef`), with its index; null when it names none. */
export function plotEntryOf(spec: any, plotId: unknown): { index: number; entry: any } | null {
    const index = plotEntries(spec).findIndex((entry) => plotKey(entry) === plotId);
    return index < 0 ? null : { index, entry: plotEntries(spec)[index] };
}

/** The table of the map *entry*'s own picking layer: its first layer that picks (`isPick`), else its first. */
export function pickLayerOf(entry: any): string | undefined {
    const refs: any[] = Array.isArray(entry?.layerRefs) ? entry.layerRefs : [];
    return refs.find((ref) => ref?.isPick)?.dataRef ?? refs[0]?.dataRef;
}

/** A view a selection was made in: a map or a plot of the document, by its place among the views of its kind. */
export type DrawnView = { kind: 'map' | 'plot'; index: number; entry: any };

/** A layer a map of the document draws, with the map's index and entry. */
export type MapLayerRef = { index: number; entry: any; ref: any };

/** Every layer each map of *spec* draws, the maps in order and each map's layers in order. */
export function mapLayerRefs(spec: any): MapLayerRef[] {
    return mapEntries(spec).flatMap((entry, index) =>
        (Array.isArray(entry?.layerRefs) ? entry.layerRefs : []).map((ref: any) => ({ index, entry, ref })));
}

/**
 * Light each layer of each map of *spec* with the positions *positionsOf*
 * gives it (asked once a layer, with the layer's place in `mapLayerRefs`), on
 * its own map alone: each call names the map by its index, so two maps that
 * draw one table, in one workspace or in two, light only their own rows. A
 * layer with no position lit is cleared, on its map alone too.
 */
export function lightMaps(
    grammar: any,
    spec: any,
    positionsOf: (layer: MapLayerRef, at: number) => number[],
): void {
    mapLayerRefs(spec).forEach((layer, at) => {
        const positions = positionsOf(layer, at);
        if (positions.length === 0) grammar?.clearHighlightOnMap?.(layer.ref.dataRef, layer.index);
        else grammar?.highlightOnMap?.(layer.ref.dataRef, positions, layer.index);
    });
}
