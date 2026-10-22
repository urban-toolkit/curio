/**
 * The drawing tools a Map Edits node lends the Autark maps it feeds and is
 * linked to (#662).
 *
 * The Map Edits node is the panel: its layers, the action, the forms and
 * the edit log. A map is where features are drawn and reshaped. They meet
 * here, by the map's node id and the Map Edits node's:
 *
 * - the Map Edits node publishes a session (`publishMapSession`) while an
 *   action is under way: the layer being worked on, as the map names it, and
 *   its features as the log leaves them, the mode of the action, the shape
 *   being drawn, and what a shape drawn or reshaped on the map becomes;
 * - the Autark node registers each map it draws (`registerEditMap`), whose
 *   camera and origin the overlay on it (`MapEditOverlay`) reads.
 *
 * Picks are not here: a pick on the map is the map's selection, which the
 * interaction edge carries to the Map Edits node, as a selection crosses
 * between two views, and what the node picks, or a rule matches, comes back
 * the same way (`providers/flow/useInteractions`). The edits reach the map on
 * the data edge (`mapEditsPreview`).
 */
import { useSyncExternalStore } from "react";
import type { SelectionId } from "../references/selectionTags";
import type { Geometry } from "./editFeatures";
import type { EditedFeature, GeometryKind } from "./layerModel";

export type MapEditMode = "select" | "draw" | "reshape" | "move";

export interface MapEditActive {
  /** The table the map draws the layer under. */
  table: string;
  label: string;
  kind: GeometryKind;
  /** What one feature is called: "road". */
  noun: string;
  mode: MapEditMode;
  /** Picks by a rule: what the node selects is what the rule matches, outlined as about to change. */
  rule?: boolean;
  /** The layer's features as the log leaves them. */
  features: EditedFeature[];
  /** The shape drawn but not yet added. */
  draft?: Geometry | null;
  /** Longitude-latitude coordinates (else the map's own Mercator metres). */
  geographic: boolean;
  /** The column a feature's id is read from, which a pick names it by. */
  key?: string;
}

export interface MapEditSession {
  interactionId: string;
  /** Show only this layer: the table the map keeps drawing, hiding its others. */
  solo?: string | null;
  active: MapEditActive | null;
  onDrawn: (geometry: Geometry) => void;
  onReshape: (id: SelectionId, geometry: Geometry) => void;
  /** Turns the shape mode (reshape, move) off again: the map's Done. */
  onShapeDone?: () => void;
}

/** Each map's sessions, by the Map Edits node that published each, the latest last. */
const sessions = new Map<string, Map<string, MapEditSession>>();
const maps = new Map<string, any>();
const layerIds = new Map<string, (table: string) => string>();
const listeners = new Map<string, Set<() => void>>();

function notify(mapId: string) {
  for (const listener of listeners.get(mapId) ?? []) listener();
}

/**
 * Publish, or with null take back, the session the Map Edits node
 * *nodeId* edits *mapId* with. A node takes back its own session only: a map
 * two nodes feed keeps the other's.
 */
export function publishMapSession(mapId: string, nodeId: string, session: MapEditSession | null): void {
  const mine = sessions.get(mapId) ?? new Map<string, MapEditSession>();
  if (session === null) {
    if (!mine.has(nodeId)) return;
    mine.delete(nodeId);
  } else {
    // The latest published is the one the map shows.
    mine.delete(nodeId);
    mine.set(nodeId, session);
  }
  if (mine.size > 0) sessions.set(mapId, mine);
  else sessions.delete(mapId);
  notify(mapId);
}

/** The session *mapId* is edited with now: the latest a Map Edits node published. */
export function mapSession(mapId: string): MapEditSession | undefined {
  const mine = sessions.get(mapId);
  return mine ? [...mine.values()].at(-1) : undefined;
}

/** The autk map *mapId* drew last, for the overlay on it. */
export function registerEditMap(mapId: string, map: any, layerIdOf?: (table: string) => string): void {
  if (map) maps.set(mapId, map);
  else maps.delete(mapId);
  if (map && layerIdOf) layerIds.set(mapId, layerIdOf);
  else layerIds.delete(mapId);
  notify(mapId);
}

export function editMap(mapId: string): any {
  return maps.get(mapId);
}

/** The id *mapId*'s map gives the layer that draws *table* (a titled layer goes by its title). */
export function editMapLayerId(mapId: string, table: string): string {
  return layerIds.get(mapId)?.(table) ?? table;
}

function subscribe(mapId: string, listener: () => void): () => void {
  const set = listeners.get(mapId) ?? new Set();
  set.add(listener);
  listeners.set(mapId, set);
  return () => set.delete(listener);
}

/** The session and map of *mapId*, read in a component; it renders again when either changes. */
export function useMapEdit(mapId: string): { session: MapEditSession | undefined; map: any } {
  const session = useSyncExternalStore(
    (listener) => subscribe(mapId, listener),
    () => mapSession(mapId),
    () => undefined,
  );
  const map = useSyncExternalStore(
    (listener) => subscribe(mapId, listener),
    () => maps.get(mapId),
    () => undefined,
  );
  return { session, map };
}

/** Subscribe to *mapId*'s session outside React. */
export function onMapSession(mapId: string, listener: () => void): () => void {
  return subscribe(mapId, listener);
}

// World Mercator (EPSG:3395), the projection autk-db draws every layer in: what
// a longitude-latitude coordinate is on the map, and back.
const A = 6378137;
const E = 0.0818191908426215;

export function toMercator([lon, lat]: [number, number]): [number, number] {
  const phi = (Math.max(-89.9, Math.min(89.9, lat)) * Math.PI) / 180;
  const sin = Math.sin(phi);
  const y = A * Math.log(Math.tan(Math.PI / 4 + phi / 2) * Math.pow((1 - E * sin) / (1 + E * sin), E / 2));
  return [(A * lon * Math.PI) / 180, y];
}

export function fromMercator([x, y]: [number, number]): [number, number] {
  const t = Math.exp(-y / A);
  let phi = Math.PI / 2 - 2 * Math.atan(t);
  for (let i = 0; i < 8; i += 1) {
    const sin = Math.sin(phi);
    phi = Math.PI / 2 - 2 * Math.atan(t * Math.pow((1 - E * sin) / (1 + E * sin), E / 2));
  }
  return [((x / A) * 180) / Math.PI, (phi * 180) / Math.PI];
}
