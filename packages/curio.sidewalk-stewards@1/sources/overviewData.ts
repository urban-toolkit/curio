import type { Feature, FeatureCollection, Position } from './geojson';
import type { SidewalkTileEditConfig } from './SidewalkTileEditor';
import { featureBounds, type Bounds } from './sidewalkEditOperations';

export interface OverviewConfig {
  datasetId: string;
  sourceIdentity?: string;
  gridUrl: string;
  networkUrl: string;
  boundariesUrl: string;
}
export interface OverviewContext {
  grid: FeatureCollection;
  network: FeatureCollection;
  boundaries: FeatureCollection;
}

export function stableJson(value: unknown): string {
  return JSON.stringify(value, (_key, item) => item && typeof item === 'object' && !Array.isArray(item)
    ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item);
}
export function overviewIdentity(config: SidewalkTileEditConfig): string {
  return stableJson([config.overview, config.imageUrlTemplate, config.networkUrlTemplate]);
}
export function tileStorageKey(config: SidewalkTileEditConfig, tileId: string): string {
  return config.overview ? `${overviewIdentity(config)}:${tileId}` : tileId;
}
function legacyDataset(config: SidewalkTileEditConfig): boolean {
  const o = config.overview;
  const root = 'docs/examples/data/sidewalk-stewards-regions';
  return !!o && !o.sourceIdentity && o.datasetId === 'recife-z19' && o.gridUrl === `${root}/tile-grid.geojson`
    && o.networkUrl === `${root}/overview-network.geojson` && o.boundariesUrl === `${root}/tile-boundaries.geojson`
    && config.imageUrlTemplate === `${root}/tiles/{tile_id}.png`
    && config.networkUrlTemplate === `${root}/tile-network/{tile_id}.geojson`;
}
export function savedTile(config: SidewalkTileEditConfig, tileId: string) {
  const current = config.byTile[tileStorageKey(config, tileId)];
  if (current) return current;
  // Untagged v1 records belong only to the original prepared Recife dataset.
  return !config.overview || legacyDataset(config) ? config.byTile[tileId] : undefined;
}
/** Move original unscoped Recife records into the same dataset-keyed store on persistence. */
export function scopeLegacyTiles(config: SidewalkTileEditConfig): SidewalkTileEditConfig {
  if (!legacyDataset(config)) return config;
  const byTile = { ...config.byTile };
  for (const [id, record] of Object.entries(config.byTile)) {
    if (!/^[a-zA-Z0-9_-]+$/.test(id)) continue;
    const key = tileStorageKey(config, id);
    byTile[key] ??= record;
    delete byTile[id];
  }
  return { ...config, byTile };
}
export function committedSignature(config: SidewalkTileEditConfig, grid: FeatureCollection): string {
  return stableJson(grid.features.map(feature => {
    const id = String(feature.properties?.tile_id ?? '');
    const record = savedTile(config, id);
    return [id, record?.committedNetwork, record?.revision, record?.provenance, record?.committedEdit];
  }));
}

export function validateOverview(context: OverviewContext): void {
  const ids = new Set<string>();
  if (!context.grid.features.length) throw new Error('Overview grid contains no tiles.');
  for (const tile of context.grid.features) {
    const id = tile.properties?.tile_id;
    const bounds = featureBounds(tile);
    if (typeof id !== 'string' || !id || ids.has(id)) throw new Error('Overview tiles need unique tile_id values.');
    if (tile.geometry?.type !== 'Polygon' || !bounds || bounds.some(v => !Number.isFinite(v))
      || bounds[0] >= bounds[2] || bounds[1] >= bounds[3]
      || tile.geometry.coordinates.length !== 1 || tile.geometry.coordinates[0].length !== 5
      || tile.geometry.coordinates[0].some((p: Position) => ![bounds[0], bounds[2]].includes(p[0]) || ![bounds[1], bounds[3]].includes(p[1]))) {
      throw new Error('Overview replacement requires rectangular tile polygons.');
    }
    ids.add(id);
  }
  if (context.network.features.some(f => !['LineString', 'MultiLineString'].includes(f.geometry?.type ?? ''))) {
    throw new Error('Overview network must contain line features.');
  }
}

