import type { Feature, FeatureCollection, Position } from './geojson';
import { featureBounds, type Bounds } from './sidewalkEditOperations';

export type TileDirection = 'north' | 'south' | 'east' | 'west';
export const TILE_DIRECTIONS: TileDirection[] = ['north', 'south', 'east', 'west'];

interface Cell {
  id: string;
  feature: Feature;
  bounds: Bounds;
  x: number | null;
  y: number | null;
  zoom: number | null;
  sides: Record<TileDirection, Array<[number, number]>>;
}

export interface TileNeighborIndex {
  features: Map<string, Feature>;
  bounds: Map<string, Bounds>;
  positions: Map<string, number>;
  neighbors: Map<string, Partial<Record<TileDirection, string>>>;
}

const tileId = (feature: Feature): string => String(feature.properties?.tile_id ?? feature.properties?.tileId ?? feature.id ?? '');
const integer = (value: unknown): number | null => Number.isSafeInteger(Number(value)) && value !== null && value !== '' ? Number(value) : null;
const bucket = (coordinate: number, tolerance: number): number => Math.round(coordinate / tolerance);
const cellKey = (zoom: number, x: number, y: number): string => `${zoom}/${x}/${y}`;

function boundarySegments(feature: Feature, bounds: Bounds, tolerance: number): Cell['sides'] {
  const sides: Cell['sides'] = { north: [], south: [], east: [], west: [] };
  const geometry = feature.geometry;
  const rings: Position[][] = geometry?.type === 'Polygon' ? geometry.coordinates
    : geometry?.type === 'MultiPolygon' ? geometry.coordinates.flat() : [];
  for (const ring of rings) for (let i = 1; i < ring.length; i += 1) {
    const a = ring[i - 1]; const b = ring[i];
    if (Math.abs(a[1] - b[1]) <= tolerance && Math.abs(a[0] - b[0]) > tolerance) {
      const segment: [number, number] = [Math.min(a[0], b[0]), Math.max(a[0], b[0])];
      if (Math.abs(a[1] - bounds[3]) <= tolerance) sides.north.push(segment);
      if (Math.abs(a[1] - bounds[1]) <= tolerance) sides.south.push(segment);
    }
    if (Math.abs(a[0] - b[0]) <= tolerance && Math.abs(a[1] - b[1]) > tolerance) {
      const segment: [number, number] = [Math.min(a[1], b[1]), Math.max(a[1], b[1])];
      if (Math.abs(a[0] - bounds[2]) <= tolerance) sides.east.push(segment);
      if (Math.abs(a[0] - bounds[0]) <= tolerance) sides.west.push(segment);
    }
  }
  return sides;
}

function sharedSide(a: Cell, b: Cell, direction: TileDirection, tolerance: number): number {
  const opposite: Record<TileDirection, TileDirection> = { north: 'south', south: 'north', east: 'west', west: 'east' };
  const [ai, bi] = direction === 'north' ? [3, 1] : direction === 'south' ? [1, 3]
    : direction === 'east' ? [2, 0] : [0, 2];
  if (Math.abs(a.bounds[ai] - b.bounds[bi]) > tolerance) return 0;
  let overlap = 0;
  for (const first of a.sides[direction]) for (const second of b.sides[opposite[direction]]) {
    overlap += Math.max(0, Math.min(first[1], second[1]) - Math.max(first[0], second[0]));
  }
  return overlap > tolerance ? overlap : 0;
}

