const {
  ACTIVE_TILE_CHANNEL, ACTIVE_TILE_SCHEMA, CAMERA_CONTEXT_CHANNEL, CAMERA_CONTEXT_SCHEMA,
  INSPECTION_REQUEST_CHANNEL, INSPECTION_REQUEST_SCHEMA, cameraMatchesTile, inspectionMatchesTile,
  latestActiveTile, latestCameraContext, latestInspectionRequest, pointFromWgs84, pointToWgs84,
  sourceFingerprint, tileGeometryWgs84,
} = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/streetViewContract');
const { distanceMeters, imagesForRequest, imagesForTile, readStreetImages, requestedHeading } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/streetViewImages');
const { clientToViewPoint, viewToPoint } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/SidewalkTileEditor');
export {};

const polygon = { type: 'Polygon' as const, coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]] };
const tile = { schema: ACTIVE_TILE_SCHEMA, editorId: 'editor', sourceFingerprint: 'dataset',
  selectionEpoch: '2026-10-15T00:00:00Z:x', selectionRevision: 3, tileId: 'A', geometry: polygon, crs: 'EPSG:4326' as const };

test('versioned events survive Curio details transport and do not contain image URLs', () => {
  const active = latestActiveTile([{ details: { [ACTIVE_TILE_CHANNEL]: tile }, priority: 1 }]);
  expect(active).toEqual(tile);
  const camera = { schema: CAMERA_CONTEXT_SCHEMA, editorId: 'editor', sourceFingerprint: 'dataset',
    selectionEpoch: tile.selectionEpoch, selectionRevision: 3, viewerId: 'viewer', tileId: 'A', imageId: 'pano-1',
    displayRevision: 2, location: [0.2, 0.3], headingDegrees: 0, headingMeaning: 'requested-static-image' };
  expect(latestCameraContext([{ details: { [CAMERA_CONTEXT_CHANNEL]: camera }, priority: 1 }])).toEqual(camera);
  expect(cameraMatchesTile(camera as any, tile)).toBe(true);
  expect(cameraMatchesTile({ ...camera, selectionRevision: 1 } as any, tile)).toBe(false);
  expect(JSON.stringify(camera)).not.toContain('key=');
  expect(sourceFingerprint(undefined, 'images', 'network', { type: 'FeatureCollection', features: [{ properties: { tile_id: 'A' }, geometry: polygon }] }))
    .not.toEqual(sourceFingerprint(undefined, 'images', 'network', { type: 'FeatureCollection', features: [{ properties: { tile_id: 'B' }, geometry: polygon }] }));
});

test('inspection requests use the same Curio interaction envelope and reject invalid or stale identities', () => {
  const request = { schema: INSPECTION_REQUEST_SCHEMA, editorId: 'editor', sourceFingerprint: 'dataset',
    selectionEpoch: tile.selectionEpoch, selectionRevision: tile.selectionRevision,
    requestRevision: 5, tileId: 'A', location: [0.3, 0.4], crs: 'EPSG:4326' };
  const envelope = [{ details: { [ACTIVE_TILE_CHANNEL]: tile, [INSPECTION_REQUEST_CHANNEL]: request }, priority: 1 }];
  expect(latestActiveTile(envelope)).toEqual(tile);
  expect(latestInspectionRequest(envelope)).toEqual(request);
  expect(inspectionMatchesTile(request, tile)).toBe(true);
  expect(inspectionMatchesTile({ ...request, selectionRevision: 2 }, tile)).toBe(false);
  expect(latestInspectionRequest([{ details: { [INSPECTION_REQUEST_CHANNEL]: { ...request, location: [181, 0] } }, priority: 1 }])).toBeNull();
  const camera = { schema: CAMERA_CONTEXT_SCHEMA, editorId: 'editor', sourceFingerprint: 'dataset',
    selectionEpoch: tile.selectionEpoch, selectionRevision: 3, requestRevision: 5,
    viewerId: 'viewer', tileId: 'A', imageId: 'pano-1', displayRevision: 8,
    location: [0.3, 0.4], headingDegrees: null, headingMeaning: null };
  expect(latestCameraContext([{ details: { [CAMERA_CONTEXT_CHANNEL]: camera }, priority: 1 }])).toEqual(camera);
  expect(JSON.stringify(request)).not.toContain('image_url');
});

test('explicit Web Mercator tile coordinates become WGS84 rather than being relabelled', () => {
  const feature: any = { type: 'Feature', properties: { tile_id: 'A' }, geometry: {
    type: 'Polygon', coordinates: [[[0, 0], [111319.49079327357, 0], [111319.49079327357, 111325.1428663851], [0, 111325.1428663851], [0, 0]]],
  } };
  const converted = tileGeometryWgs84(feature, 'EPSG:3857');
  expect(converted.coordinates[0][2][0]).toBeCloseTo(1, 6);
  expect(converted.coordinates[0][2][1]).toBeCloseTo(1, 6);
  expect(pointFromWgs84([1, 1], 'EPSG:3857')[0]).toBeCloseTo(111319.49079327357, 4);
  expect(pointToWgs84([111319.49079327357, 111325.1428663851], 'EPSG:3857')).toEqual(expect.arrayContaining([expect.closeTo(1, 6), expect.closeTo(1, 6)]));
  expect(() => tileGeometryWgs84(feature, 'EPSG:26916')).toThrow(/Unsupported tile CRS/);
});