const equalPoint = (a: Position, b: Position) => a.length === b.length && a.every((v, i) => Math.abs(v - b[i]) < 1e-12);
type TileBounds = { id: string; bounds: Bounds };
function lineBounds(coordinates: Position[]): Bounds {
  return [Math.min(...coordinates.map(p => p[0])), Math.min(...coordinates.map(p => p[1])),
    Math.max(...coordinates.map(p => p[0])), Math.max(...coordinates.map(p => p[1]))];
}
/** Bucket rectangular tiles once so full-area linework only checks nearby tiles. */
function tileLookup(tiles: TileBounds[]) {
  if (!tiles.length) return (_bounds: Bounds): TileBounds[] => [];
  const originX = Math.min(...tiles.map(tile => tile.bounds[0]));
  const originY = Math.min(...tiles.map(tile => tile.bounds[1]));
  const width = Math.max(1e-12, Math.min(...tiles.map(tile => tile.bounds[2] - tile.bounds[0])));
  const height = Math.max(1e-12, Math.min(...tiles.map(tile => tile.bounds[3] - tile.bounds[1])));
  const buckets = new Map<string, TileBounds[]>();
  const cells = (bounds: Bounds) => {
    const epsilon = 1e-12;
    const x0 = Math.floor((bounds[0] - epsilon - originX) / width);
    const x1 = Math.floor((bounds[2] + epsilon - originX) / width);
    const y0 = Math.floor((bounds[1] - epsilon - originY) / height);
    const y1 = Math.floor((bounds[3] + epsilon - originY) / height);
    const result: string[] = [];
    for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) result.push(`${x}:${y}`);
    return result;
  };
  for (const tile of tiles) for (const cell of cells(tile.bounds)) {
    const bucket = buckets.get(cell) ?? [];
    bucket.push(tile);
    buckets.set(cell, bucket);
  }
  return (bounds: Bounds): TileBounds[] => {
    const found = new Map<string, TileBounds>();
    for (const cell of cells(bounds)) for (const tile of buckets.get(cell) ?? []) {
      const b = tile.bounds;
      if (b[0] <= bounds[2] + 1e-12 && b[2] >= bounds[0] - 1e-12
        && b[1] <= bounds[3] + 1e-12 && b[3] >= bounds[1] - 1e-12) found.set(tile.id, tile);
    }
    return [...found.values()].sort((a, b) => a.id.localeCompare(b.id));
  };
}
function splitLine(coordinates: Position[], tiles: Array<{ id: string; bounds: Bounds }>, keep: (owner: string | undefined) => boolean) {
  const parts: Position[][] = [];
  let active: Position[] = [];
  let removed = false;
  const flush = () => { if (active.length > 1) parts.push(active); active = []; };
  for (let i = 1; i < coordinates.length; i++) {
    const a = coordinates[i - 1], b = coordinates[i];
    const cuts = new Set([0, 1]);
    for (const { bounds } of tiles) {
      for (const axis of [0, 1]) {
        if (b[axis] === a[axis]) continue;
        for (const edge of [bounds[axis], bounds[axis + 2]]) {
          const t = (edge - a[axis]) / (b[axis] - a[axis]);
          if (t > 0 && t < 1) cuts.add(t);
        }
      }
    }
    const sorted = [...cuts].sort((x, y) => x - y);
    const point = (t: number) => t === 0 ? a : t === 1 ? b : a.map((v, axis) => v + t * (b[axis] - v));
    for (let j = 1; j < sorted.length; j++) {
      const start = point(sorted[j - 1]), end = point(sorted[j]);
      if (equalPoint(start, end)) continue;
      const midpoint = [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2];
      // Shared-border line segments belong to the lexicographically first tile.
      const owner = tiles.find(({ bounds: q }) => midpoint[0] >= q[0] - 1e-12 && midpoint[0] <= q[2] + 1e-12
        && midpoint[1] >= q[1] - 1e-12 && midpoint[1] <= q[3] + 1e-12)?.id;
      if (!keep(owner)) { removed = true; flush(); continue; }
      if (active.length && !equalPoint(active[active.length - 1], start)) flush();
      if (!active.length) active = [start];
      active.push(end);
    }
  }
  flush();
  return { parts, removed };
}
function lines(feature: Feature): Position[][] {
  return feature.geometry?.type === 'MultiLineString' ? feature.geometry.coordinates
    : feature.geometry?.type === 'LineString' ? [feature.geometry.coordinates] : [];
}

