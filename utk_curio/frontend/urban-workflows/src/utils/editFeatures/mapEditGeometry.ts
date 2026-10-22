/**
 * How a Map Edits node's overlay sees the Autark map it draws on (#662,
 * `components/editFeatures/MapEditOverlay`): a data coordinate on the screen
 * and back, through the map's camera and its origin; the view from straight
 * above that every action is worked in, and the tilt put back after it; the
 * buildings drawn flat meanwhile; and which feature a click reaches, as the
 * map draws its points and lines.
 */
import type { Geometry } from "./editFeatures";
import { kindOf, type EditedFeature } from "./layerModel";
import { fromMercator, toMercator } from "./mapEditBus";
import { toRings } from "./geometryRings";

export type XY = [number, number];

export interface Projection {
  width: number;
  height: number;
  toScreen: (xy: XY) => XY;
  toData: (sx: number, sy: number) => XY;
  /** How many screen pixels *length* map units are at *xy* now. */
  pixels: (xy: XY, length: number) => number;
}

/** How the map shows a data coordinate now, and back: through its camera and its origin. */
export function projectionOf(map: any, geographic: boolean): Projection | null {
  const camera = map?.camera;
  const canvas: HTMLCanvasElement | undefined = map?.canvas;
  if (!camera || !canvas || typeof camera.getViewProjectionMatrix !== "function") return null;
  const width = canvas.offsetWidth;
  const height = canvas.offsetHeight;
  if (!(width > 0 && height > 0)) return null;
  let origin: number[] = [0, 0];
  try {
    origin = map.layerManager?.origin ?? origin;
  } catch {
    return null;
  }
  const m = camera.getViewProjectionMatrix() as ArrayLike<number>;
  const eye = camera.getEye() as number[];
  const onScreen = ([mx, my]: XY): XY => {
    const x = mx - origin[0];
    const y = my - origin[1];
    const cx = m[0] * x + m[4] * y + m[12];
    const cy = m[1] * x + m[5] * y + m[13];
    const cw = m[3] * x + m[7] * y + m[15];
    return [((cx / cw + 1) / 2) * width, ((1 - cy / cw) / 2) * height];
  };
  const inMapUnits = (xy: XY): XY => (geographic ? toMercator(xy) : xy);
  return {
    width,
    height,
    toScreen: (xy) => onScreen(inMapUnits(xy)),
    pixels: (xy, length) => {
      const [mx, my] = inMapUnits(xy);
      const [ax, ay] = onScreen([mx, my]);
      const [bx, by] = onScreen([mx + length, my]);
      return Math.hypot(bx - ax, by - ay);
    },
    toData: (sx, sy) => {
      const dir = camera.getWorldRayDirection(sx / width, 1 - sy / height) as number[];
      const t = dir[2] !== 0 ? -eye[2] / dir[2] : 0;
      const world: XY = [eye[0] + t * dir[0] + origin[0], eye[1] + t * dir[1] + origin[1]];
      return geographic ? fromMercator(world) : world;
    },
  };
}

export interface CameraView {
  up: number[];
  lookAt: number[];
  eye: number[];
}

export function cameraView(map: any): CameraView | null {
  const camera = map?.camera;
  if (!camera?.getEye) return null;
  return { up: [...camera.getUp()], lookAt: [...camera.getLookAt()], eye: [...camera.getEye()] };
}

export function showView(map: any, view: CameraView): void {
  const camera = map?.camera;
  if (!camera?.resetCamera) return;
  camera.resetCamera(view.up, view.lookAt, view.eye);
  if (map.renderer) camera.resize(map.renderer.pixelWidth, map.renderer.pixelHeight);
  map.requestRender?.();
}

/**
 * *view* seen from straight above, as far away and facing the same way: the
 * overlay draws on the ground, and a raised building's roof only covers its
 * footprint when the map is not tilted.
 */
export function fromAbove(view: CameraView): CameraView {
  const [ex, ey, ez] = view.eye;
  const [lx, ly, lz] = view.lookAt;
  const distance = Math.hypot(ex - lx, ey - ly, ez - lz);
  let hx = lx - ex, hy = ly - ey;
  let length = Math.hypot(hx, hy);
  if (length < 1e-9) {
    [hx, hy] = view.up;
    length = Math.hypot(hx, hy);
  }
  const up = length < 1e-9 ? [0, 1, 0] : [hx / length, hy / length, 0];
  return { up, lookAt: [lx, ly, lz], eye: [lx, ly, lz + distance] };
}

/** *before*'s tilt and heading again, around where *now* looks and as far away. */
export function tiltedAgain(now: CameraView, before: CameraView): CameraView {
  const offset = before.eye.map((v, i) => v - before.lookAt[i]);
  const was = Math.hypot(...offset);
  const is = Math.hypot(...now.eye.map((v, i) => v - now.lookAt[i]));
  const scale = was > 0 ? is / was : 1;
  return { up: before.up, lookAt: now.lookAt, eye: now.lookAt.map((v, i) => v + offset[i] * scale) };
}

export function isFromAbove(view: CameraView): boolean {
  const [ex, ey] = view.eye;
  const [lx, ly] = view.lookAt;
  return Math.hypot(ex - lx, ey - ly) < 1e-6 * Math.max(1, Math.abs(view.eye[2] - view.lookAt[2]));
}

/** The heights a flattened buildings layer had, by the vertex array they were taken from. */
const SAVED_HEIGHTS = new WeakMap<Float32Array, Float32Array>();

