/**
 * A basemap under an Autark map, turned on and off from the node, as SCOUT's
 * view node toggles its tile layer.
 *
 * Autark draws everything itself, with WebGPU, in EPSG:3395, so there is no
 * tile layer to put under it. Its own basemap is OpenStreetMap: the land, the
 * water, the parks and the roads around the data, which autk-db loads from
 * Overpass by a bounding box and autk-map draws in its style's colors. Those
 * layer types sit below every other layer in autk-map's order (surface,
 * parks, water, roads), so the node's own layers stay on top.
 *
 * The OSM data goes into a database of its own: autk-db wants OpenStreetMap
 * loaded before any other layer of a workspace, and the node's database has
 * its layers already. What one extent loads is kept for the page, so turning
 * the basemap off and on, or running the node again, asks Overpass once.
 */
import { newAutkDb } from './autkRasters';

/** The OSM layers a basemap draws, bottom to top. */
export const BASEMAP_LAYERS = ['surface', 'parks', 'water', 'roads'] as const;

/** The table the basemap's OSM goes into; each layer is `<table>_<layer>`. */
export const BASEMAP_TABLE = 'curio_basemap';

/** A layer id that is the basemap's, not the node's. */
export const basemapLayerId = (layer: string) => `${BASEMAP_TABLE}_${layer}`;

/** How far past the data the basemap reaches, as a share of its extent. */
const MARGIN = 0.1;

// WGS 84, as EPSG:3395 (World Mercator) projects it.
const A = 6378137;
const E = 0.0818191908426215;

/** `[lon, lat]` in degrees of a point in EPSG:3395 metres. */
export function worldMercatorToLonLat(x: number, y: number): [number, number] {
    const lon = (x / A) * (180 / Math.PI);
    const t = Math.exp(-y / A);
    let phi = Math.PI / 2 - 2 * Math.atan(t);
    for (let i = 0; i < 15; i++) {
        const s = E * Math.sin(phi);
        const next = Math.PI / 2 - 2 * Math.atan(t * Math.pow((1 - s) / (1 + s), E / 2));
        if (Math.abs(next - phi) < 1e-12) { phi = next; break; }
        phi = next;
    }
    return [lon, phi * (180 / Math.PI)];
}

/**
 * The extent of a map's own layers, `[west, south, east, north]` in degrees,
 * with a margin; null when it has none. autk-map keeps a layer's vertices
 * relative to the map's origin (EPSG:3395), two values a vertex, three for
 * buildings.
 */
export function mapExtent(map: any): [number, number, number, number] | null {
    const manager = map?.layerManager;
    if (!manager?.hasOrigin) return null;
    const [ox, oy] = manager.origin;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const layer of manager.layers ?? []) {
        const id = String(layer?.layerInfo?.id ?? '');
        if (id.startsWith(`${BASEMAP_TABLE}_`)) continue;
        const position: ArrayLike<number> | undefined = layer?.position;
        if (!position || position.length === 0) continue;
        const stride = layer.layerInfo.typeLayer === 'buildings' ? 3 : 2;
        for (let i = 0; i + 1 < position.length; i += stride) {
            const x = position[i], y = position[i + 1];
            if (x < minX) minX = x;
            if (x > maxX) maxX = x;
            if (y < minY) minY = y;
            if (y > maxY) maxY = y;
        }
    }
    if (!Number.isFinite(minX)) return null;
    const padX = (maxX - minX) * MARGIN, padY = (maxY - minY) * MARGIN;
    const [west, south] = worldMercatorToLonLat(ox + minX - padX, oy + minY - padY);
    const [east, north] = worldMercatorToLonLat(ox + maxX + padX, oy + maxY + padY);
    return [west, south, east, north];
}

const loaded = new Map<string, Promise<Map<string, any>>>();

/** The basemap's collections for *bbox*, by layer: loaded once a page. */
export function basemapCollections(
    bbox: [number, number, number, number],
    newDb: () => Promise<any> = newAutkDb,
): Promise<Map<string, any>> {
    const key = bbox.map((v) => v.toFixed(4)).join(',');
    let pending = loaded.get(key);
    if (!pending) {
        pending = (async () => {
            const db = await newDb();
            await db.loadOsm({
                queryArea: { bbox },
                outputTableName: BASEMAP_TABLE,
                autoLoadLayers: { layers: [...BASEMAP_LAYERS] },
            });
            const collections = new Map<string, any>();
            for (const layer of BASEMAP_LAYERS) {
                try {
                    const collection = await db.getLayer(basemapLayerId(layer));
                    if (collection?.features?.length) collections.set(layer, collection);
                } catch {
                    // An area with no water, say: that layer is left out.
                }
            }
            return collections;
        })();
        // A failure is not kept, so the next try asks Overpass again.
        pending.catch(() => loaded.delete(key));
        loaded.set(key, pending);
    }
    return pending;
}

/** Forget what has been loaded (tests). */
export function clearBasemapCache(): void {
    loaded.clear();
}

/** Every map the grammar draws, once each. */
function mapsOf(grammar: any): any[] {
    const registry: Map<string, any> | undefined = grammar?._mapRegistry;
    return registry ? [...new Set(registry.values())] : [];
}

/**
 * Show or hide the basemap under every map *grammar* draws. Shown the first
 * time, its OSM is loaded for the map's extent and added under the map's
 * layers; after that it is hidden and shown again without reloading.
 */
export async function setBasemap(
    grammar: any,
    on: boolean,
    newDb: () => Promise<any> = newAutkDb,
): Promise<void> {
    for (const map of mapsOf(grammar)) {
        const has = (layer: string) => !!map.layerManager?.searchByLayerId?.(basemapLayerId(layer));
        if (on && !BASEMAP_LAYERS.some(has)) {
            const bbox = mapExtent(map);
            if (!bbox) continue;
            const collections = await basemapCollections(bbox, newDb);
            for (const [layer, collection] of collections) {
                if (has(layer)) continue;
                map.loadCollection(basemapLayerId(layer), { collection, type: layer });
            }
        }
        for (const layer of BASEMAP_LAYERS) {
            if (has(layer)) map.updateRenderInfo(basemapLayerId(layer), { isSkip: !on });
        }
    }
}
