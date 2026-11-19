/**
 * Each Autark map opens framed on the layers it draws (#773), then turned by
 * the `camera` its document writes for it.
 *
 * autk-map's flat camera starts 10,000 world units straight above the map's
 * origin whatever its layers hold (`FlatMapRenderPath.resetCamera`), and its
 * R key puts it back there: about 8 km of ground across the map's height. A
 * few blocks were a speck in the middle of the map, and a city ran past every
 * edge. autk-map fits its camera to what it shows only in terrain mode
 * (`fitCameraToTerrainBounds`).
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
 * A framed map is then turned by the `camera` of its own `map` entry, as
 * autk-grammar turns the maps it draws by itself, through the grammar's own
 * `applyCamera`, which the node takes from the grammar it runs and gives each
 * map with its entry's camera (`attachSpecCameras`), so the map keeps it for
 * its R key and for the moment it is first shown. `applyCamera` moves the eye
 * round the point the map looks at, as far from it as the eye is high, so it
 * only ever turns a view that looks straight down: the framed one, or
 * autk-map's own for a map with nothing to frame. A map in terrain mode fits
 * its own camera, and no camera turns it; neither the grammar nor Curio turns
 * terrain mode on.
 *
 * A node whose map is drawn again after each edit (Map Editor) keeps the view
 * instead: `mapViews` takes each map's camera before the redraw, and
 * `keepMapViews` puts it back on the new maps. A map whose entry now writes
 * another camera than the one it was drawn with shows that camera's view.
 * Given the panes of the documents the two draws ran, each view goes back to
 * the map of its key (`autkViews.mapKey`: a map's `id`, else its index), so a
 * map with an id keeps its view wherever the document now lists it; without
 * them, by the maps' order.
 */
import type { CameraSpec } from '@urban-toolkit/autk-grammar';
import { grammarMaps } from './autkMapDrawing';
import { mapKey, type ViewPanes } from './autkViews';

/** autk-grammar's `applyCamera`: turns a map's camera as a `camera` of the document says. */
export type ApplyCamera = (map: any, camera: CameraSpec) => void;

/** Set on a map: the `camera` of its own `map` entry, with the `applyCamera` that turns the map by it. */
const SPEC_CAMERA = Symbol.for('curio.autk.specCamera');
type SpecCamera = { camera: CameraSpec; applyCamera: ApplyCamera };

/**
 * Give each map *grammar* drew the `camera` its own entry of *spec*'s `map`
 * writes, with autk-grammar's *applyCamera*, which turns the map by it each
 * time Curio frames it. *spec* is the document the grammar ran; its maps are
 * in the order of its entries (`grammarMaps`), a `map` that is one object
 * being the first.
 */
export function attachSpecCameras(grammar: unknown, spec: any, applyCamera: ApplyCamera): void {
    const entries: any[] = spec?.map ? (Array.isArray(spec.map) ? spec.map : [spec.map]) : [];
    grammarMaps(grammar).forEach((map, index) => {
        const camera = entries[index]?.camera;
        if (!map || camera === null || typeof camera !== 'object' || Array.isArray(camera)) return;
        const turn: SpecCamera = { camera, applyCamera };
        map[SPEC_CAMERA] = turn;
    });
}

/**
 * The camera *map*'s entry writes, as a key that is the same for the same
 * camera, however its fields are ordered; none when it writes no camera.
 */
function cameraKey(map: any): string | undefined {
    const camera = (map?.[SPEC_CAMERA] as SpecCamera | undefined)?.camera;
    return camera ? JSON.stringify([camera.zoom ?? null, camera.pitch ?? null, camera.bearing ?? null]) : undefined;
}

/**
 * Turn *map* by the `camera` of its own entry, from a view that looks straight
 * down: autk-grammar's `applyCamera` puts the eye `pitch` degrees from straight
 * down, facing `bearing`, as far from the point the map looks at as the eye is
 * high, or as `zoom` says. False when the entry writes no camera.
 */
function turnBySpecCamera(map: any): boolean {
    const turn = map?.[SPEC_CAMERA] as SpecCamera | undefined;
    if (!turn) return false;
    turn.applyCamera(map, turn.camera);
    return true;
}

/**
 * Build *map*'s matrices for the camera it was just given, at the size its
 * canvas draws at, and ask it for a frame: a map that draws on demand draws
 * the camera it was given.
 */
function drawGivenCamera(map: any): void {
    const { pixelWidth, pixelHeight } = map.renderer ?? {};
    if (pixelWidth > 0 && pixelHeight > 0) map.camera.resize(pixelWidth, pixelHeight);
    map.requestRender?.();
}

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

/**
 * Frame *map* on its layers, then turn it by its camera; false when it drew
 * nothing to frame or is not shown.
 */
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
    const framed: FramedView = { eye: [...eye], lookAt: [...lookAt], up: [0, 1, 0] };
    map[FRAMED_VIEW] = framed;
    turnBySpecCamera(map);
    camera.resize(map.renderer.pixelWidth, map.renderer.pixelHeight);
    // A map that draws on demand draws the camera it was given.
    map.requestRender?.();
    map[VIEWED] = true;
    return true;
}

const FRAMED = Symbol.for('curio.autk.framedMap');
/** Set on a map whose camera Curio framed or put back: a view worth keeping. */
const VIEWED = Symbol.for('curio.autk.viewedMap');
/**
 * Set on a map Curio framed: the view it framed it at, straight down, before
 * its camera turned it; a map whose view was put back keeps the one it had.
 */
const FRAMED_VIEW = Symbol.for('curio.autk.framedView');
type FramedView = { eye: number[]; lookAt: number[]; up: number[] };