test('editor click inversion respects translated, resized and zoomed rendered rectangles', () => {
  const bounds: [number, number, number, number] = [0, 0, 1, 1];
  for (const rect of [
    { left: 100, top: 200, width: 400, height: 200 },
    { left: 350, top: 80, width: 1200, height: 600 },
    { left: -25, top: 400, width: 180, height: 900 },
  ]) {
    const [x, y] = clientToViewPoint(rect, rect.left + rect.width * 0.35, rect.top + rect.height * 0.62);
    expect(x).toBeCloseTo(350);
    expect(y).toBeCloseTo(620);
    expect(viewToPoint(x, y, bounds)).toEqual([expect.closeTo(0.35), expect.closeTo(0.38)]);
  }
});

test('point matching chooses actual nearest imagery only within an explicit metre threshold', () => {
  const images = [
    { id: 'A', location: [0.5, 0.5], imageUrl: '/a.jpg', requestedHeading: 0, date: null },
    { id: 'B', location: [0.5002, 0.5], imageUrl: '/b.jpg', requestedHeading: null, date: null },
    { id: 'missing', location: [0.50001, 0.5], imageUrl: null, requestedHeading: null, date: null },
    { id: 'outside', location: [1.0001, 0.5], imageUrl: '/outside.jpg', requestedHeading: null, date: null },
    { id: 'far', location: [2, 2], imageUrl: '/far.jpg', requestedHeading: null, date: null },
  ];
  expect(imagesForRequest(images, polygon, [0.50015, 0.5], 30).map((image: { id: string }) => image.id)).toEqual(['B', 'A']);
  expect(imagesForRequest(images, polygon, [0.6, 0.6], 30)).toEqual([]);
  const nearby = imagesForRequest(images, polygon, [0.9999, 0.5], 60);
  expect(nearby[0]).toMatchObject({ id: 'outside', outside: true });
});

test('static input keeps actual point positions, zero heading, and bounded outside fallback', async () => {
  const input = { dataType: 'geodataframe', data: { type: 'FeatureCollection', features: [
    { type: 'Feature', geometry: { type: 'Point', coordinates: [0.2, 0.3] }, properties: {
      pano_id: 'inside', image_url: 'https://example.invalid/image?pano=inside&heading=0',
    } },
    { type: 'Feature', geometry: { type: 'Point', coordinates: [1.0001, 0.5] }, properties: {
      pano_id: 'nearby', image_url: '/street-view.jpg',
    } },
    { type: 'Feature', geometry: { type: 'Point', coordinates: [2, 2] }, properties: {
      pano_id: 'distant', image_url: '/distant.jpg',
    } },
    { type: 'Feature', geometry: null, properties: { pano_id: 'bad', image_url: '/bad.jpg' } },
  ] } };
  const { images, unavailable } = await readStreetImages(input);
  expect(unavailable).toBe(1);
  expect(images[0].location).toEqual([0.2, 0.3]);
  expect(images[0].requestedHeading).toBe(0);
  expect(requestedHeading('/image?heading=0')).toBe(0);
  expect(requestedHeading('/image')).toBeNull();
  expect(imagesForTile(images, polygon).map((image: { id: string }) => image.id)).toEqual(['inside']);
  const emptyPolygon = { type: 'Polygon' as const, coordinates: [[[1, 0], [1.1, 0], [1.1, 0.4999], [1, 0.4999], [1, 0]]] };
  expect(imagesForTile(images, emptyPolygon).map((image: { id: string }) => image.id)).toEqual(['nearby']);
  expect(distanceMeters([0, 0], [0, 0])).toBe(0);
});

test('the Data Loading dict artifact and Fetcher geodataframe use the same point contract', async () => {
  const collection = { type: 'FeatureCollection', features: [{ type: 'Feature',
    geometry: { type: 'Point', coordinates: [-34.93, -8.06] },
    properties: { pano_id: 'synthetic-a', image_url: 'docs/examples/data/sidewalk-street-view-context/fixture-a1.svg?heading=0' },
  }] };
  const previousFetch = global.fetch;
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => collection })) as unknown as typeof fetch;
  try {
    const fromLoader = await readStreetImages({ dataType: 'dict', data: 'fixture-artifact' });
    const fromFetcher = await readStreetImages({ dataType: 'geodataframe', data: collection });
    expect(fromLoader).toEqual(fromFetcher);
    expect(fromLoader.images[0]).toMatchObject({ id: 'synthetic-a', location: [-34.93, -8.06], requestedHeading: 0 });
    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('/get?fileName=fixture-artifact'), expect.any(Object));
  } finally { global.fetch = previousFetch; }
});
