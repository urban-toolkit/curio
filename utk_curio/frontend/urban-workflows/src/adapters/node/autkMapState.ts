/**
 * What a person set on an Autark map, kept across a redraw (#662).
 *
 * An edit made in the Interaction node linked to the map draws the map
 * again (a new grammar, a new map). The camera is kept already; this keeps
 * what was set on each layer through the map's own menu: hidden or shown,
 * its opacity, colors and color map, borders, point and line sizes. A layer
 * is matched by its id, the table it draws, so a new layer starts as the
 * document draws it, and a layer gone is forgotten.
 */
import { grammarMaps } from './autkMapDrawing';

/** The render settings of a layer a person can change, by layer id. */
export type MapLayerState = Record<string, Record<string, unknown>>;

const KEPT = ['isSkip', 'opacity', 'showBorders', 'isColorMap', 'color', 'strokeColor', 'pointSize', 'polylinesWidth'] as const;

function layersOf(map: any): any[] {
    const layers = map?.layerManager?.layers;
    return Array.isArray(layers) ? layers : [];
}

const idOf = (layer: any): string | undefined => {
    const id = layer?.layerInfo?.id;
    return typeof id === 'string' && id ? id : undefined;
};

/**
 * The id the map gives the layer that draws *table*: autk-grammar 4.2 names a
 * layer by its `title` when it has one, else by its `dataRef`. A lookup by
 * table name alone misses every titled layer, and showing one layer alone then
 * hid them all. *spec* is the document drawn; its `dataRef` may still be the
 * code's `[!! input_k !!]` form.
 */
export function layerIdFor(spec: any, table: string): string {
    const maps = spec?.map ? (Array.isArray(spec.map) ? spec.map : [spec.map]) : [];
    const bare = (ref: unknown) => String(ref ?? '').replace(/^\[!!\s*(.*?)\s*!!\]$/, '$1');
    for (const map of maps) {
        for (const ref of map?.layerRefs ?? []) {
            if (bare(ref?.dataRef) !== table) continue;
            return typeof ref?.title === 'string' && ref.title.trim() !== '' ? ref.title : table;
        }
    }
    return table;
}

/**
 * The settings of each layer the first map of *grammar* draws, before a layer
 * is shown alone: with which one a click selects (`isPick`), which a redraw
 * does not keep, since an edit's own pick sets it.
 */
export function snapshotBeforeSolo(grammar: unknown): MapLayerState | null {
    const state = snapshotMapLayers(grammar);
    const picking = idOf(grammarMaps(grammar)[0]?.activePickingLayer);
    if (state && picking && state[picking]) state[picking] = { ...state[picking], isPick: true };
    return state;
}

/** The settings of each layer the first map of *grammar* draws. */
export function snapshotMapLayers(grammar: unknown): MapLayerState | null {
    const map = grammarMaps(grammar)[0];
    if (!map) return null;
    const out: MapLayerState = {};
    for (const layer of layersOf(map)) {
        const id = idOf(layer);
        const info = layer?.layerRenderInfo;
        if (!id || !info) continue;
        const kept: Record<string, unknown> = {};
        for (const key of KEPT) if (info[key] !== undefined) kept[key] = info[key];
        // The color map as configured; its domain comes from the new data.
        if (info.colormap?.config) kept.colormap = { ...info.colormap.config };
        out[id] = kept;
    }
    return out;
}

/** Put *state* back on the layers of *map* that have the same id. */
export function restoreMapLayers(map: any, state: MapLayerState | null): void {
    if (!map || !state) return;
    for (const layer of layersOf(map)) {
        const id = idOf(layer);
        const kept = id ? state[id] : undefined;
        if (!id || !kept) continue;
        const { colormap, ...renderInfo } = kept;
        try {
            if (Object.keys(renderInfo).length > 0) map.updateRenderInfo(id, renderInfo);
            if (colormap && typeof map.updateColorMap === 'function') map.updateColorMap(id, { colorMap: colormap });
        } catch (error) {
            // A setting the new layer cannot take is left as the document draws it.
            console.warn('[autk-map] keeping a layer setting across a redraw failed:', id, error);
        }
    }
    map.requestRender?.();
}

/**
 * Show *table* alone on *map*, as the map's own menu would: the only layer
 * shown, the only one in its color map (when it has one, *colorMapped*) and
 * the one a click selects. With null, each layer gets back what it had in
 * *state*, or is shown with no color map.
 */
export function soloMapLayer(
    map: any,
    table: string | null,
    state: MapLayerState | null = null,
    colorMapped = false,
): void {
    if (!map) return;
    const set = (id: string, info: Record<string, unknown>) => {
        try {
            map.updateRenderInfo(id, info);
        } catch {
            // A layer that cannot take it stays as it is.
        }
    };
    let picking: string | null = null;
    for (const layer of layersOf(map)) {
        const id = idOf(layer);
        if (!id) continue;
        if (table !== null) {
            set(id, { isSkip: id !== table, isColorMap: id === table && colorMapped });
            continue;
        }
        // Back to what the person had, or shown.
        const own = state?.[id];
        set(id, { isSkip: own?.isSkip === true, ...(own && 'isColorMap' in own ? { isColorMap: own.isColorMap === true } : {}) });
        if (own?.isPick === true) picking = id;
    }
    // One picking layer at a time: setting it takes picking off the others.
    if (table !== null) set(table, { isPick: true });
    else if (picking) set(picking, { isPick: true });
    map.requestRender?.();
}