/**
 * Draws every buildings layer of *map* flat, on the ground (*flat*), or at its
 * heights again. Only the map's own vertices change, never the data; a layer
 * the map loads again comes with its heights and is flattened anew.
 */
export function setBuildingsFlat(map: any, flat: boolean): void {
  let layers: any[] = [];
  try {
    layers = map?.layerManager?.layers ?? [];
  } catch {
    return;
  }
  let changed = false;
  for (const layer of layers) {
    if (layer?.layerInfo?.typeLayer !== "buildings") continue;
    const position: Float32Array | undefined = layer.position;
    if (!(position instanceof Float32Array)) continue;
    const saved = SAVED_HEIGHTS.get(position);
    if (flat && !saved) {
      const heights = new Float32Array(position.length / 3);
      for (let i = 0; i < heights.length; i += 1) {
        heights[i] = position[i * 3 + 2];
        position[i * 3 + 2] = 0;
      }
      SAVED_HEIGHTS.set(position, heights);
    } else if (!flat && saved) {
      for (let i = 0; i < saved.length; i += 1) position[i * 3 + 2] = saved[i];
      SAVED_HEIGHTS.delete(position);
    } else continue;
    layer._normalsAreDirty = true;
    layer.makeLayerDataDirty?.();
    changed = true;
  }
  if (changed) map.requestRender?.();
}

/** A key for what the camera shows, so the overlay draws again only when it moved. */
export function cameraKey(map: any): string {
  try {
    const m = map.camera.getViewProjectionMatrix() as ArrayLike<number>;
    return `${map.canvas.offsetWidth}x${map.canvas.offsetHeight}:${Array.from(m).map((v) => v.toFixed(6)).join(",")}`;
  } catch {
    return "";
  }
}

function inRing([x, y]: XY, ring: XY[]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function segmentDistance([px, py]: XY, [ax, ay]: XY, [bx, by]: XY): number {
  const dx = bx - ax, dy = by - ay;
  const t = dx === 0 && dy === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

/** The fewest screen pixels a click may be off a point or a line and still pick it. */
const MIN_REACH = 10;

/** How big the map draws a layer's marks, in map units: a point's radius, half a line's width. */
export interface DrawnSize {
  pointRadius: number;
  lineHalfWidth: number;
}

/** Autark's sizes for the layer *table*: its pointSize and polylinesWidth, or its defaults (64, 12). */
export function drawnSize(map: any, table: string | undefined): DrawnSize {
  let info: any;
  try {
    info = table ? map?.layerManager?.searchByLayerId?.(table)?.layerRenderInfo : undefined;
  } catch {
    info = undefined;
  }
  const positive = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && v > 0;
  const byRoad = info?.polylinesWidthByComponent as ArrayLike<number> | undefined;
  const widest = byRoad && byRoad.length > 0 ? Math.max(...Array.from(byRoad).filter(positive)) : NaN;
  return {
    pointRadius: positive(info?.pointSize) ? info.pointSize : 64,
    lineHalfWidth: (positive(widest) ? widest : positive(info?.polylinesWidth) ? info.polylinesWidth : 12) / 2,
  };
}

/**
 * The feature of *features* at screen point *s*: a click anywhere on a point
 * or a line as the map draws it picks it, and of several the one whose
 * middle or line is nearest; an area is picked inside, the top-most first.
 */
export function hitAt(features: readonly EditedFeature[], s: XY, p: Projection, size: DrawnSize): EditedFeature | null {
  let best: EditedFeature | null = null;
  let bestDistance = Infinity;
  const consider = (f: EditedFeature, distance: number) => {
    if (distance < bestDistance) {
      best = f;
      bestDistance = distance;
    }
  };
  for (let i = features.length - 1; i >= 0; i -= 1) {
    const f = features[i];
    if (!f.geometry || f.id === null) continue;
    const kind = kindOf(f.geometry);
    const { rings, closed } = toRings(f.geometry);
    if (kind === "points") {
      for (const ring of rings) {
        const [x, y] = p.toScreen(ring[0]);
        const distance = Math.hypot(x - s[0], y - s[1]);
        if (distance <= Math.max(MIN_REACH, p.pixels(ring[0], size.pointRadius))) consider(f, distance);
      }
      continue;
    }
    const screen = rings.map((ring) => ring.map(p.toScreen));
    if (kind === "areas" && screen.some((ring, r) => closed[r] && inRing(s, ring))) {
      consider(f, 0);
      continue;
    }
    for (const [r, ring] of screen.entries()) {
      const segments = closed[r] ? ring.length : ring.length - 1;
      for (let k = 0; k < segments; k += 1) {
        const distance = segmentDistance(s, ring[k], ring[(k + 1) % ring.length]);
        const reach = kind === "lines" ? Math.max(MIN_REACH, p.pixels(rings[r][k], size.lineHalfWidth)) : MIN_REACH;
        if (distance <= reach) consider(f, distance);
      }
    }
  }
  return best;
}

export function shifted(geometry: Geometry, dx: number, dy: number): Geometry {
  const moved = JSON.parse(JSON.stringify(geometry)) as Geometry;
  const shift = (value: any) => {
    if (typeof value[0] === "number") {
      value[0] += dx;
      value[1] += dy;
    } else value.forEach(shift);
  };
  shift(moved.coordinates);
  return moved;
}
