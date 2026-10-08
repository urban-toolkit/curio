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
 * on demand (`autkMapDrawing`). The grammar keeps each map by the dataRefs it
 * draws (`_mapRegistry`).
 */

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
    return true;
}

const FRAMED = Symbol.for('curio.autk.framedMap');

/**
 * Frame each flat map of *grammar* on its layers, now or, for a map drawn
 * while hidden (a collapsed scenario's member), when it is first shown:
 * Curio resizes a map that is shown with a window resize, which autk-map
 * handles before this listener, added later, runs.
 */
export function frameMaps(grammar: any): void {
    const registry: Map<string, any> | undefined = grammar?._mapRegistry;
    if (!registry) return;
    for (const map of new Set(registry.values())) {
        if (!map || map._terrainRenderPath || typeof map.resetCamera !== 'function') continue;
        if (!map[FRAMED]) {
            const ownReset = map.resetCamera.bind(map);
            map.resetCamera = () => {
                if (map._terrainRenderPath || !frameMap(map)) ownReset();
            };
            map[FRAMED] = true;
        }
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
