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
import { mapEntries, mapIndexOf, pickLayerOf, type ViewPanes } from './autkViews';
import { INPUT_ROW, tablePositions } from '../../utils/autkInput';
import { TOP_KEYS } from '../../utils/buildingHeight';
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
 * The autk-map layer that draws *table* on a map of *grammar*, as the
 * grammar's `mapLayer` finds it, or null: on the map *mapId* names (its index,
 * or its `id`), else the last one when several maps draw it.
 */
export function mapLayerOf(grammar: any, table: string, mapId?: string | number): any | null {
    const found = typeof grammar?.mapLayer === 'function' ? grammar.mapLayer(table, mapId) : undefined;
    if (!found) return null;
    return layersOf(found.map).find((layer) => idOf(layer) === found.layerId) ?? null;
}

/** The id a layer of a document has in its map, as autk-grammar names it: its `title`, else its table. */
const layerIdOfRef = (ref: any): string =>
    typeof ref?.title === 'string' && ref.title !== '' ? ref.title : bareRef(ref?.dataRef);

/** The layers the map *entry* of a document draws. */
const refsOf = (entry: any): any[] => (Array.isArray(entry?.layerRefs) ? entry.layerRefs : []);

/**
 * The map of *grammar* a pick was made on, and the layers of *spec* it draws:
 * the map *mapId* names among *panes*, those of *spec* (its index, or its
 * `id`), as autk-grammar's `map:picking` names it; without one, the map that
 * draws *table*, else the first. A map the grammar does not list as one of its
 * maps reads every layer of *spec*.
 */
function pickedMap(
    grammar: any, spec: any, table: string | undefined, mapId: string | number | undefined, panes?: ViewPanes | null,
) {
    const maps = grammarMaps(grammar);
    if (mapId !== undefined) {
        const index = mapIndexOf(panes, mapId);
        return { index, map: index < 0 ? undefined : maps[index], refs: index < 0 ? [] : refsOf(mapEntries(spec)[index]) };
    }
    const map = (table ? grammar?.mapLayer?.(table)?.map : undefined) ?? maps[0];
    const index = maps.indexOf(map);
    return { index: Math.max(index, 0), map, refs: index < 0 ? layerRefsOf(spec) : refsOf(mapEntries(spec)[index]) };
}

/**
 * The table of the layer that picks on a map of *grammar*: autk-map has one,
 * the last a document marks `isPick`, or the one picked in its layer menu or
 * shown alone by a Map Editor node. The map is the one *mapId* names among
 * *panes*, those of *spec* (its index, or its `id`), as autk-grammar's
 * `map:picking` names the map picked on; without one, the map that draws
 * *table*, else the first. Only that
 * map's layers are read, so two maps whose layers share a title stay apart.
 * Null when the map has none or it draws a table its entry of *spec* does not
 * name.
 */
export function pickingTableOf(
    grammar: any, spec: any, table: string | undefined, mapId?: string | number, panes?: ViewPanes | null,
): string | null {
    const { map, refs } = pickedMap(grammar, spec, table, mapId, panes);
    const picking = idOf(map?.activePickingLayer);
    if (!picking) return null;
    for (const ref of refs) {
        const named = bareRef(ref?.dataRef);
        if (named && layerIdOfRef(ref) === picking) return named;
    }
    return null;
}

/**
 * The map a pick was made on, by the `mapId` autk-grammar names it with, else
 * the map that draws the picked layer *layerId*, else the first; with its
 * entry of *spec* and the table picked: the one its layer that picks now
 * draws, else its entry's own picking layer's. Null for a `mapId` that names
 * no map among *panes*, those of *spec*.
 */
