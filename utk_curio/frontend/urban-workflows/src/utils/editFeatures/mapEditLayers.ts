/**
 * The drawing tools of a Map Editor node, drawn by the Autark map it edits on
 * (#662): the shape being drawn and its corners, a shape waiting to be added,
 * and a feature being reshaped or moved, with its corners and midpoints. They
 * are layers of the map itself, loaded through autk-map's own
 * `loadCollection` and drawn in its highlight at a fixed size on the screen,
 * so nothing is drawn over the map (`MapEditOverlay` hears the pointer and
 * holds the tip). Each draw of a map is a new map, which gets them again.
 *
 * autk-map draws its buildings after every flat layer, over them, and the
 * tools are flat: a feature being reshaped or moved is skipped in its own
 * layer meanwhile and drawn by the tools, so it does not cover its handles.
 */
import type { Geometry } from "./editFeatures";
import { toRings } from "./geometryRings";
import { kindOf } from "./layerModel";
import { toMercator } from "./mapEditBus";
import { projectionOf, type XY } from "./mapEditGeometry";

/** What the tools show, in the coordinates of the layer worked on. */
export interface MapEditTools {
  /** Whole shapes: one waiting to be added, a feature being reshaped or moved. */
  shapes: Geometry[];
  /** The shape being drawn: its corners so far, then the pointer. */
  path: XY[];
  /** The corners of the shape being drawn, or the ones a drag moves. */
  corners: XY[];
  /** The midpoints a click or a drag adds a corner at. */
  midpoints: XY[];
  /** The feature the tools draw instead of its layer: that layer's id, and where in it the map draws the feature. */
  hidden: { layer: string; positions: number[] } | null;
}

// The tool layers, bottom to top, by the names autk-map's layer menu lists
// them under while they are drawn.
const AREA = "Map Editor: area";
const SHAPE = "Map Editor: shape";
const MIDPOINTS = "Map Editor: midpoints";
const CORNERS = "Map Editor: corners";
const TOOL_LAYERS = [AREA, SHAPE, MIDPOINTS, CORNERS];

/** Whether the map layer *id* is one of the tools, never kept, hidden or picked on as the document's layers are. */
export function isMapEditToolLayer(id: unknown): boolean {
  return typeof id === "string" && TOOL_LAYERS.includes(id);
}

/** The screen pixels of a corner's radius, a midpoint's and a line's width. */
const CORNER_PX = 6;
const MIDPOINT_PX = 4;
const LINE_PX = 3;
/** How opaque an area is under its outline. */
const AREA_OPACITY = 0.35;

/** Each tool layer's type, and how it is drawn at *units* map units to a screen pixel. */
const STYLE: Record<string, { type: "polygons" | "polylines" | "points"; info: (units: number) => Record<string, unknown> }> = {
  [AREA]: { type: "polygons", info: () => ({ opacity: AREA_OPACITY, showBorders: false }) },
  [SHAPE]: { type: "polylines", info: (units) => ({ opacity: 1, polylinesWidth: LINE_PX * units }) },
  [MIDPOINTS]: { type: "points", info: (units) => ({ opacity: 1, pointSize: MIDPOINT_PX * units }) },
  [CORNERS]: { type: "points", info: (units) => ({ opacity: 1, pointSize: CORNER_PX * units }) },
};

/**
 * The features of each tool layer for *tools*, in the map's units, World
 * Mercator metres. A line has two points at least and an area three corners
 * in each ring: autk-map draws nothing of less.
 */
function toolFeatures(tools: MapEditTools, geographic: boolean): Record<string, object[]> {
  const at = (xy: XY): XY => (geographic ? toMercator(xy) : [xy[0], xy[1]]);
  const everywhere = (value: any): any => (typeof value[0] === "number" ? at(value as XY) : value.map(everywhere));
  const feature = (geometry: object) => ({ type: "Feature", geometry, properties: {} });
  const line = (points: XY[]) => feature({ type: "LineString", coordinates: points.map(at) });
  const point = (xy: XY) => feature({ type: "Point", coordinates: at(xy) });
  const out: Record<string, object[]> = { [AREA]: [], [SHAPE]: [], [MIDPOINTS]: tools.midpoints.map(point), [CORNERS]: [] };
  for (const shape of tools.shapes) {
    const kind = kindOf(shape);
    const { rings, closed } = toRings(shape);
    // A point is its one corner.
    if (kind === "points") {
      out[CORNERS].push(...rings.map((ring) => point(ring[0])));
      continue;
    }
    if (kind === "areas" && rings.every((ring) => ring.length >= 3)) {
      out[AREA].push(feature({ type: shape.type, coordinates: everywhere(shape.coordinates) }));
    }
    rings.forEach((ring, r) => {
      if (ring.length >= 2) out[SHAPE].push(line(closed[r] ? [...ring, ring[0]] : ring));
    });
  }
  if (tools.path.length >= 2) out[SHAPE].push(line(tools.path));
  out[CORNERS].push(...tools.corners.map(point));
  return out;
}