/** Build once per prepared grid/source revision; never infer adjacency from tile IDs. */
export function buildTileNeighborIndex(grid: FeatureCollection): TileNeighborIndex {
  const raw = grid.features.flatMap(feature => {
    const id = tileId(feature); const bounds = featureBounds(feature);
    return id && bounds ? [{ id, feature, bounds }] : [];
  });
  const dimensions = raw.flatMap(({ bounds }) => [bounds[2] - bounds[0], bounds[3] - bounds[1]]).filter(value => value > 0);
  const tolerance = dimensions.reduce((minimum, value) => Math.min(minimum, value), 1) * 1e-5;
  const cells: Cell[] = raw.map(({ id, feature, bounds }) => ({
    id, feature, bounds, x: integer(feature.properties?.x), y: integer(feature.properties?.y),
    zoom: integer(feature.properties?.zoom), sides: boundarySegments(feature, bounds, tolerance),
  }));
  const features = new Map(cells.map(cell => [cell.id, cell.feature]));
  const positions = new Map(grid.features.map((feature, position) => [tileId(feature), position]));
  const metadata = new Map<string, Cell>();
  const sideBuckets = new Map<string, Cell[]>();
  for (const cell of cells) {
    if (cell.x !== null && cell.y !== null && cell.zoom !== null) metadata.set(cellKey(cell.zoom, cell.x, cell.y), cell);
    for (const [direction, coordinate] of [
      ['north', cell.bounds[3]], ['south', cell.bounds[1]], ['east', cell.bounds[2]], ['west', cell.bounds[0]],
    ] as Array<[TileDirection, number]>) {
      const key = `${direction}:${bucket(coordinate, tolerance)}`;
      const existing = sideBuckets.get(key);
      if (existing) existing.push(cell);
      else sideBuckets.set(key, [cell]);
    }
  }
  const opposite: Record<TileDirection, TileDirection> = { north: 'south', south: 'north', east: 'west', west: 'east' };
  const neighbors = new Map<string, Partial<Record<TileDirection, string>>>();
  for (const cell of cells) {
    const result: Partial<Record<TileDirection, string>> = {};
    for (const direction of TILE_DIRECTIONS) {
      const [dx, dy] = direction === 'north' ? [0, -1] : direction === 'south' ? [0, 1]
        : direction === 'east' ? [1, 0] : [-1, 0];
      const byMetadata = cell.x !== null && cell.y !== null && cell.zoom !== null
        ? metadata.get(cellKey(cell.zoom, cell.x + dx, cell.y + dy)) : undefined;
      const candidates = new Set<Cell>();
      if (byMetadata) candidates.add(byMetadata);
      const coordinate = direction === 'north' ? cell.bounds[3] : direction === 'south' ? cell.bounds[1]
        : direction === 'east' ? cell.bounds[2] : cell.bounds[0];
      const center = bucket(coordinate, tolerance);
      for (let offset = -1; offset <= 1; offset += 1) {
        for (const candidate of sideBuckets.get(`${opposite[direction]}:${center + offset}`) ?? []) candidates.add(candidate);
      }
      const ranked = [...candidates].filter(candidate => candidate !== cell).map(candidate => ({
        candidate, overlap: sharedSide(cell, candidate, direction, tolerance),
      })).filter(item => item.overlap > 0).sort((a, b) => b.overlap - a.overlap || a.candidate.id.localeCompare(b.candidate.id));
      if (ranked.length) result[direction] = ranked[0].candidate.id;
    }
    neighbors.set(cell.id, result);
  }
  return { features, bounds: new Map(cells.map(cell => [cell.id, cell.bounds])), positions, neighbors };
}

/** Resolve an actual camera position against the prepared grid, only on explicit adoption. */
export function tileAtPoint(index: TileNeighborIndex, point: Position): string | null {
  for (const [id, bounds] of index.bounds) {
    if (point[0] < bounds[0] || point[0] > bounds[2] || point[1] < bounds[1] || point[1] > bounds[3]) continue;
    const feature = index.features.get(id);
    if (feature?.geometry?.type === 'Polygon') {
      // Grid cells are rectangular in the canonical example, but respect the polygon itself.
      const ring = feature.geometry.coordinates[0] ?? [];
      let inside = false;
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const a = ring[i], b = ring[j];
        if ((a[1] > point[1]) !== (b[1] > point[1])
          && point[0] < (b[0] - a[0]) * (point[1] - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
      }
      if (!inside) continue;
    }
    return id;
  }
  return null;
}
