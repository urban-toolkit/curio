/**
 * What a person set on an Autark map, kept across a redraw (#662).
 *
 * An edit made in the Map Editor node linked to the map draws the map
 * again (a new grammar, a new map). The camera is kept already; this keeps
 * what was set on each layer through the map's own menu: hidden or shown,
 * its opacity, colors and color map, borders, point and line sizes. A layer
 * is matched by its id, the table it draws, so a new layer starts as the
 * document draws it, and a layer gone is forgotten. The drawing tools a Map
 * Editor node puts on the map as layers (`mapEditLayers`) are none of the
 * document's: never kept, hidden or picked on.
 */
import { grammarMaps } from './autkMapDrawing';
import { INPUT_ROW, tablePositions } from '../../utils/autkInput';
import { idKey } from '../../utils/editFeatures/applyEdits';
import { isMapEditToolLayer } from '../../utils/editFeatures/mapEditLayers';

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
    for (const ref of layerRefsOf(spec)) {
        if (bareRef(ref?.dataRef) !== table) continue;
        return typeof ref?.title === 'string' && ref.title.trim() !== '' ? ref.title : table;
    }
    return table;
}

/** The layers *spec*'s maps draw, in its order. */
function layerRefsOf(spec: any): any[] {
    const maps = spec?.map ? (Array.isArray(spec.map) ? spec.map : [spec.map]) : [];
    return maps.flatMap((map: any) => (Array.isArray(map?.layerRefs) ? map.layerRefs : []));
}

/** A layer's table, from its `dataRef` as written or as a `[!! input_k !!]` chip. */
const bareRef = (ref: unknown) => String(ref ?? '').replace(/^\[!!\s*(.*?)\s*!!\]$/, '$1');

/**
 * The autk-map layer that draws *table* on a map of *grammar*, found as the
 * grammar finds it to light it (`mapLayer`), or null.
 */
export function mapLayerOf(grammar: any, table: string): any | null {
    const found = typeof grammar?.mapLayer === 'function' ? grammar.mapLayer(table) : undefined;
    if (!found) return null;
    return layersOf(found.map).find((layer) => idOf(layer) === found.layerId) ?? null;
}

/**
 * The table of the layer that picks on the map of *grammar* that draws
 * *table*: autk-map has one, the last a document marks `isPick`, or the one
 * picked in its layer menu or shown alone by a Map Editor node. Null when the
 * map has none or it draws a table *spec* does not name.
 */
export function pickingTableOf(grammar: any, spec: any, table: string | undefined): string | null {
    const map = (table ? grammar?.mapLayer?.(table)?.map : undefined) ?? grammarMaps(grammar)[0];
    const picking = idOf(map?.activePickingLayer);
    if (!picking) return null;
    for (const ref of layerRefsOf(spec)) {
        const named = bareRef(ref?.dataRef);
        if (named && layerIdFor(spec, named) === picking) return named;
    }
    return null;
}

/** The features a map draws of each table, and the input row each of its positions stands for, read back once a draw. */
export type DrawnTables = {
    features: (table: string) => Promise<any[] | null> | null;
    rows: (table: string) => Promise<number[] | null> | null;
};

/** What a map shows of one table its document draws, as autk-map holds it. */
export type MapTableState = {
    /** Whether the table's layer is the one that picks: autk-map draws a highlight there only. */
    pick: boolean;
    /** The properties of the features the layer lights, as autk-db exported them. */
    lit: Array<Record<string, unknown>>;
    /** The positions the layer lights. */
    positions: number[];
    /** How many features the layer draws: autk-map's components. */
    drawn: number;
    /** How many positions name an input row, read back from what autk-db exported; null when none could be. */
    rows: number | null;
    /** For a layer of points, the farthest a point drawn lies from the feature exported for it, in metres; else null. */
    pointDrift: number | null;
};

/** The feature *layer* draws at *position*: autk-map names the one it was handed (`featureIndex`). */
function featureAt(layer: any, features: readonly any[], position: number): any {
    const index = layer?.components?.[position]?.featureIndex;
    return features[Number.isInteger(index) ? index : position];
}

/** A feature's properties as its document has them: without the input row Curio tags it with. */
function ownProperties(feature: any): Record<string, unknown> {
    const { [INPUT_ROW]: _row, ...properties } = feature?.properties ?? {};
    return properties;
}

/**
 * For a layer of points on *map*, the farthest a point autk-map draws lies
 * from the feature of *features* it was drawn for: what tells that the
 * features read back are the ones the map was handed, in its order. autk-map
 * holds each point less the map's origin. Null for other layers.
 */
function pointDrift(map: any, layer: any, features: readonly any[]): number | null {
    const points = layer?.pointInstances;
    const components: any[] = Array.isArray(layer?.components) ? layer.components : [];
    let origin: unknown;
    try {
        origin = map?.layerManager?.origin;
    } catch {
        return null;
    }
    if (!(points instanceof Float32Array) || !Array.isArray(origin) || components.length === 0) return null;
    let drift = 0;
    components.forEach((_component, position) => {
        const start = position > 0 ? components[position - 1].nPoints : 0;
        const geometry = featureAt(layer, features, position)?.geometry;
        const at = geometry?.type === 'MultiPoint' ? geometry.coordinates?.[0] : geometry?.coordinates;
        const dx = Number(at?.[0]) - origin[0] - points[2 * start];
        const dy = Number(at?.[1]) - origin[1] - points[2 * start + 1];
        drift = Math.max(drift, Number.isFinite(dx) && Number.isFinite(dy) ? Math.hypot(dx, dy) : Infinity);
    });
    return drift;
}

