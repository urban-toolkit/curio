/**
 * Each Autark map opens framed on the layers it draws (#773).
 *
 * autk-map's flat camera starts 10,000 world units straight above the map's
 * origin whatever its layers hold (`FlatMapRenderPath.resetCamera`), and its
 * R key puts it back there: about 8 km of ground across the map's height. A
 * few blocks were a speck in the middle of the map, and a city ran past every
 * edge. autk-map fits its camera to what it shows only in terrain mode
 * (`fitCameraToTerrainBounds`), and the grammar's document has no camera.
 *
 * `frameMaps` does for each flat map of a grammar what terrain mode does, with
 * the same arithmetic, through the camera's own `resetCamera` and `resize`:
 * the camera looks straight down on the middle of the layers' extent, from as
 * high as fits that extent with 8% to spare. The extent is that of the
 * geometry each layer drew, which autk-map keeps relative to the map's origin,
 * the space its camera is in. Buildings lift the camera by the tallest one,
 * so their roofs fit as flat ground would. The map's R key frames it the same
 * way, and a framed map is asked for a frame (`requestRender`), since it draws
 * on demand (`autkMapDrawing`). Every map the grammar drew is framed
 * (`grammarMaps`).
 *
 * A node whose map is drawn again after each edit (Map Editor) keeps the view
 * instead: `mapViews` takes each map's camera before the redraw, and
 * `keepMapViews` puts it back on the new maps.
 */
import { grammarMaps } from './autkMapDrawing';

/** What a map's layers drew, in its world units, and the tallest height. */
export type MapExtent = { minX: number; minY: number; maxX: number; maxY: number; top: number };

/** Each vertex a layer drew, as autk-map keeps it: x, y (and z) runs. */
function drawnVertices(layer: any): { values: ArrayLike<number>; stride: number } | null {
    // A points layer keeps one x, y pair a point; every other layer its mesh,
    // and a buildings layer's mesh has a height for each vertex.
    if (ArrayBuffer.isView(layer?.pointInstances)) return { values: layer.pointInstances, stride: 2 };
    if (ArrayBuffer.isView(layer?.position)) return { values: layer.position, stride: layer._dimension === 3 ? 3 : 2 };
    return null;
}

/** The extent of what *layers* drew, or null when they drew nothing. */
export function drawnExtent(layers: any[]): MapExtent | null {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity, top = 0;
    for (const layer of layers) {
        const drawn = drawnVertices(layer);
        if (!drawn) continue;
        const { values, stride } = drawn;
        for (let i = 0; i + 1 < values.length; i += stride) {
            const x = values[i], y = values[i + 1];
            if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
            if (x < minX) minX = x;
            if (x > maxX) maxX = x;
            if (y < minY) minY = y;
            if (y > maxY) maxY = y;
            if (stride === 3 && values[i + 2] > top) top = values[i + 2];
        }
    }
    return Number.isFinite(minX) ? { minX, minY, maxX, maxY, top } : null;
}

/**
 * Where autk-map's terrain mode would put the camera for *extent* on a view of
 * *aspect* (width over height) and vertical field of view *fovy*: looking
 * straight down on its middle, from the height that fits it, never past half
 * of the camera's far plane *far*, where the ground would be clipped.
 */
export function framingCamera(
    extent: MapExtent, aspect: number, fovy: number, far: number = Infinity,
): { lookAt: number[]; eye: number[] } {
    const width = Math.max(extent.maxX - extent.minX, 1);
    const height = Math.max(extent.maxY - extent.minY, 1);
    const centerX = (extent.minX + extent.maxX) * 0.5;
    const centerY = (extent.minY + extent.maxY) * 0.5;
    const halfFovTangent = Math.tan(fovy * 0.5);
    const distanceForHeight = height / (2 * halfFovTangent);
    const distanceForWidth = width / (2 * halfFovTangent * aspect);
    const distance = Math.max(distanceForHeight, distanceForWidth) * 1.08;
    const eyeZ = Math.min(extent.top + distance, far * 0.5);
    return { lookAt: [centerX, centerY, 0], eye: [centerX, centerY, eyeZ] };
}

/** The canvas a map draws into, when it is laid out. */
function shownCanvas(map: any): HTMLCanvasElement | null {
    const canvas = map?.canvas;
    return canvas && canvas.offsetWidth > 0 && canvas.offsetHeight > 0 ? canvas : null;
}

/** Frame *map* on its layers; false when it drew nothing to frame or is not shown. */
function frameMap(map: any): boolean {
    const camera = map?.camera;
    const canvas = shownCanvas(map);
    if (!canvas || typeof camera?.resetCamera !== 'function' || !map.renderer) return false;
    const extent = drawnExtent(map.layerManager?.layers ?? []);
    // One point has no extent to fit: autk-map's own view stays.
    if (!extent || (extent.maxX <= extent.minX && extent.maxY <= extent.minY)) return false;
    const aspect = Math.max(canvas.offsetWidth / canvas.offsetHeight, 1e-6);
    const { lookAt, eye } = framingCamera(extent, aspect, camera.getFovyRadians(), camera.getFar());
    camera.resetCamera([0, 1, 0], lookAt, eye);
    camera.resize(map.renderer.pixelWidth, map.renderer.pixelHeight);
    // A map that draws on demand draws the camera it was given.
    map.requestRender?.();
    map[VIEWED] = true;
    return true;
}