/** How many map units one screen pixel is now, in the middle of *map*'s view; null before it has a camera and a size. */
function unitsPerPixel(map: any): number | null {
  const p = projectionOf(map, false);
  if (!p) return null;
  const pixels = p.pixels(p.toData(p.width / 2, p.height / 2), 1);
  return Number.isFinite(pixels) && pixels > 0 ? 1 / pixels : null;
}

/** Whether *map* holds the layer *id* now. */
function holds(map: any, id: string): boolean {
  const layers = map?.layerManager?.layers;
  return Array.isArray(layers) && layers.some((layer: any) => layer?.layerInfo?.id === id);
}

/** What a map shows of the tools: its tool layers and what they were loaded from, their size, and the feature skipped. */
interface Shown {
  ids: string[];
  features: string;
  units: string;
  hidden: { layer: string; key: string } | null;
}

const shownOn = new WeakMap<object, Shown>();

/**
 * Show *tools* on *map*, or none (null): each tool layer added, loaded again
 * when what it draws changed, or removed, drawn in the map's highlight at its
 * size on the screen now; and the feature the tools draw skipped in its own
 * layer, the skip cleared once they draw none.
 */
export function showMapEditTools(map: any, tools: MapEditTools | null, geographic: boolean): void {
  if (!map || typeof map.loadCollection !== "function") return;
  const was = shownOn.get(map) ?? { ids: [], features: "", units: "", hidden: null };
  const now: Shown = { ...was };
  try {
    const features = tools ? toolFeatures(tools, geographic) : null;
    const key = features ? JSON.stringify(features) : "";
    if (key !== was.features) {
      // All loaded again, bottom to top: autk-map draws the layer loaded last over the others.
      for (const id of was.ids) if (holds(map, id)) map.removeLayer(id);
      now.ids = TOOL_LAYERS.filter((id) => (features?.[id]?.length ?? 0) > 0);
      for (const id of now.ids) {
        map.loadCollection(id, { collection: { type: "FeatureCollection", features: features![id] }, type: STYLE[id].type });
      }
      now.features = key;
      now.units = "";
    }
    // Sizes are in map units: a layer loaded takes its type's own, and a zoom changes what a pixel is.
    const units = unitsPerPixel(map);
    if (units !== null && now.ids.length > 0 && units.toPrecision(4) !== now.units) {
      const color = map.style?.getHighlightColor?.();
      for (const id of now.ids) map.updateRenderInfo(id, { ...(color ? { color } : {}), ...STYLE[id].info(units) });
      now.units = units.toPrecision(4);
    }
    // The feature drawn by the tools, skipped in its layer: autk-map toggles
    // each position it is given, so the layer's skips are cleared first.
    const hidden = tools?.hidden && tools.hidden.positions.length > 0 ? tools.hidden : null;
    const positions = hidden ? [...new Set(hidden.positions)] : [];
    const hiddenKey = hidden ? `${hidden.layer}:${positions.join(",")}` : null;
    if (hiddenKey !== (was.hidden?.key ?? null)) {
      if (was.hidden) map.clearSkippedIds?.(was.hidden.layer);
      if (hidden && hiddenKey) {
        map.clearSkippedIds?.(hidden.layer);
        map.setSkippedIds?.(hidden.layer, positions);
      }
      now.hidden = hidden && hiddenKey ? { layer: hidden.layer, key: hiddenKey } : null;
    }
  } catch (error) {
    console.warn("[map edits] showing the drawing tools on the map failed:", error);
  }
  if (now.ids.length === 0 && !now.hidden) shownOn.delete(map);
  else shownOn.set(map, now);
}
