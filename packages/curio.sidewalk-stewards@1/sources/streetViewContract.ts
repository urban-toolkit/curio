import type { Feature, Position } from './geojson';

export const ACTIVE_TILE_CHANNEL = 'sidewalk.active-tile';
export const ACTIVE_TILE_REQUEST_CHANNEL = 'sidewalk.active-tile-request';
export const INSPECTION_REQUEST_CHANNEL = 'sidewalk.inspection-request';
export const CAMERA_CONTEXT_CHANNEL = 'sidewalk.camera-context';
export const ACTIVE_TILE_SCHEMA = 'io.github.lzml0.sidewalk-stewards/active-tile/v1';
export const ACTIVE_TILE_REQUEST_SCHEMA = 'io.github.lzml0.sidewalk-stewards/active-tile-request/v1';
export const INSPECTION_REQUEST_SCHEMA = 'io.github.lzml0.sidewalk-stewards/inspection-request/v1';
export const CAMERA_CONTEXT_SCHEMA = 'io.github.lzml0.sidewalk-stewards/camera-context/v1';

export type Wgs84Polygon = { type: 'Polygon'; coordinates: Position[][] };
export interface ActiveTileEvent {
  schema: typeof ACTIVE_TILE_SCHEMA;
  editorId: string;
  sourceFingerprint: string;
  selectionEpoch: string;
  selectionRevision: number;
  tileId: string | null;
  geometry: Wgs84Polygon | null;
  crs: 'EPSG:4326';
}
export interface ActiveTileRequest {
  schema: typeof ACTIVE_TILE_REQUEST_SCHEMA;
  viewerId: string;
  viewerEpoch?: string;
  requestRevision: number;
}
export interface InspectionRequest {
  schema: typeof INSPECTION_REQUEST_SCHEMA;
  editorId: string;
  sourceFingerprint: string;
  selectionEpoch: string;
  selectionRevision: number;
  requestRevision: number;
  tileId: string;
  location: [number, number];
  crs: 'EPSG:4326';
}
export interface CameraContextEvent {
  schema: typeof CAMERA_CONTEXT_SCHEMA;
  editorId: string;
  sourceFingerprint: string;
  selectionEpoch: string;
  selectionRevision: number;
  viewerId: string;
  tileId: string;
  imageId: string;
  displayRevision: number;
  /** Absent on older tile-only events; null means no point request. */
  requestRevision?: number | null;
  location: [number, number] | null;
  headingDegrees: number | null;
  headingMeaning: 'requested-static-image' | 'live-view-direction' | null;
}

function latest(interactions: unknown, channel: string): any | null {
  if (!Array.isArray(interactions)) return null;
  const events = interactions.flatMap((entry: any) => {
    const event = entry?.details?.[channel];
    return event ? [{ event, priority: Number(entry.priority ?? 0) }] : [];
  });
  if (!events.length) return null;
  const priority = Math.max(...events.map(item => item.priority));
  return events.filter(item => item.priority === priority).at(-1)?.event ?? null;
}
export function latestActiveTile(interactions: unknown): ActiveTileEvent | null {
  const event = latest(interactions, ACTIVE_TILE_CHANNEL);
  return event?.schema === ACTIVE_TILE_SCHEMA && typeof event.editorId === 'string'
    && typeof event.sourceFingerprint === 'string' && typeof event.selectionEpoch === 'string'
    && Number.isSafeInteger(event.selectionRevision) && event.selectionRevision >= 0
    && (event.tileId === null || typeof event.tileId === 'string')
    && (event.geometry === null || event.geometry?.type === 'Polygon')
    && event.crs === 'EPSG:4326' ? event : null;
}
export function latestActiveTileRequest(interactions: unknown): ActiveTileRequest | null {
  const event = latest(interactions, ACTIVE_TILE_REQUEST_CHANNEL);
  return event?.schema === ACTIVE_TILE_REQUEST_SCHEMA && typeof event.viewerId === 'string'
    && (event.viewerEpoch === undefined || typeof event.viewerEpoch === 'string')
    && Number.isSafeInteger(event.requestRevision) ? event : null;
}
export function latestInspectionRequest(interactions: unknown): InspectionRequest | null {
  const event = latest(interactions, INSPECTION_REQUEST_CHANNEL);
  return event?.schema === INSPECTION_REQUEST_SCHEMA && typeof event.editorId === 'string'
    && typeof event.sourceFingerprint === 'string' && typeof event.selectionEpoch === 'string'
    && Number.isSafeInteger(event.selectionRevision) && event.selectionRevision >= 0
    && Number.isSafeInteger(event.requestRevision) && event.requestRevision >= 1
    && typeof event.tileId === 'string' && event.tileId.length > 0 && event.crs === 'EPSG:4326'
    && validWgs84Point(event.location) ? event : null;
}
export function latestCameraContext(interactions: unknown): CameraContextEvent | null {
  const event = latest(interactions, CAMERA_CONTEXT_CHANNEL);
  return event?.schema === CAMERA_CONTEXT_SCHEMA && typeof event.editorId === 'string'
    && typeof event.sourceFingerprint === 'string' && typeof event.selectionEpoch === 'string'
    && Number.isSafeInteger(event.selectionRevision) && typeof event.viewerId === 'string'
    && typeof event.tileId === 'string' && typeof event.imageId === 'string'
    && Number.isSafeInteger(event.displayRevision)
    && (event.requestRevision === undefined || event.requestRevision === null
      || (Number.isSafeInteger(event.requestRevision) && event.requestRevision >= 1))
    && (event.location === null || (Array.isArray(event.location)
      && event.location.length === 2 && event.location.every(Number.isFinite)))
    && (event.headingDegrees === null || Number.isFinite(event.headingDegrees))
    && (event.headingMeaning === null || event.headingMeaning === 'requested-static-image' || event.headingMeaning === 'live-view-direction')
    ? event : null;
}

