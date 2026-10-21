/**
 * A feature's parts (#662): the polygons of a MultiPolygon, the lines of a
 * MultiLineString, the points of a MultiPoint; a single geometry is one part.
 * An Interaction node draws a feature part by part, adds a part to one, and
 * takes one away.
 */
import type { Geometry } from "./editFeatures";

const MULTI: Record<string, string> = { Point: "MultiPoint", LineString: "MultiLineString", Polygon: "MultiPolygon" };
const SINGLE: Record<string, string> = { MultiPoint: "Point", MultiLineString: "LineString", MultiPolygon: "Polygon" };

/** The parts of *geometry*, each a single geometry. */
export function partsOf(geometry: Geometry | null | undefined): Geometry[] {
  if (!geometry) return [];
  const single = SINGLE[geometry.type];
  if (single) return ((geometry as any).coordinates as any[]).map((coordinates) => ({ type: single, coordinates }) as Geometry);
  return MULTI[geometry.type] ? [geometry] : [];
}

/** *parts* as one geometry: a single one alone, else the Multi kind of theirs. */
export function fromParts(parts: readonly Geometry[]): Geometry | null {
  if (parts.length === 0) return null;
  if (parts.length === 1) return parts[0];
  const multi = MULTI[parts[0].type];
  if (!multi || parts.some((p) => p.type !== parts[0].type)) return null;
  return { type: multi, coordinates: parts.map((p) => (p as any).coordinates) } as Geometry;
}

/** *geometry* with *part* added, or null when they are not the same kind. */
export function withPart(geometry: Geometry | null | undefined, part: Geometry): Geometry | null {
  const parts = partsOf(geometry);
  if (parts.length > 0 && parts[0].type !== partsOf(part)[0]?.type) return null;
  return fromParts([...parts, ...partsOf(part)]);
}

/** *geometry* without its part *index*, or null when that would leave none. */
export function withoutPart(geometry: Geometry | null | undefined, index: number): Geometry | null {
  const parts = partsOf(geometry);
  if (parts.length < 2 || index < 0 || index >= parts.length) return null;
  return fromParts(parts.filter((_, i) => i !== index));
}