/** Whether *map* is a flat map, whose camera Curio sets; terrain mode fits its own. */
const isFlat = (map: any): boolean => !!map && !map._terrainRenderPath && typeof map.resetCamera === 'function';

/**
 * The map's R key frames it on its layers and turns it by its camera. A map
 * with nothing to frame takes autk-map's own view, turned by its camera as
 * autk-grammar turns its own maps; a map in terrain mode fits its own camera.
 */
function frameOnReset(map: any): void {
    if (map[FRAMED]) return;
    const ownReset = map.resetCamera.bind(map);
    map.resetCamera = () => {
        if (map._terrainRenderPath) ownReset();
        else if (!frameMap(map)) {
            ownReset();
            if (turnBySpecCamera(map)) drawGivenCamera(map);
        }
    };
    map[FRAMED] = true;
}

/**
 * Frame each flat map of *grammar* on its layers and turn it by its camera,
 * now or, for a map drawn while hidden (a collapsed scenario's member), when
 * it is first shown:
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

/**
 * Where a map's camera stands, the origin of the world it stands in, the
 * camera its entry wrote when it was drawn (`cameraKey`), when it wrote one,
 * the view Curio framed it at before that camera turned it, when it did, and
 * the map's key in the document it was drawn from, when that was given.
 */
export type MapView = {
    eye: number[]; lookAt: number[]; up: number[]; origin: number[] | null; camera?: string; framed?: FramedView;
    key?: string | number;
};

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
 * Given *panes*, those of the document the grammar ran, each view holds its
 * map's key.
 */
export function mapViews(grammar: any, panes?: ViewPanes | null): Array<MapView | null> {
    return grammarMaps(grammar).map((map, index) => {
        const camera = map?.camera;
        if (!isFlat(map) || typeof camera?.getEye !== 'function') return null;
        if (!map[VIEWED] && !shownCanvas(map)) return null;
        try {
            const view: MapView = {
                eye: [...camera.getEye()],
                lookAt: [...camera.getLookAt()],
                up: [...camera.getUp()],
                origin: originOf(map),
            };
            const written = cameraKey(map);
            if (written !== undefined) view.camera = written;
            const framed = map[FRAMED_VIEW] as FramedView | undefined;
            if (framed) view.framed = { eye: [...framed.eye], lookAt: [...framed.lookAt], up: [...framed.up] };
            if (panes) view.key = mapKey(panes, index);
            return view;
        } catch {
            return null;
        }
    });
}

/**
 * Put *map*'s camera at *view*, moved by however far the map's origin moved,
 * so the same ground stays in view, and keep the view it was framed at, moved
 * the same way; false when the map has no camera to set.
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
    if (view.framed) {
        const framed: FramedView = { eye: moved(view.framed.eye), lookAt: moved(view.framed.lookAt), up: [...view.framed.up] };
        map[FRAMED_VIEW] = framed;
    }
    drawGivenCamera(map);
    map[VIEWED] = true;
    return true;
}

/**
 * Show each flat map of *grammar* that its entry's `camera` turns at the view
 * Curio framed it at, straight down on its layers, before the turn: the very
 * view it was given then (`FRAMED_VIEW`), whatever size its canvas is laid out
 * at now, or, for a map it holds none of, a framing made now. Return what puts
 * the turned views back. The e2e framing check (#773) reads such a map framed,
 * as it reads a map with no camera, then reads its turn
 * (`window.__curio_showMapsFramed`, `window.__curio_mapViews`).
 */
export function showFramedViews(grammar: any): () => void {
    const views = mapViews(grammar);
    const turned = grammarMaps(grammar).flatMap((map, index) => (
        isFlat(map) && map[SPEC_CAMERA] ? [{ map, view: views[index] }] : []
    ));
    for (const { map } of turned) {
        const framed = map[FRAMED_VIEW] as FramedView | undefined;
        if (framed && typeof map.camera?.resetCamera === 'function' && map.renderer) {
            map.camera.resetCamera([...framed.up], [...framed.lookAt], [...framed.eye]);
            drawGivenCamera(map);
            continue;
        }
        const turn = map[SPEC_CAMERA];
        delete map[SPEC_CAMERA];
        try {
            frameMap(map);
        } finally {
            map[SPEC_CAMERA] = turn;
        }
    }
    return () => keepMapViews({ maps: turned.map(({ map }) => map) }, turned.map(({ view }) => view));
}

/**
 * Put each flat map of *grammar* back on the view *views* holds for it, as
 * `mapViews` took it from the maps the last draw made, so a draw after an
 * edit keeps the view the person zoomed and panned to, or the one its camera
 * turned it to: the view is put back as it was, never turned again. A view
 * that holds its map's key goes back to the map of that key among *panes*,
 * those of the document the grammar ran; any other to the map at its place. autk-map
 * draws a map's layers relative to the middle of the first layer it loads,
 * which a removed feature at its edge moves; the camera moves with it. A map
 * with no view to keep, or whose entry writes another camera than the one its
 * view was taken under, is framed and turned by its camera, as `frameMaps`
 * does it, and every map's R key frames and turns it.
 */
export function keepMapViews(grammar: any, views: ReadonlyArray<MapView | null>, panes?: ViewPanes | null): void {
    const byKey = !!panes && views.some((view) => view?.key !== undefined);
    grammarMaps(grammar).forEach((map, index) => {
        const taken = byKey
            ? views.find((view) => view?.key === mapKey(panes, index)) ?? null
            : views[index];
        const view = taken && taken.camera === cameraKey(map) ? taken : null;
        if (!view || !isFlat(map) || !putBackView(map, view)) {
            frameMaps({ maps: [map] });
            return;
        }
        frameOnReset(map);
    });
}