export function validWgs84Point(point: unknown): point is [number, number] {
  return Array.isArray(point) && point.length === 2 && point.every(Number.isFinite)
    && Math.abs(point[0]) <= 180 && Math.abs(point[1]) <= 90;
}

export function pointToWgs84(point: Position, crs?: string | null): [number, number] {
  if (crs === null || crs === undefined || crs === 'EPSG:4326') {
    if (!validWgs84Point(point)) throw new Error('Inspection point is outside WGS84 coordinates.');
    return [point[0], point[1]];
  }
  if (crs !== 'EPSG:3857') throw new Error(`Unsupported tile CRS: ${crs}`);
  const longitude = point[0] / 6378137 * 180 / Math.PI;
  const latitude = (2 * Math.atan(Math.exp(point[1] / 6378137)) - Math.PI / 2) * 180 / Math.PI;
  if (!validWgs84Point([longitude, latitude])) throw new Error('Inspection point is outside WGS84 coordinates.');
  return [longitude, latitude];
}

/** GeoJSON defaults to WGS84. Explicit Web Mercator is converted, never relabelled. */
export function tileGeometryWgs84(feature: Feature, crs?: string | null): Wgs84Polygon {
  if (feature.geometry?.type !== 'Polygon') throw new Error('The active tile must be a polygon.');
  const sourceCrs = crs ?? 'EPSG:4326';
  if (sourceCrs !== 'EPSG:4326' && sourceCrs !== 'EPSG:3857') throw new Error(`Unsupported tile CRS: ${sourceCrs}`);
  const coordinates = feature.geometry.coordinates.map(ring => ring.map((point: Position): Position => {
    if (point.length < 2 || !Number.isFinite(point[0]) || !Number.isFinite(point[1])) throw new Error('Invalid tile coordinate.');
    if (sourceCrs === 'EPSG:4326') return [point[0], point[1]];
    const longitude = point[0] / 6378137 * 180 / Math.PI;
    const latitude = (2 * Math.atan(Math.exp(point[1] / 6378137)) - Math.PI / 2) * 180 / Math.PI;
    return [longitude, latitude];
  }));
  if (!coordinates.length || coordinates[0].length < 4) throw new Error('Invalid tile polygon.');
  return { type: 'Polygon', coordinates };
}

export function pointFromWgs84(point: Position, crs?: string | null): Position {
  if (crs === null || crs === undefined || crs === 'EPSG:4326') return [point[0], point[1]];
  if (crs !== 'EPSG:3857') throw new Error(`Unsupported tile CRS: ${crs}`);
  const latitude = Math.max(-85.05112878, Math.min(85.05112878, point[1]));
  return [6378137 * point[0] * Math.PI / 180,
    6378137 * Math.log(Math.tan(Math.PI / 4 + latitude * Math.PI / 360))];
}

export function sourceFingerprint(sourceIdentity: string | undefined, imageTemplate: string, networkTemplate: string, source?: unknown): string {
  if (sourceIdentity) return sourceIdentity;
  const sourceValue: any = source;
  const identity = typeof sourceValue === 'string' ? sourceValue
    : sourceValue?.type === 'FeatureCollection' && Array.isArray(sourceValue.features)
      ? sourceValue.features.map((feature: any) => [feature.properties?.tile_id ?? feature.id, feature.geometry])
      : sourceValue?.path ?? sourceValue?.metadata?.sourceIdentity ?? null;
  const value = JSON.stringify([imageTemplate, networkTemplate, identity]);
  let hash = 2166136261;
  for (let i = 0; i < value.length; i += 1) hash = Math.imul(hash ^ value.charCodeAt(i), 16777619);
  return `fnv1a-${(hash >>> 0).toString(16).padStart(8, '0')}`;
}

export function cameraMatchesTile(camera: CameraContextEvent, tile: ActiveTileEvent): boolean {
  return tile.tileId !== null && camera.editorId === tile.editorId && camera.sourceFingerprint === tile.sourceFingerprint
    && camera.selectionEpoch === tile.selectionEpoch && camera.selectionRevision === tile.selectionRevision
    && camera.tileId === tile.tileId;
}

export function inspectionMatchesTile(request: InspectionRequest, tile: ActiveTileEvent): boolean {
  return tile.tileId !== null && request.editorId === tile.editorId
    && request.sourceFingerprint === tile.sourceFingerprint
    && request.selectionEpoch === tile.selectionEpoch
    && request.selectionRevision === tile.selectionRevision && request.tileId === tile.tileId;
}
