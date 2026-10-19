import type { Feature, FeatureCollection, Position } from './geojson';
import type { Wgs84Polygon } from './streetViewContract';
import { fetchData } from './resourceResolver';

export interface StreetImage {
  id: string;
  location: [number, number];
  imageUrl: string | null;
  requestedHeading: number | null;
  date: string | null;
}

export const DEFAULT_INSPECTION_DISTANCE_METRES = 60;
export type MatchedStreetImage = StreetImage & {
  outside: boolean;
  distanceFromCenter: number;
  distanceFromRequest: number;
};

async function unwrap(input: unknown, signal?: AbortSignal): Promise<any> {
  let value: any = input;
  // Data Loading produces a dict artifact reference, whereas Street View
  // Fetcher produces a geodataframe. Both use Curio's public /get route.
  for (let depth = 0; depth < 8; depth += 1) {
    if (typeof value === 'string') {
      if (!value.trim()) return null;
      try { value = JSON.parse(value); }
      catch { value = await fetchData(value, signal); }
    } else if (value?.path && !value.data) {
      value = await fetchData(value.path, signal);
    } else if (['dict', 'geodataframe', 'geojson'].includes(value?.dataType)) {
      value = value.data;
    } else if (value?.data?.type === 'FeatureCollection') {
      value = value.data;
    } else if (value?.content?.type === 'FeatureCollection') {
      value = value.content;
    } else return value;
  }
  throw new Error('Street View input contains too many nested references.');
}
export async function readStreetImages(input: unknown, signal?: AbortSignal): Promise<{ images: StreetImage[]; unavailable: number }> {
  const value: any = await unwrap(input, signal);
  if (!value) return { images: [], unavailable: 0 };
  if (value.type !== 'FeatureCollection' || !Array.isArray(value.features)) throw new Error('Street View input must be a point FeatureCollection.');
  const collection = value as FeatureCollection;
  const images: StreetImage[] = [];
  let unavailable = 0;
  for (const [index, feature] of collection.features.entries()) {
    const coords = feature.geometry?.type === 'Point' ? feature.geometry.coordinates : null;
    if (!Array.isArray(coords) || coords.length < 2 || !Number.isFinite(coords[0]) || !Number.isFinite(coords[1])
      || Math.abs(coords[0]) > 180 || Math.abs(coords[1]) > 90) { unavailable += 1; continue; }
    const props = feature.properties ?? {};
    const url = typeof props.image_url === 'string' && props.image_url.trim() ? props.image_url : null;
    const id = String(props.pano_id ?? props.image_id ?? feature.id ?? `image-${index + 1}`);
    const heading = requestedHeading(url);
    images.push({ id, location: [coords[0], coords[1]], imageUrl: url,
      requestedHeading: heading, date: typeof props.date === 'string' && props.date ? props.date : null });
    if (!url) unavailable += 1;
  }
  return { images, unavailable };
}

/** Parse only the public request parameter; never return or log the keyed URL. */
export function requestedHeading(url: string | null): number | null {
  if (!url) return null;
  try {
    const raw = new URL(url, 'http://localhost').searchParams.get('heading');
    if (raw === null || raw.trim() === '') return null;
    const value = Number(raw);
    return Number.isFinite(value) ? ((value % 360) + 360) % 360 : null;
  } catch { return null; }
}

