const { buildTileNeighborIndex, tileAtPoint } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/tileNeighbors');
const { cameraBoundary } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/cameraBoundary');

function cell(id: string, west: number, south: number, east: number, north: number, metadata: Record<string, unknown> = {}) {
  return { type: 'Feature' as const, id, properties: { tile_id: id, ...metadata }, geometry: {
    type: 'Polygon' as const, coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
  } };
}

test('cardinal neighbors follow geographic geometry, not tile-ID order or PCP candidates', () => {
  const grid = { type: 'FeatureCollection' as const, features: [
    cell('center', 1, 1, 2, 2, { x: 8, y: 8, zoom: 19 }),
    cell('north-99', 1, 2, 2, 3, { x: 8, y: 7, zoom: 19 }),
    cell('south-A', 1, 0, 2, 1, { x: 8, y: 9, zoom: 19 }),
    cell('east-2', 2, 1, 3, 2, { x: 9, y: 8, zoom: 19 }),
    cell('west-500', 0, 1, 1, 2, { x: 7, y: 8, zoom: 19 }),
    cell('corner-only', 2, 2, 3, 3, { x: 9, y: 7, zoom: 19 }),
  ] };
  const index = buildTileNeighborIndex(grid);
  expect(index.neighbors.get('center')).toEqual({ north: 'north-99', south: 'south-A', east: 'east-2', west: 'west-500' });
  expect(index.neighbors.get('north-99')?.east).toBe('corner-only');
});

test('holes and study-area edges disable navigation instead of jumping across a gap', () => {
  const index = buildTileNeighborIndex({ type: 'FeatureCollection', features: [
    cell('A', 0, 0, 1, 1), cell('across-gap', 2, 0, 3, 1), cell('corner', 1, 1, 2, 2),
  ] });
  expect(index.neighbors.get('A')).toEqual({});
  expect(index.neighbors.get('across-gap')?.west).toBeUndefined();
  expect(tileAtPoint(index, [2.5, 0.5])).toBe('across-gap');
  expect(tileAtPoint(index, [1.5, 0.5])).toBeNull();
});

test('outside camera uses the actual polygon boundary without changing its coordinates', () => {
  const polygon = cell('A', 0, 0, 1, 1).geometry;
  expect(cameraBoundary([0.5, 0.5], polygon)).toBeNull();
  const cue = cameraBoundary([1.001, 0.5], polygon);
  expect(cue?.nearest).toEqual([1, 0.5]);
  expect(cue?.metres).toBeGreaterThan(100);
  expect(cue?.metres).toBeLessThan(120);
});

test('geometry fallback resolves partial sides and deterministically chooses greatest overlap', () => {
  const index = buildTileNeighborIndex({ type: 'FeatureCollection', features: [
    cell('center', 0, 0, 2, 2, { x: 50, y: 50, zoom: 19 }),
    cell('short', 2, 0, 3, 0.5), cell('long', 2, 0.5, 3, 2),
  ] });
  expect(index.neighbors.get('center')?.east).toBe('long');
  expect(index.neighbors.get('long')?.west).toBe('center');
});

test('full prepared grid builds one reusable adjacency index including imagery-free cells', () => {
  // Synthetic scale fixture; no private Recife data or redistribution assumptions.
  const grid = { type: 'FeatureCollection', features: Array.from({ length: 9282 }, (_, i) =>
    cell(`cell-${i}`, i % 102, Math.floor(i / 102), i % 102 + 1, Math.floor(i / 102) + 1,
      { image_available: i !== 0 })) };
  const start = performance.now();
  const index = buildTileNeighborIndex(grid);
  const elapsedMs = performance.now() - start;
  expect(index.features.size).toBe(9282);
  expect(index.neighbors.size).toBe(9282);
  const withoutImage = grid.features.find((feature: any) => feature.properties.image_available === false);
  expect(withoutImage).toBeDefined();
  expect(index.neighbors.has(withoutImage!.properties.tile_id)).toBe(true);
  console.info(JSON.stringify({ stage: 'tile-neighbor-index', tiles: index.features.size, elapsedMs: Math.round(elapsedMs) }));
}, 30000);