/**
 * What the map of *grammar* shows of each table *spec* draws: whether its
 * layer picks, and the features it lights, read from autk-map's own layer
 * (the positions it lights, and the feature it was handed for each) and from
 * the features autk-db exported for it (*drawn*), not through the input's
 * rows; beside how many of its positions name an input row (*drawn*), as a
 * pick and a highlight read them. The e2e tests read it
 * (`window.__curio_mapState`).
 */
export async function mapStateOf(grammar: any, spec: any, drawn: DrawnTables): Promise<Record<string, MapTableState> | null> {
    if (grammarMaps(grammar).length === 0) return null;
    const out: Record<string, MapTableState> = {};
    for (const ref of layerRefsOf(spec)) {
        const table = bareRef(ref?.dataRef);
        const layer = table ? mapLayerOf(grammar, table) : null;
        if (!layer) continue;
        const features = (await drawn.features(table)) ?? [];
        const rows = await drawn.rows(table);
        const positions: number[] = Array.isArray(layer.highlightedIds) ? layer.highlightedIds : [];
        out[table] = {
            pick: layer.layerRenderInfo?.isPick === true,
            lit: positions.map((position) => ownProperties(featureAt(layer, features, position))),
            positions,
            drawn: Array.isArray(layer.components) ? layer.components.length : 0,
            rows: rows ? rows.length : null,
            pointDrift: pointDrift(grammar.mapLayer(table)?.map, layer, features),
        };
    }
    return out;
}

/**
 * Where a map draws the rows of *features*, a table it draws, whose column
 * *key* holds *id*: their positions in the table's layer, through the input
 * row each position stands for (*order*: the rows read back from what autk-db
 * exported, `drawnRows`), as a highlight names them.
 */
export function featurePositions(
    features: readonly any[],
    order: number[] | null | undefined,
    key: string,
    id: unknown,
): number[] {
    const wanted = idKey(id);
    if (wanted === null) return [];
    const rows = features.flatMap((feature, row) => (idKey(feature?.properties?.[key]) === wanted ? [row] : []));
    return tablePositions(rows, order);
}

/**
 * The properties of the feature the map of *grammar* draws at *position* of
 * *table*'s layer, counted from the end when negative, from the features
 * autk-db exported for it (*features*); null when there is none. The e2e
 * tests read it (`window.__curio_mapFeatureAt`).
 */
export function drawnFeatureAt(
    grammar: any,
    table: string,
    features: readonly any[] | null,
    position: number,
): Record<string, unknown> | null {
    const layer = mapLayerOf(grammar, table);
    const count = Array.isArray(layer?.components) ? layer.components.length : 0;
    const at = position < 0 ? count + position : position;
    if (!layer || !features || at < 0 || at >= count) return null;
    const feature = featureAt(layer, features, at);
    return feature ? ownProperties(feature) : null;
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
        if (!id || !info || isMapEditToolLayer(id)) continue;
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
        if (!id || !kept || isMapEditToolLayer(id)) continue;
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
        if (!id || isMapEditToolLayer(id)) continue;
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

/** What a Map Editor node feeding a map asks of it: the layer shown alone, and the layer an action works on. */
export type EditsView = { solo: string | null; picking: string | null };

/**
 * *map* as the Map Editor node feeding it asks now (*now*), after what it asked
 * before (*was*): its *solo* layer shown alone, and its *picking* layer, the
 * one an action works on, the layer that picks. autk-map lights a pick on its
 * picking layer only, so the node's pick and a rule's matches show there. When
 * the layer shown alone is shown with the others again, each layer gets back
 * what it had in *before*; when an action ends with none shown alone, only the
 * layer that picked before picks again, and what was set on the layers
 * meanwhile through the map's menu stays. Layers go by their ids.
 */
export function showForEdits(
    map: any,
    was: EditsView | null,
    now: EditsView,
    before: MapLayerState | null,
    colorMapped = false,
): void {
    if (!map) return;
    // One picking layer at a time: setting it takes picking off the others.
    const pick = (id: string) => {
        try {
            map.updateRenderInfo(id, { isPick: true });
        } catch {
            // A layer that cannot pick stays as it is.
        }
        map.requestRender?.();
    };
    if (now.solo !== null) soloMapLayer(map, now.solo, null, colorMapped);
    else if (was?.solo) soloMapLayer(map, null, before);
    else if (now.picking === null) {
        const picked = Object.keys(before ?? {}).find((id) => before?.[id]?.isPick === true);
        if (picked) pick(picked);
        return;
    }
    if (now.picking !== null && now.picking !== now.solo) pick(now.picking);
}
