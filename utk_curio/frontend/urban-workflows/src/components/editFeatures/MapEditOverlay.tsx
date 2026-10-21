/**
 * What an Interaction node does on the Autark map it feeds (#662): an overlay
 * over the map's canvas, drawn through the map's own camera, where the
 * layer the node works on is picked, drawn into and reshaped
 * (`utils/editFeatures/mapEditBus`).
 *
 * The map keeps its own gestures: a drag pans it and the wheel zooms it, in
 * every mode. A click is the node's:
 *
 * - pick: a click picks the feature under it (shift-click adds it); with the
 *   lasso on, a drag outlines the features to pick (shift-drag adds them);
 * - draw: a click places a point, or a corner of a line or an area, and a
 *   double-click, Enter or Finish ends it; Backspace takes back a corner and
 *   Escape gives up;
 * - reshape: drag a corner, click or drag a midpoint to add one, alt-click a
 *   part of a feature of several to remove it, alt-click a corner to
 *   delete it; move: drag the picked feature to move it whole.
 *
 * Only what the action is about is drawn here: the pick, the features a rule
 * matches, the handles and the line being drawn. The map draws the layers,
 * with the edits made, again after each one.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { SelectionId } from "../../utils/references/selectionTags";
import type { Geometry } from "../../utils/editFeatures/editFeatures";
import { kindOf, type EditedFeature } from "../../utils/editFeatures/layerModel";
import { editMap, fromMercator, toMercator, useMapEdit } from "../../utils/editFeatures/mapEditBus";
import { partsOf, withoutPart } from "../../utils/editFeatures/geometryParts";
import { LASSO_MIN_PIXELS, lassoPicks, outlineLength } from "../../utils/editFeatures/lasso";
import { toRings } from "./EditCanvas";

type XY = [number, number];

const BLUE = "#1F6FEB";
const RED = "#D1242F";
/** Handles grow in when they appear, around their own middle. */
const HANDLE_IN: React.CSSProperties = { cursor: "copy", transformBox: "fill-box", transformOrigin: "center", animation: "curio-handles-in 180ms ease-out" };
/** How many matched or picked features are outlined at most. */
const MAX_OUTLINED = 3000;

interface Projection {
  width: number;
  height: number;
  toScreen: (xy: XY) => XY;
  toData: (sx: number, sy: number) => XY;
  /** How many screen pixels *length* map units are at *xy* now. */
  pixels: (xy: XY, length: number) => number;
}

