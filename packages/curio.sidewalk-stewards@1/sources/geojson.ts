/** Minimal GeoJSON types used by this package; no runtime dependency. */
export type Position = number[];
export interface LineString { type: 'LineString'; coordinates: Position[]; }
export interface MultiLineString { type: 'MultiLineString'; coordinates: Position[][]; }
export interface Polygon { type: 'Polygon'; coordinates: Position[][]; }
export interface GeometryCollection { type: 'GeometryCollection'; geometries: Array<Geometry | null>; }
export type Geometry = LineString | MultiLineString | Polygon | GeometryCollection | { type: string; coordinates?: any };
export interface Feature<G extends Geometry | null = Geometry | null, P = Record<string, any>> {
  type: 'Feature'; id?: string | number; geometry: G; properties: P | null;
}
export interface FeatureCollection<G extends Geometry | null = Geometry | null, P = Record<string, any>> {
  type: 'FeatureCollection'; features: Array<Feature<G, P>>; [key: string]: any;
}