const FRAMED = Symbol.for('curio.autk.framedMap');
/** Set on a map whose camera Curio framed or put back: a view worth keeping. */
const VIEWED = Symbol.for('curio.autk.viewedMap');

/** Whether *map* is a flat map, whose camera Curio sets; terrain mode fits its own. */
const isFlat = (map: any): boolean => !!map && !map._terrainRenderPath && typeof map.resetCamera === 'function';

/** The map's R key frames it on its layers. */
function frameOnReset(map: any): void {
    if (map[FRAMED]) return;
    const ownReset = map.resetCamera.bind(map);
    map.resetCamera = () => {
        if (map._terrainRenderPath || !frameMap(map)) ownReset();
    };
    map[FRAMED] = true;
}

/**
 * Frame each flat map of *grammar* on its layers, now or, for a map drawn
 * while hidden (a collapsed scenario's member), when it is first shown:
 * Curio resizes a map that is shown with a window resize, which autk-map
 * handles before this listener, added later, runs.
 */
export function frameMaps(grammar: any): void {
    for (const map of grammarMaps(grammar)) {
        if (!isFlat(map)) continue;
        frameOnReset(map);
        if (shownCanvas(map)) {
            map.resetCamera();
            continue;
        }
        const onShown = () => {
            if (map._isDestroyed) window.removeEventListener('resize', onShown);
            else if (shownCanvas(map)) {
                window.removeEventListener('resize', onShown);
                map.resetCamera();
            }
        };
        window.addEventListener('resize', onShown);
    }
}

/** Where a map's camera stands, and the origin of the world it stands in. */
export type MapView = { eye: number[]; lookAt: number[]; up: number[]; origin: number[] | null };

/**
 * The origin autk-map draws *map*'s layers relative to: the middle of the
 * first layer it loaded (its LayerManager's), or null before it has one.
 */
function originOf(map: any): number[] | null {
    try {
        const manager = map?.layerManager;
        if (!manager || manager.hasOrigin === false) return null;
        return Array.isArray(manager.origin) ? [...manager.origin] : null;
    } catch {
        return null;
    }
}

/**
 * The view of each map *grammar* drew, in its order: null for one with no view
 * to keep. A map drawn while hidden and never shown since has autk-map's own
 * camera, which no one framed or moved: the next draw frames its map instead.
 */
export function mapViews(grammar: any): Array<MapView | null> {
    return grammarMaps(grammar).map((map) => {
        const camera = map?.camera;
        if (!isFlat(map) || typeof camera?.getEye !== 'function') return null;
        if (!map[VIEWED] && !shownCanvas(map)) return null;
        try {
            return {
                eye: [...camera.getEye()],
                lookAt: [...camera.getLookAt()],
                up: [...camera.getUp()],
                origin: originOf(map),
            };
        } catch {
            return null;
        }
    });
}

/**
 * Put *map*'s camera at *view*, moved by however far the map's origin moved,
 * so the same ground stays in view; false when the map has no camera to set.
 */
function putBackView(map: any, view: MapView): boolean {
    const camera = map?.camera;
    if (typeof camera?.resetCamera !== 'function' || !map.renderer) return false;
    const origin = originOf(map);
    const shift = (i: number) => (
        view.origin && origin && Number.isFinite(view.origin[i]) && Number.isFinite(origin[i])
            ? view.origin[i] - origin[i]
            : 0
    );
    const moved = (point: number[]) => point.map((value, i) => value + shift(i));
    camera.resetCamera([...view.up], moved(view.lookAt), moved(view.eye));
    const { pixelWidth, pixelHeight } = map.renderer;
    if (pixelWidth > 0 && pixelHeight > 0) camera.resize(pixelWidth, pixelHeight);
    // A map that draws on demand draws the camera it was given.
    map.requestRender?.();
    map[VIEWED] = true;
    return true;
}

/**
 * Put each flat map of *grammar* back on the view *views* holds at its place,
 * as `mapViews` took it from the maps the last draw made, so a draw after an
 * edit keeps the view the person zoomed and panned to. autk-map draws a map's
 * layers relative to the middle of the first layer it loads, which a removed
 * feature at its edge moves; the camera moves with it. A map with no view to
 * keep is framed, as `frameMaps` frames it, and every map's R key frames it.
 */
export function keepMapViews(grammar: any, views: ReadonlyArray<MapView | null>): void {
    grammarMaps(grammar).forEach((map, index) => {
        const view = views[index];
        if (!view || !isFlat(map) || !putBackView(map, view)) {
            frameMaps({ maps: [map] });
            return;
        }
        frameOnReset(map);
    });
}
