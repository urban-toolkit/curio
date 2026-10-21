/**
 * How an Interaction node edits on the Autark map that feeds it (#662).
 *
 * The Interaction node is the panel: its layers, the action, the forms and
 * the edit log. The map is where features are picked, drawn and reshaped.
 * They meet here, by the map's node id:
 *
 * - the Interaction node publishes a session (`publishMapSession`) while an
 *   action is under way: the layer being worked on, its features as the log
 *   leaves them, the pick, and what a click on the map does;
 * - the Autark node registers each map it draws (`registerEditMap`), whose
 *   camera and origin the overlay on it (`MapEditOverlay`) reads.
 *
 * The edit log itself reaches the map as the Interaction node's setting
 * (`utils/editFeatures/mapLayerEdits`): the map draws, and hands on, its
 * layers with the edits applied.
 */
import { useSyncExternalStore } from "react";
import type { SelectionId } from "../references/selectionTags";
import type { Geometry } from "./editFeatures";
import type { EditedFeature, GeometryKind } from "./layerModel";

export type MapEditMode = "select" | "draw" | "reshape" | "move";

export interface MapEditActive {
  /** The table name the map draws the layer under. */
  table: string;
  label: string;
  kind: GeometryKind;
  /** What one feature is called: "road". */
  noun: string;
  mode: MapEditMode;
  /** The layer's features as the log leaves them. */
  features: EditedFeature[];
  selected: SelectionId[];
  /** Features a rule matches, drawn as about to be removed. */
  matches?: SelectionId[];
  /** Features just added or edited, lit up once the map draws them again. */
  recent?: SelectionId[];
  /** Longitude-latitude coordinates (else the map's own Mercator metres). */
  geographic: boolean;
  /** The column a feature's id is read from, for the map's own highlight. */
  key?: string;
  /** In select mode, a drag draws a lasso that picks what it encloses, in place of a pan. */
  lasso?: boolean;
}

export interface MapEditSession {
  interactionId: string;
  /** Show only this layer: the table the map keeps drawing, hiding its others. */
  solo?: string | null;
  active: MapEditActive | null;
  onSelect: (id: SelectionId | null, additive: boolean) => void;
  /** A lasso's pick: these features, added to the pick when *additive*. */
  onSelectMany?: (ids: SelectionId[], additive: boolean) => void;
  onDrawn: (geometry: Geometry) => void;
  onReshape: (id: SelectionId, geometry: Geometry) => void;
  /** Turns the shape mode (reshape, move) off again: the map's Done. */
  onShapeDone?: () => void;
}

const sessions = new Map<string, MapEditSession>();
const maps = new Map<string, any>();
const layerIds = new Map<string, (table: string) => string>();
const listeners = new Map<string, Set<() => void>>();

function notify(mapId: string) {
  for (const listener of listeners.get(mapId) ?? []) listener();
}

/** Publish, or with null take back, the session an Interaction node edits *mapId* with. */
export function publishMapSession(mapId: string, session: MapEditSession | null): void {
  const current = sessions.get(mapId);
  if (session === null) {
    if (!current) return;
    sessions.delete(mapId);
  } else sessions.set(mapId, session);
  notify(mapId);
}

/** The session *mapId* is edited with, if any. */
export function mapSession(mapId: string): MapEditSession | undefined {
  return sessions.get(mapId);
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
    () => sessions.get(mapId),
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