// autk-db's default metric workspace reduces geometry to a 0.01 m grid.
// Tile clipping can create fragments smaller than one grid-cell diagonal;
// those collapse on import and prevent the entire After layer from loading.
// Keep the committed network and provenance exact; omit only such generated
// fragments from the derived overview display.
function renderableFragment(coordinates: Position[]): boolean {
  if (coordinates.length < 2) return false;
  const lat = coordinates.reduce((sum, point) => sum + point[1], 0) / coordinates.length;
  const xScale = 111_320 * Math.cos(lat * Math.PI / 180);
  const yScale = 111_320;
  const xs = coordinates.map(point => point[0]);
  const ys = coordinates.map(point => point[1]);
  return Math.hypot((Math.max(...xs) - Math.min(...xs)) * xScale,
    (Math.max(...ys) - Math.min(...ys)) * yScale) >= 0.015;
}

/** Replace owned portions of original linework; committed empty tiles are deletions. */
export function buildOverview(context: OverviewContext, config: SidewalkTileEditConfig, latestTileOutput?: unknown) {
  validateOverview(context);
  const tiles = context.grid.features.map(tile => ({ id: String(tile.properties?.tile_id), bounds: featureBounds(tile)! }))
    .sort((a, b) => a.id.localeCompare(b.id));
  const edits = tiles.flatMap(tile => {
    const record = savedTile(config, tile.id);
    return record?.committedNetwork ? [{ ...tile, record }] : [];
  });
  const committedIds = new Set(edits.map(e => e.id));
  const nearbyTiles = tileLookup(tiles);
  const nearbyEdits = tileLookup(edits);
  const features: Feature[] = [];
  for (const [index, feature] of context.network.features.entries()) {
    const sourceLines = lines(feature);
    if (!sourceLines.some(line => nearbyEdits(lineBounds(line)).length)) {
      features.push(feature);
      continue;
    }
    const split = sourceLines.map(line => splitLine(line, nearbyTiles(lineBounds(line)),
      owner => !owner || !committedIds.has(owner)));
    if (!split.some(s => s.removed)) { features.push(feature); continue; }
    split.flatMap(s => s.parts).filter(renderableFragment).forEach((coordinates, part) => features.push({ ...feature,
      id: `base:${String(feature.id ?? index)}:${index}:outside:${part}`, geometry: { type: 'LineString', coordinates } }));
  }
  for (const { id, record } of edits) {
    record.committedNetwork!.features.forEach((feature, index) => {
      lines(feature).flatMap(line => splitLine(line, nearbyTiles(lineBounds(line)), owner => owner === id).parts)
        .filter(renderableFragment).forEach((coordinates, part) => {
        features.push({ ...feature, id: `saved:${config.overview!.datasetId}:${id}:${index}:${part}`,
          geometry: { type: 'LineString', coordinates }, properties: { ...feature.properties,
            // AutkMap's supported roads classification gives new sidewalk edges the same thin path style.
            highway: feature.properties?.highway ?? 'path', tile_id: id,
            sidewalk_dataset_id: config.overview!.datasetId, sidewalk_edit_revision: record.revision ?? 1,
            sidewalk_source_feature_id: feature.id ?? index, sidewalk_provenance_ref: id } });
      });
    });
  }
  const grid = { ...context.grid, features: context.grid.features.map(feature => {
    const { interacted: _selection, ...properties } = feature.properties ?? {};
    return { ...feature, properties };
  }) };
  return {
    dataType: 'outputs',
    data: [
      { dataType: 'geodataframe', layerName: 'upstream', layerType: 'polygons', data: grid },
      { dataType: 'geodataframe', layerName: 'sidewalk_network', layerType: 'roads', data: { ...context.network, features } },
      { dataType: 'geodataframe', layerName: 'tile_boundaries', layerType: 'polylines', data: context.boundaries },
    ],
    metadata: { datasetId: config.overview!.datasetId, datasetIdentity: overviewIdentity(config),
      committedEdits: Object.fromEntries(edits.map(({ id, record }) => [id, { editRevision: record.revision ?? 1,
        provenance: record.provenance, envelope: record.committedEdit }])),
      ...(latestTileOutput ? { latestTileOutput } : {}) },
  };
}