export function polygonCenter(polygon: Wgs84Polygon): [number, number] {
  const points = polygon.coordinates[0] ?? [];
  const unique = points.length > 1 && points[0][0] === points.at(-1)?.[0] && points[0][1] === points.at(-1)?.[1]
    ? points.slice(0, -1) : points;
  return [unique.reduce((sum, p) => sum + p[0], 0) / unique.length,
    unique.reduce((sum, p) => sum + p[1], 0) / unique.length];
}
export function distanceMeters(a: Position, b: Position): number {
  const rad = Math.PI / 180;
  const phi1 = a[1] * rad, phi2 = b[1] * rad;
  const deltaPhi = (b[1] - a[1]) * rad, deltaLambda = (b[0] - a[0]) * rad;
  const h = Math.sin(deltaPhi / 2) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(deltaLambda / 2) ** 2;
  return 2 * 6371008.8 * Math.asin(Math.min(1, Math.sqrt(h)));
}
export function pointInPolygon(point: Position, polygon: Wgs84Polygon): boolean {
  const inRing = (ring: Position[]) => {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const a = ring[i], b = ring[j];
      const cross = (point[0] - a[0]) * (b[1] - a[1]) - (point[1] - a[1]) * (b[0] - a[0]);
      if (Math.abs(cross) < 1e-12 && point[0] >= Math.min(a[0], b[0]) - 1e-12 && point[0] <= Math.max(a[0], b[0]) + 1e-12
        && point[1] >= Math.min(a[1], b[1]) - 1e-12 && point[1] <= Math.max(a[1], b[1]) + 1e-12) return true;
      if ((a[1] > point[1]) !== (b[1] > point[1]) && point[0] < (b[0] - a[0]) * (point[1] - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
    }
    return inside;
  };
  return !!polygon.coordinates[0] && inRing(polygon.coordinates[0])
    && !polygon.coordinates.slice(1).some(inRing);
}
function distanceToBoundary(point: Position, polygon: Wgs84Polygon): number {
  const center = polygonCenter(polygon);
  const scaleX = 111320 * Math.cos(center[1] * Math.PI / 180), scaleY = 111320;
  let nearest = Infinity;
  for (const ring of polygon.coordinates) for (let i = 1; i < ring.length; i += 1) {
    const a = ring[i - 1], b = ring[i];
    const ax = (a[0] - point[0]) * scaleX, ay = (a[1] - point[1]) * scaleY;
    const dx = (b[0] - a[0]) * scaleX, dy = (b[1] - a[1]) * scaleY;
    const t = Math.max(0, Math.min(1, -(ax * dx + ay * dy) / (dx * dx + dy * dy || 1)));
    nearest = Math.min(nearest, Math.hypot(ax + t * dx, ay + t * dy));
  }
  return nearest;
}

/** Prefer in-tile records; the explicit nearby fallback is at most 30 m outside the polygon. */
export function imagesForTile(images: StreetImage[], polygon: Wgs84Polygon, fallbackMetres = 30): Array<StreetImage & { outside: boolean; distanceFromCenter: number }> {
  const center = polygonCenter(polygon);
  const inside = images.filter(image => pointInPolygon(image.location, polygon));
  const choices = inside.length ? inside : images.filter(image => distanceToBoundary(image.location, polygon) <= fallbackMetres);
  return choices.map(image => ({ ...image, outside: !pointInPolygon(image.location, polygon), distanceFromCenter: distanceMeters(center, image.location) }))
    .sort((a, b) => a.distanceFromCenter - b.distanceFromCenter || a.id.localeCompare(b.id));
}

/** A point request uses the actual camera point, not a tile-centre substitute. */
export function imagesForRequest(images: StreetImage[], polygon: Wgs84Polygon, requested: Position,
  maxDistanceMetres = DEFAULT_INSPECTION_DISTANCE_METRES): MatchedStreetImage[] {
  const center = polygonCenter(polygon);
  return images.filter(image => !!image.imageUrl && Number.isFinite(image.location[0]) && Number.isFinite(image.location[1]))
    .map(image => ({ ...image, outside: !pointInPolygon(image.location, polygon),
      distanceFromCenter: distanceMeters(center, image.location),
      distanceFromRequest: distanceMeters(requested, image.location) }))
    .filter(image => image.distanceFromRequest <= maxDistanceMetres)
    .sort((a, b) => a.distanceFromRequest - b.distanceFromRequest || a.id.localeCompare(b.id));
}