/** How the map shows a data coordinate now, and back: through its camera and its origin. */
function projectionOf(map: any, geographic: boolean): Projection | null {
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

interface CameraView {
  up: number[];
  lookAt: number[];
  eye: number[];
}

function cameraView(map: any): CameraView | null {
  const camera = map?.camera;
  if (!camera?.getEye) return null;
  return { up: [...camera.getUp()], lookAt: [...camera.getLookAt()], eye: [...camera.getEye()] };
}

function showView(map: any, view: CameraView): void {
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
function fromAbove(view: CameraView): CameraView {
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
function tiltedAgain(now: CameraView, before: CameraView): CameraView {
  const offset = before.eye.map((v, i) => v - before.lookAt[i]);
  const was = Math.hypot(...offset);
  const is = Math.hypot(...now.eye.map((v, i) => v - now.lookAt[i]));
  const scale = was > 0 ? is / was : 1;
  return { up: before.up, lookAt: now.lookAt, eye: now.lookAt.map((v, i) => v + offset[i] * scale) };
}

function isFromAbove(view: CameraView): boolean {
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
function setBuildingsFlat(map: any, flat: boolean): void {
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
function cameraKey(map: any): string {
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
interface DrawnSize {
  pointRadius: number;
  lineHalfWidth: number;
}

/** Autark's sizes for the layer *table*: its pointSize and polylinesWidth, or its defaults (64, 12). */
function drawnSize(map: any, table: string | undefined): DrawnSize {
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
function hitAt(features: readonly EditedFeature[], s: XY, p: Projection, size: DrawnSize): EditedFeature | null {
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

function shifted(geometry: Geometry, dx: number, dy: number): Geometry {
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

type Gesture =
  | { kind: "click"; start: XY; moved: boolean; shift: boolean }
  | { kind: "corner" | "mid"; ring: number; index: number; shape?: Geometry }
  | { kind: "move"; origin: Geometry; at: XY }
  | { kind: "lasso"; points: XY[]; shift: boolean };

export default function MapEditOverlay({ mapId }: { mapId: string }) {
  const { session, map } = useMapEdit(mapId);
  const active = session?.active ?? null;
  const box = useRef<HTMLDivElement>(null);
  const [, setTick] = useState(0);
  const [draft, setDraft] = useState<XY[]>([]);
  const [hover, setHover] = useState<XY | null>(null);
  const [dragShape, setDragShape] = useState<{ id: SelectionId; geometry: Geometry } | null>(null);
  // The lasso being drawn, in screen pixels.
  const [lassoLine, setLassoLine] = useState<XY[] | null>(null);
  const gesture = useRef<Gesture | null>(null);
  // The map's tilt before an action looked from above, put back after it.
  const tilt = useRef<CameraView | null>(null);
  const flatNow = useRef(false);

  // Draw again whenever the camera moves, and look from
  // above again when the map is tilted during the action.
  useEffect(() => {
    if (!active || !map) return;
    let frame = 0;
    let last = "";
    const loop = () => {
      if (flatNow.current) setBuildingsFlat(map, true);
      const key = cameraKey(map);
      if (key !== last) {
        last = key;
        const view = flatNow.current ? cameraView(map) : null;
        if (view && !isFromAbove(view)) {
          if (!tilt.current) tilt.current = view;
          showView(map, fromAbove(view));
        }
        setTick((t) => t + 1);
      }
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, [active, map]);

  const mode = active?.mode ?? "select";
  const kind = active?.kind ?? "points";
  useEffect(() => setDraft([]), [mode, kind, active?.table]);

  const projection = active && map ? projectionOf(map, active.geographic) : null;
  const features = active?.features ?? [];
  const shown = useMemo(
    () => features.map((f) => (dragShape && f.id !== null && String(f.id) === String(dragShape.id) ? { ...f, geometry: dragShape.geometry } : f)),
    [features, dragShape],
  );
  const selectedKeys = useMemo(
    () => new Set([...(active?.selected ?? []), ...(active?.recent ?? [])].map(String)),
    [active?.selected, active?.recent],
  );
  const matchKeys = useMemo(() => new Set((active?.matches ?? []).map(String)), [active?.matches]);
  const selectedOne = active?.selected.length === 1 ? shown.find((f) => f.id !== null && String(f.id) === String(active.selected[0])) : undefined;
  const handles = selectedOne?.geometry && (mode === "reshape" || mode === "move") ? toRings(selectedOne.geometry) : null;

  // Every layer is worked on in 2D, from straight above with the buildings
  // drawn flat: outlines and handles are on the ground, and a raised roof,
  // tilted or off the middle of the view, is not over its footprint. One fixed
  // view for points, lines and areas alike. The tilt and the heights come back
  // after, around where the map then looks.
  const flat = !!active;
  flatNow.current = flat;
  useEffect(() => {
    if (!flat || !map) return;
    const view = cameraView(map);
    if (!view || isFromAbove(view)) return;
    if (!tilt.current) tilt.current = view;
    showView(map, fromAbove(view));
  }, [flat, map]);
  useEffect(() => {
    const restore = () => {
      const before = tilt.current;
      tilt.current = null;
      const current = editMap(mapId);
      setBuildingsFlat(current, false);
      const now = cameraView(current);
      if (before && now) showView(current, tiltedAgain(now, before));
    };
    if (!flat) restore();
    return () => {
      if (flat) restore();
    };
  }, [flat, mapId]);

  const finishDraft = useCallback(() => {
    if (!session) return;
    if (kind === "lines" && draft.length >= 2) session.onDrawn({ type: "LineString", coordinates: draft });
    else if (kind === "areas" && draft.length >= 3) session.onDrawn({ type: "Polygon", coordinates: [[...draft, draft[0]]] });
    else return;
    setDraft([]);
  }, [session, kind, draft]);

  // The latest of everything the listeners read, so they are added once.
  // How big the map draws the layer's points and lines, for what a click reaches.
  const size = drawnSize(map, active?.table);
  const live = useRef({ session, active, projection, shown, selectedOne, handles, mode, kind, draft, finishDraft, dragShape, size });
  live.current = { session, active, projection, shown, selectedOne, handles, mode, kind, draft, finishDraft, dragShape, size };

  useEffect(() => {
    const host = box.current?.parentElement;
    if (!host || !active) return;
    const local = (event: MouseEvent): XY => {
      const p = live.current.projection;
      const rect = host.getBoundingClientRect();
      // An event the map's zoom fix sent again (autkMapZoom) is in the map's own pixels already.
      if ((event as any).__curioMapZoomCorrected === true) return [event.clientX - rect.left, event.clientY - rect.top];
      // Under React Flow's zoom the node is scaled: client pixels to the map's own.
      const sx = p && rect.width > 0 ? p.width / rect.width : 1;
      const sy = p && rect.height > 0 ? p.height / rect.height : 1;
      return [(event.clientX - rect.left) * sx, (event.clientY - rect.top) * sy];
    };
    const stop = (event: Event) => {
      event.stopPropagation();
      event.preventDefault();
    };
    const onDown = (event: PointerEvent) => {
      const { projection: p, selectedOne: one, handles: h, mode: m, shown: all, size: z } = live.current;
      // Heard on the window, ahead of the page's own listeners: a press on this map only.
      if (!p || event.button !== 0 || !host.contains(event.target as Node)) return;
      const target = event.target as Element;
      // The overlay's own buttons are buttons.
      if (target.closest?.("[data-map-edit-ui]")) return;
      const ring = target.getAttribute?.("data-ring");
      const index = target.getAttribute?.("data-index");
      if (h && one && ring !== null && index !== null && ring !== undefined) {
        stop(event);
        const r = Number(ring), i = Number(index);
        if (event.altKey && target.getAttribute("data-handle") === "corner") {
          const rings = h.rings.map((rr) => [...rr]);
          const min = h.closed[r] ? 3 : kindOf(one.geometry) === "points" ? 1 : 2;
          if (rings[r].length > min) {
            rings[r].splice(i, 1);
            live.current.session?.onReshape(one.id as SelectionId, h.rebuild(rings));
          }
          return;
        }
        gesture.current = { kind: target.getAttribute("data-handle") === "mid" ? "mid" : "corner", ring: r, index: i };
        return;
      }
      const s = local(event);
      // Moving points, an alt-click inside one part of a feature of several
      // takes that part away (a corner's own alt-click deletes the corner).
      if (m === "reshape" && event.altKey && one?.geometry && one.id !== null) {
        const parts = partsOf(one.geometry);
        const hit = parts.length > 1 ? parts.findIndex((part) => hitAt([{ ...one, geometry: part }], s, p, z) !== null) : -1;
        const rest = hit >= 0 ? withoutPart(one.geometry, hit) : null;
        if (rest) {
          stop(event);
          live.current.session?.onReshape(one.id as SelectionId, rest);
          return;
        }
      }
      // Moving a feature whole is a shift-drag on it; a plain drag pans the map.
      if (m === "move" && event.shiftKey && one?.geometry && hitAt(all, s, p, z)?.id === one.id) {
        stop(event);
        gesture.current = { kind: "move", origin: one.geometry, at: p.toData(s[0], s[1]) };
        host.style.cursor = "grabbing";
        return;
      }
      // With the lasso on, a drag outlines what to pick, in place of a pan.
      if (m === "select" && live.current.active?.lasso) {
        stop(event);
        gesture.current = { kind: "lasso", points: [s], shift: event.shiftKey };
        return;
      }
      // A press the map may turn into a pan: a click only if it stays put.
      gesture.current = { kind: "click", start: s, moved: false, shift: event.shiftKey };
    };
    const onMove = (event: PointerEvent) => {
      const { projection: p, selectedOne: one, mode: m } = live.current;
      if (!p) return;
      const s = local(event);
      if (m === "draw") setHover(p.toData(s[0], s[1]));
      const g = gesture.current;
      if (!g) {
        // Moving it whole, the picked feature shows it can be grabbed with shift held.
        const grab = m === "move" && event.shiftKey && !!one?.geometry && hitAt([one], s, p, live.current.size) !== null;
        host.style.cursor = grab ? "grab" : "";
        return;
      }
      if (g.kind === "lasso") {
        stop(event);
        g.points.push(s);
        setLassoLine([...g.points]);
        return;
      }
      // Shift-drag would tilt and turn Autark's camera, which the view from
      // above then snaps back, a flicker each move: the map never sees it.
      if (event.shiftKey && (event.buttons & 1) === 1) stop(event);
      if (g.kind === "click") {
        if (Math.hypot(s[0] - g.start[0], s[1] - g.start[1]) > 6) g.moved = true;
        return;
      }
      // A drag of the node's own is not the map's: autk-map starts a pan on
      // a move with the button held even when it never saw the press, and
      // panning under the pointer would leave the feature where it was.
      stop(event);
      if (!one?.geometry || one.id === null) return;
      const at = p.toData(s[0], s[1]);
      if (g.kind === "move") {
        setDragShape({ id: one.id, geometry: shifted(g.origin, at[0] - g.at[0], at[1] - g.at[1]) });
        return;
      }
      // The shape the drag started on, with a midpoint's corner once added.
      const base = toRings(g.shape ?? one.geometry);
      const rings = base.rings.map((rr) => [...rr]);
      if (g.kind === "corner") rings[g.ring][g.index] = at;
      else {
        // A midpoint adds its corner once; the rest of the drag moves it.
        rings[g.ring].splice(g.index + 1, 0, at);
        gesture.current = { kind: "corner", ring: g.ring, index: g.index + 1, shape: base.rebuild(rings) };
      }
      setDragShape({ id: one.id, geometry: base.rebuild(rings) });
    };
    const onUp = (event: PointerEvent) => {
      const g = gesture.current;
      gesture.current = null;
      if (g?.kind === "move") host.style.cursor = "grab";
      const { projection: p, session: s, mode: m, kind: k, shown: all, dragShape: dragged, size: z } = live.current;
      if (!g || !p || !s) return;
      if (g.kind === "lasso") {
        setLassoLine(null);
        // Too short to outline anything: a click, which picks what is under it.
        if (outlineLength(g.points) < LASSO_MIN_PIXELS) s.onSelect(hitAt(all, g.points[0], p, z)?.id ?? null, g.shift);
        else s.onSelectMany?.(lassoPicks(all, g.points, p.toScreen), g.shift);
        return;
      }
      // A click on a midpoint adds its corner there; no drag is needed.
      if (g.kind === "mid") {
        const one = live.current.selectedOne;
        if (one?.geometry && one.id !== null) {
          const base = toRings(one.geometry);
          const rings = base.rings.map((rr) => [...rr]);
          const a = rings[g.ring][g.index], b = rings[g.ring][(g.index + 1) % rings[g.ring].length];
          rings[g.ring].splice(g.index + 1, 0, [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]);
          s.onReshape(one.id as SelectionId, base.rebuild(rings));
        }
        setDragShape(null);
        return;
      }
      if (g.kind !== "click") {
        if (dragged) s.onReshape(dragged.id, dragged.geometry);
        setDragShape(null);
        return;
      }
      if (g.moved) return;
      const at = p.toData(g.start[0], g.start[1]);
      if (m === "draw") {
        if (k === "points") s.onDrawn({ type: "Point", coordinates: at });
        else setDraft((current) => [...current, at]);
        return;
      }
      if (m === "reshape" || m === "move") {
        const found = hitAt(all, g.start, p, z);
        if (found) s.onSelect(found.id, false);
        return;
      }
      s.onSelect(hitAt(all, g.start, p, z)?.id ?? null, g.shift);
    };
    const onDouble = (event: MouseEvent) => {
      // The map's own double-click pick is not the node's.
      stop(event);
      if (live.current.mode !== "draw") return;
      // Its two clicks placed two corners at one point: keep one.
      setDraft((current) => (current.length >= 2 ? current.slice(0, -1) : current));
      setTimeout(() => live.current.finishDraft(), 0);
    };
    // A click on the map is the node's, not a pick of the map's own.
    const onClick = (event: MouseEvent) => {
      if (!(event.target as Element).closest?.("[data-map-edit-ui]")) event.stopPropagation();
    };
    const onKey = (event: KeyboardEvent) => {
      if (live.current.mode !== "draw" || /^(INPUT|SELECT|TEXTAREA)$/.test((event.target as HTMLElement)?.tagName ?? "")) return;
      let handled = true;
      if (event.key === "Enter") live.current.finishDraft();
      else if (event.key === "Escape") setDraft([]);
      else if (event.key === "Backspace" && live.current.draft.length > 0) setDraft((current) => current.slice(0, -1));
      else handled = false;
      if (handled) stop(event);
    };
    window.addEventListener("pointerdown", onDown, true);
    host.addEventListener("dblclick", onDouble, true);
    host.addEventListener("click", onClick, true);
    window.addEventListener("pointermove", onMove, true);
    window.addEventListener("pointerup", onUp, true);
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("pointerdown", onDown, true);
      host.removeEventListener("dblclick", onDouble, true);
      host.removeEventListener("click", onClick, true);
      window.removeEventListener("pointermove", onMove, true);
      window.removeEventListener("pointerup", onUp, true);
      window.removeEventListener("keydown", onKey, true);
      host.style.cursor = "";
    };
  }, [!!active]);

  if (!active) return null;
  // The box is there before the camera is, so the listeners have their host.
  if (!projection) return <div ref={box} data-testid="map-edit-overlay" style={{ position: "absolute", inset: 0, pointerEvents: "none" }} />;
  const p = projection;
  const path = (geometry: Geometry) => {
    const { rings, closed } = toRings(geometry);
    return rings.map((ring, r) => ring.map((xy, i) => `${i === 0 ? "M" : "L"}${p.toScreen(xy).map((v) => v.toFixed(1)).join(" ")}`).join(" ") + (closed[r] ? " Z" : "")).join(" ");
  };
  /** A ring around a feature too small to see on the map as it is zoomed. */
  const SMALL_PX = 14;
  const outline = (f: EditedFeature, color: string, dashed: boolean) => {
    if (!f.geometry) return null;
    const id = String(f.id);
    if (kindOf(f.geometry) === "points") {
      return toRings(f.geometry).rings.map((ring, r) => {
        const [x, y] = p.toScreen(ring[0]);
        // Around the point as the map draws it.
        const radius = Math.max(7, p.pixels(ring[0], size.pointRadius) + 2);
        return (
          <g key={`${id}-${r}`}>
            <circle cx={x} cy={y} r={radius + 2} fill="none" stroke="#FFFFFF" strokeWidth={4} />
            <circle cx={x} cy={y} r={radius} fill={`${color}40`} stroke={color} strokeWidth={2.5} strokeDasharray={dashed ? "3 2" : undefined} />
          </g>
        );
      });
    }
    const d = path(f.geometry);
    const screen = toRings(f.geometry).rings.flat().map(p.toScreen);
    const xs = screen.map(([x]) => x), ys = screen.map(([, y]) => y);
    const small = screen.length > 0 && Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) < SMALL_PX;
    const width = dashed ? 2 : 3.5;
    return (
      <g key={id}>
        {/* A white casing, so the outline reads on a busy map. */}
        <path d={d} fill="none" stroke="#FFFFFF" strokeWidth={width + 3} strokeLinejoin="round" strokeLinecap="round" />
        <path
          d={d}
          fill={kindOf(f.geometry) === "areas" ? `${color}2E` : "none"}
          stroke={color}
          strokeWidth={width}
          strokeDasharray={dashed ? "5 3" : undefined}
          strokeLinejoin="round"
          strokeLinecap="round"
          fillRule="evenodd"
        />
        {small ? (
          <circle
            cx={(Math.max(...xs) + Math.min(...xs)) / 2}
            cy={(Math.max(...ys) + Math.min(...ys)) / 2}
            r={12}
            fill="none"
            stroke={color}
            strokeWidth={2.5}
            strokeDasharray={dashed ? "3 2" : undefined}
          />
        ) : null}
      </g>
    );
  };
  // The pick and the features a rule matches are shown by the overlay's own
  // outlines alone, on the ground where the map draws them (buildings flat).
  const picked = shown.filter((f) => f.id !== null && selectedKeys.has(String(f.id))).slice(0, MAX_OUTLINED);
  const matched = matchKeys.size > 0 ? shown.filter((f) => f.id !== null && matchKeys.has(String(f.id))).slice(0, MAX_OUTLINED) : [];
  const draftScreen = draft.map(p.toScreen);
  const hoverScreen = hover && mode === "draw" && draft.length > 0 ? p.toScreen(hover) : null;
  const noun = active.noun;
  const tip =
    mode === "draw"
      ? kind === "points"
        ? `Point tool · click to place a ${noun} · drag to pan`
        : `${kind === "lines" ? "Line" : "Area"} tool · click to add points · double-click to finish · Esc to cancel`
      : mode === "reshape"
        ? kind === "points"
          ? `Moving the ${noun} · drag it`
          : `Moving points · drag a corner · click or drag a midpoint to add one · alt-click a corner to delete it${selectedOne?.geometry && partsOf(selectedOne.geometry).length > 1 ? " · alt-click inside a part to remove it" : ""}`
        : mode === "move"
          ? `Moving the whole ${noun} · shift-drag it · drag to pan`
          : active.lasso
            ? `Lasso · drag around ${noun}s to pick them · shift-drag adds`
            : `Drag to pan · click a ${noun} to pick it · shift-click adds`;
  // Changing a shape, the tip says so in blue, with Done to go back to panning.
  const shaping = mode === "reshape" || mode === "move";
  const last = draftScreen[draftScreen.length - 1];

  return (
    <div ref={box} data-testid="map-edit-overlay" data-edit-mode={mode} data-edit-layer={active.table} style={{ position: "absolute", inset: 0, pointerEvents: "none", cursor: mode === "draw" || (mode === "select" && active.lasso) ? "crosshair" : undefined }}>
      <svg width={p.width} height={p.height} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }} aria-hidden="true">
        {matched.map((f) => outline(f, RED, true))}
        {picked.map((f) => outline(f, BLUE, false))}
        <style>{"@keyframes curio-handles-in { from { opacity: 0; transform: scale(0.6); } to { opacity: 1; transform: scale(1); } } @media (prefers-reduced-motion: reduce) { .curio-handle { animation: none !important; } }"}</style>
        {handles
          ? handles.rings.map((ring, r) => (
              <g key={`ring-${r}`} style={{ pointerEvents: "auto" }}>
                {mode === "reshape" && ring.length > 1
                  ? ring.slice(0, handles.closed[r] ? ring.length : ring.length - 1).map((xy, i) => {
                      const next = ring[(i + 1) % ring.length];
                      const [x, y] = p.toScreen([(xy[0] + next[0]) / 2, (xy[1] + next[1]) / 2]);
                      return <circle key={`m${i}-${selectedOne?.id}`} className="curio-handle" data-handle="mid" data-ring={r} data-index={i} cx={x} cy={y} r={4} fill="#FFFFFF" stroke={BLUE} strokeWidth={1.5} opacity={0.85} style={HANDLE_IN} />;
                    })
                  : null}
                {mode === "reshape"
                  ? ring.map((xy, i) => {
                      const [x, y] = p.toScreen(xy);
                      return <circle key={`c${i}-${selectedOne?.id}`} className="curio-handle" data-handle="corner" data-ring={r} data-index={i} cx={x} cy={y} r={6} fill="#FFFFFF" stroke={BLUE} strokeWidth={2} style={{ ...HANDLE_IN, cursor: "grab" }} />;
                    })
                  : null}
              </g>
            ))
          : null}
        {lassoLine && lassoLine.length > 1 ? (
          <polygon data-testid="map-edit-lasso" points={lassoLine.map((pt) => pt.join(",")).join(" ")} fill={`${BLUE}1A`} stroke={BLUE} strokeWidth={1.5} strokeDasharray="5 4" strokeLinejoin="round" />
        ) : null}
        {draftScreen.length > 0 ? (
          <>
            <polyline
              points={[...draftScreen, ...(hoverScreen ? [hoverScreen] : [])].map((pt) => pt.join(",")).join(" ")}
              fill={kind === "areas" ? `${BLUE}26` : "none"}
              stroke={BLUE}
              strokeWidth={3}
              strokeLinejoin="round"
            />
            {draftScreen.map(([x, y], i) => (
              <circle key={i} cx={x} cy={y} r={5} fill="#FFFFFF" stroke={BLUE} strokeWidth={2.5} />
            ))}
          </>
        ) : null}
      </svg>
      {last ? (
        <span
          data-testid="map-edit-draft-label"
          style={{ position: "absolute", left: last[0] + 10, top: last[1] - 30, background: BLUE, color: "#FFFFFF", fontSize: 12, fontWeight: 600, padding: "3px 9px", borderRadius: 999, whiteSpace: "nowrap" }}
        >
          New {noun} · {draft.length} point{draft.length === 1 ? "" : "s"}
        </span>
      ) : null}
      <div data-map-edit-ui="true" style={{ position: "absolute", left: 10, top: 10, display: "flex", gap: 6, alignItems: "center", pointerEvents: "auto" }}>
        <span data-testid="map-edit-tip" style={{ background: shaping ? BLUE : "rgba(22,27,34,0.88)", color: "#FFFFFF", fontSize: 12, padding: "6px 10px", borderRadius: 8, transition: "background-color 160ms ease" }}>
          {tip}
        </span>
        {shaping && session?.onShapeDone ? (
          <button
            type="button"
            data-testid="map-edit-done"
            className="nodrag nopan"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={() => session.onShapeDone?.()}
            style={{ minHeight: 28, padding: "0 12px", borderRadius: 8, border: `1px solid ${BLUE}`, background: "#FFFFFF", color: BLUE, fontWeight: 600, fontSize: 12, cursor: "pointer" }}
          >
            Done
          </button>
        ) : null}
        {mode === "draw" && kind !== "points" ? (
          <button
            type="button"
            data-testid="map-edit-finish"
            className="nodrag nopan"
            disabled={draft.length < (kind === "areas" ? 3 : 2)}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={() => finishDraft()}
            style={{ minHeight: 28, padding: "0 10px", borderRadius: 8, border: 0, background: BLUE, color: "#FFFFFF", fontWeight: 600, fontSize: 12, opacity: draft.length < (kind === "areas" ? 3 : 2) ? 0.5 : 1 }}
          >
            Finish
          </button>
        ) : null}
      </div>
    </div>
  );
}