export function pickOn(
    grammar: any,
    spec: any,
    mapId: string | number | undefined,
    layerId?: string,
    panes?: ViewPanes | null,
): { index: number; entry: any; table: string | undefined } | null {
    const { index } = pickedMap(grammar, spec, layerId, mapId, panes);
    if (index < 0) return null;
    const entry = mapEntries(spec)[index];
    return { index, entry, table: pickingTableOf(grammar, spec, layerId, mapId, panes) ?? pickLayerOf(entry) };
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
 * pick and a highlight read them. With *mapIndex*, the layers of that map of
 * the grammar's maps; without it, the last map that draws each table. The
 * e2e tests read it (`window.__curio_mapState`).
 */
export async function mapStateOf(
    grammar: any, spec: any, drawn: DrawnTables, mapIndex?: number,
): Promise<Record<string, MapTableState> | null> {
    if (grammarMaps(grammar).length === 0) return null;
    const out: Record<string, MapTableState> = {};
    for (const ref of layerRefsOf(spec)) {
        const table = bareRef(ref?.dataRef);
        const layer = table ? mapLayerOf(grammar, table, mapIndex) : null;
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
            pointDrift: pointDrift(grammar.mapLayer(table, mapIndex)?.map, layer, features),
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
 * autk-db exported for it (*features*); null when there is none. With
 * *mapIndex*, that map's layer; without it, the last map's that draws it. The
 * e2e tests read it (`window.__curio_mapFeatureAt`).
 */
export function drawnFeatureAt(
    grammar: any,
    table: string,
    features: readonly any[] | null,
    position: number,
    mapIndex?: number,
): Record<string, unknown> | null {
    const layer = mapLayerOf(grammar, table, mapIndex);
    const count = Array.isArray(layer?.components) ? layer.components.length : 0;
    const at = position < 0 ? count + position : position;
    if (!layer || !features || at < 0 || at >= count) return null;
    const feature = featureAt(layer, features, at);
    return feature ? ownProperties(feature) : null;
}

/**
 * The settings of each layer map *index* of *grammar* draws (the first by
 * default; a Map Editor node's, the map it edits), before a layer is shown
 * alone: with which one a click selects (`isPick`), which a redraw does not
 * keep, since an edit's own pick sets it.
 */
export function snapshotBeforeSolo(grammar: unknown, index = 0): MapLayerState | null {
    const state = snapshotMapLayers(grammar, index);
    const picking = idOf(grammarMaps(grammar)[index]?.activePickingLayer);
    if (state && picking && state[picking]) state[picking] = { ...state[picking], isPick: true };
    return state;
}

/**
 * The layer each snapshot's legend showed (the map UI's `activeLayer`), by
 * the layer's id: the document's `legend` layer, or the one picked in the
 * map's menu.
 */
const legendOf = new WeakMap<MapLayerState, string>();

/** The settings of each layer map *index* of *grammar* draws, the first by default, and the layer its legend shows. */
export function snapshotMapLayers(grammar: unknown, index = 0): MapLayerState | null {
    const map = grammarMaps(grammar)[index];
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
    const legend = idOf(map.ui?.activeLayer);
    if (legend) legendOf.set(out, legend);
    return out;
}

/**
 * Put *state* back on the layers of *map* that have the same id, then show in
 * the legend the layer it showed when *state* was taken: autk-map moves the
 * legend to each layer whose colors are set, the last one put back here. It
 * sets the legend's layer alone, through the map UI's `activeLayer`, as
 * autk-grammar's `legend` does: autk-map's `changeActiveLayer` would also make
 * that layer the one that picks.
 */
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
    const legend = layersOf(map).find((layer) => idOf(layer) === legendOf.get(state));
    if (legend && map.ui && idOf(map.ui.activeLayer) !== idOf(legend)) {
        try {
            map.ui.activeLayer = legend;
            map.ui.refreshLegend?.(null);
        } catch (error) {
            console.warn('[autk-map] keeping the legend\'s layer across a redraw failed:', error);
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

/** What a map draws of a document's keys on its layers, read from autk-map's own layer. */
export type DrawnLayer = {
    /** The layer's id in its map: its `title`, else its table. */
    id: string;
    /** The type autk-map draws it as (`layerType`). */
    type: string | null;
    /** The features it lights, by their positions among those it draws. */
    highlighted: number[];
    /** The features it hides (`skippedComps`), by their positions among those it draws. */
    skipped: number[];
    /** Each line's width (`widthBy`), or null when the layer gives its lines none of their own. */
    widths: number[] | null;
    /** Each building's top, in the order the layer draws them, null for one drawn with no point (`buildingsZeroHeight`). */
    tops: Array<number | null> | null;
    /** Each building's points in the layer's mesh, from its first to past its last, in the same order. */
    spans: Array<[number, number]> | null;
};

/** What a map draws of a document's keys on the map: its layers, its legend, its controls and its terrain. */
export type MapDrawing = {
    layers: DrawnLayer[];
    /** The layer the legend shows (`legend`), by its id. */
    legend: string | null;
    /** Whether autk-map's menu and legend are on the page (`showUi`). */
    controls: boolean;
    /** The heights the ground rises to (`terrain`), or null on a flat map. */
    terrain: { minHeight: number; maxHeight: number; width: number; height: number } | null;
    /**
     * The colors the map draws picked features and values it cannot color in
     * (`highlightColor`, `invalidValueColor`), as autk-map's style holds them.
     */
    highlightColor: unknown;
    invalidValueColor: unknown;
};

/**
 * Where each building a buildings layer draws lies in its mesh: its points,
 * from its first to past its last. autk-map keeps on each component of a layer
 * the points of it and of every component before it (`nPoints`, a running
 * count, its `loadComponent`'s), as `pointDrift` reads a layer of points.
 */
function buildingSpans(layer: any): Array<[number, number]> | null {
    const components = layer?.components;
    if (layer?._dimension !== 3 || !ArrayBuffer.isView(layer?.position) || !Array.isArray(components)) return null;
    let start = 0;
    return components.map((component: any) => {
        const end = Math.max(start, Number(component?.nPoints) || 0);
        const span: [number, number] = [start, end];
        start = end;
        return span;
    });
}

/** The top of each building a buildings layer draws (*spans*): the highest of its points, null when it drew none. */
function buildingTops(layer: any, spans: Array<[number, number]> | null): Array<number | null> | null {
    if (!spans) return null;
    const values = layer.position as ArrayLike<number>;
    return spans.map(([start, end]) => {
        let top: number | null = null;
        for (let point = start; point < end; point += 1) {
            const z = values[point * 3 + 2];
            if (Number.isFinite(z) && (top === null || z > top)) top = z;
        }
        return top;
    });
}

/**
 * What map *index* of *grammar* draws of the keys a document writes on a map
 * and its layers, read from autk-map's own objects: each layer's type, the
 * features it lights and hides, each line's width, each building's top and
 * its points,
 * the layer its legend shows, whether its menu and legend are on the page, and
 * the heights of its terrain. The drawing tools a Map Editor node puts on the
 * map are left out. The e2e tests read it (`window.__curio_mapDrawing`).
 */
export function mapDrawingOf(grammar: unknown, index = 0): MapDrawing | null {
    const map = grammarMaps(grammar)[index];
    if (!map) return null;
    const numbers = (values: unknown): number[] => (
        values && typeof (values as any)[Symbol.iterator] === 'function' ? Array.from(values as Iterable<number>, Number) : []
    );
    const layers = layersOf(map).flatMap((layer): DrawnLayer[] => {
        const id = idOf(layer);
        if (!id || isMapEditToolLayer(id)) return [];
        const widths = layer?.layerRenderInfo?.polylinesWidthByComponent;
        const spans = buildingSpans(layer);
        return [{
            id,
            type: layer?.layerInfo?.typeLayer ?? null,
            highlighted: numbers(layer?.highlightedIds),
            // A points layer keeps the features it hides in a set of its own.
            skipped: numbers(layer?.skippedIds ?? layer?._skippedIds).sort((a, b) => a - b),
            widths: ArrayBuffer.isView(widths) ? numbers(widths) : null,
            tops: buildingTops(layer, spans),
            spans,
        }];
    });
    const ui = map.ui;
    const shown = (element: any) => !!element?.isConnected;
    const heightfield = map._terrainRenderPath?.heightfield;
    return {
        layers,
        legend: idOf(ui?.activeLayer) ?? null,
        controls: shown(ui?._menuIcon) || shown(ui?._subMenu) || shown(ui?._legend),
        terrain: heightfield
            ? { minHeight: heightfield.minHeight, maxHeight: heightfield.maxHeight, width: heightfield.width, height: heightfield.height }
            : null,
        highlightColor: map.style?.getHighlightColor?.() ?? null,
        invalidValueColor: map.style?.getInvalidValueColor?.() ?? null,
    };
}

/** A feature a grammar handed autk-map: its input row, and the keys autk-map reads a building's top from that it holds. */
export type HandedFeature = { row: number | null; tops: Record<string, unknown> };

/**
 * The features the maps of *grammar* were handed for the table of *key*
 * (`autkTableKey`), in the order a layer draws them: the export of the table
 * the grammar's map adapter loaded into autk-map (its `_exports`), each feature
 * with a geometry. Null when the grammar exported no such table. The e2e tests
 * read it (`window.__curio_mapHanded`).
 */
export async function handedFeaturesOf(grammar: unknown, key: string): Promise<HandedFeature[] | null> {
    const exports = (grammar as any)?._exports;
    let exported: any;
    try {
        exported = exports instanceof Map ? await exports.get(key) : undefined;
    } catch {
        return null;
    }
    if (!Array.isArray(exported?.features)) return null;
    return exported.features.filter((feature: any) => feature?.geometry != null).map((feature: any) => {
        const properties = feature?.properties ?? {};
        const row = properties[INPUT_ROW];
        return {
            row: Number.isInteger(row) ? row : null,
            tops: Object.fromEntries(TOP_KEYS.filter((top) => top in properties).map((top) => [top, properties[top]])),
        };
    });
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
