/** Public, versioned interaction contract. Coordinates are WGS84 [longitude, latitude]. */
export const PANORAMA_REQUEST_CHANNEL = 'curio.panorama.request';
export const PANORAMA_CAMERA_CHANNEL = 'curio.panorama.camera';
export const PANORAMA_CONTEXT_CHANNEL = 'curio.panorama.context';
export const PANORAMA_STATUS_CHANNEL = 'curio.panorama.status';
export const PANORAMA_REQUEST_SCHEMA = 'curio.streetvision/panorama-request/v1';
export const PANORAMA_CAMERA_SCHEMA = 'curio.streetvision/panorama-camera/v1';
export const PANORAMA_CONTEXT_SCHEMA = 'curio.streetvision/panorama-context/v1';
export const PANORAMA_STATUS_SCHEMA = 'curio.streetvision/panorama-status/v1';

export type Point = [number, number];
export interface PanoramaRequest {
  schema: typeof PANORAMA_REQUEST_SCHEMA;
  requestId: string;
  revision: number;
  location: Point;
  crs: 'EPSG:4326';
  radiusMetres?: number;
  initialHeadingDegrees?: number;
  /** Adopt this viewer's already displayed panorama when an editor changes tile. */
  reuseCurrent?: { viewerId: string; panoId: string };
}
export interface PanoramaCamera {
  schema: typeof PANORAMA_CAMERA_SCHEMA;
  requestId: string;
  revision: number;
  viewerId: string;
  cameraRevision: number;
  requestedLocation: Point;
  actualLocation: Point;
  panoId: string;
  headingDegrees: number;
  headingReference: 'clockwise-from-true-north';
  pitchDegrees?: number;
  zoom?: number;
}
export interface PanoramaContext {
  schema: typeof PANORAMA_CONTEXT_SCHEMA;
  requestId: string;
  revision: number;
  active: false;
}
export interface PanoramaStatus {
  schema: typeof PANORAMA_STATUS_SCHEMA;
  requestId: string;
  revision: number;
  viewerId: string;
  state: 'missing-key' | 'invalid-key' | 'loading' | 'unavailable' | 'error' | 'confirmed';
  /** Credential-free provider diagnostic suitable for inline presentation. */
  message?: string;
}
export function latestPanoramaStatus(interactions: unknown): PanoramaStatus | null {
  if (!Array.isArray(interactions)) return null;
  const candidates = interactions.flatMap((entry: any) => {
    const status = entry?.details?.[PANORAMA_STATUS_CHANNEL];
    return status?.schema === PANORAMA_STATUS_SCHEMA && typeof status.requestId === 'string'
      && Number.isSafeInteger(status.revision) && typeof status.viewerId === 'string'
      && ['missing-key', 'invalid-key', 'loading', 'unavailable', 'error', 'confirmed'].includes(status.state)
      ? [{ status: status as PanoramaStatus, priority: Number(entry.priority ?? 0) }] : [];
  });
  if (!candidates.length) return null;
  const priority = Math.max(...candidates.map(entry => entry.priority));
  return candidates.filter(entry => entry.priority === priority).at(-1)?.status ?? null;
}
export function validPoint(value: unknown): value is Point {
  return Array.isArray(value) && value.length === 2 && value.every(Number.isFinite)
    && Math.abs(value[0]) <= 180 && Math.abs(value[1]) <= 90;
}
export function readPanoramaRequest(value: any): PanoramaRequest | null {
  if (!value || value.schema !== PANORAMA_REQUEST_SCHEMA || typeof value.requestId !== 'string'
    || !value.requestId || !Number.isSafeInteger(value.revision) || value.revision < 0
    || value.crs !== 'EPSG:4326' || !validPoint(value.location)) return null;
  if (value.radiusMetres !== undefined && (!Number.isFinite(value.radiusMetres) || value.radiusMetres < 1 || value.radiusMetres > 1000)) return null;
  if (value.initialHeadingDegrees !== undefined && !Number.isFinite(value.initialHeadingDegrees)) return null;
  if (value.reuseCurrent !== undefined && (typeof value.reuseCurrent?.viewerId !== 'string'
    || !value.reuseCurrent.viewerId || typeof value.reuseCurrent?.panoId !== 'string')) return null;
  return value;
}
export function latestPanoramaRequest(interactions: unknown): PanoramaRequest | null {
  if (!Array.isArray(interactions)) return null;
  const candidates = interactions.flatMap((entry: any) => {
    const request = readPanoramaRequest(entry?.details?.[PANORAMA_REQUEST_CHANNEL]);
    return request ? [{ request, priority: Number(entry.priority ?? 0) }] : [];
  });
  if (!candidates.length) return null;
  const priority = Math.max(...candidates.map(entry => entry.priority));
  return candidates.filter(entry => entry.priority === priority).at(-1)?.request ?? null;
}
export function latestPanoramaCamera(interactions: unknown): PanoramaCamera | null {
  if (!Array.isArray(interactions)) return null;
  const candidates = interactions.flatMap((entry: any) => {
    const camera = entry?.details?.[PANORAMA_CAMERA_CHANNEL];
    return camera?.schema === PANORAMA_CAMERA_SCHEMA && typeof camera.requestId === 'string'
      && Number.isSafeInteger(camera.revision) && Number.isSafeInteger(camera.cameraRevision)
      && typeof camera.viewerId === 'string' && validPoint(camera.actualLocation)
      && validPoint(camera.requestedLocation) && Number.isFinite(camera.headingDegrees)
      && camera.headingReference === 'clockwise-from-true-north'
      ? [{ camera, priority: Number(entry.priority ?? 0) }] : [];
  });
  if (!candidates.length) return null;
  const priority = Math.max(...candidates.map(entry => entry.priority));
  return candidates.filter(entry => entry.priority === priority).at(-1)?.camera ?? null;
}
export function latestPanoramaContext(interactions: unknown): PanoramaContext | null {
  const event = Array.isArray(interactions) ? interactions.flatMap((entry: any) => {
    const context = entry?.details?.[PANORAMA_CONTEXT_CHANNEL];
    return context?.schema === PANORAMA_CONTEXT_SCHEMA && typeof context.requestId === 'string'
      && Number.isSafeInteger(context.revision) && context.active === false
      ? [{ context, priority: Number(entry.priority ?? 0) }] : [];
  }) : [];
  if (!event.length) return null;
  const priority = Math.max(...event.map(item => item.priority));
  return event.filter(item => item.priority === priority).at(-1)?.context ?? null;
}
