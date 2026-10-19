const { buildOverview, committedSignature, tileStorageKey, savedTile, scopeLegacyTiles } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/overviewData');
const { parseSidewalkEditConfig } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/SidewalkTileEditor');
const { tile, network } = require('../../_support/sidewalkEditorHarness');

const fc = (features: any[]) => ({ type: 'FeatureCollection', features });
const crossing = { type: 'Feature', id: 'crossing', properties: { highway: 'path', original: true }, geometry: { type: 'LineString', coordinates: [[-1, 0.5], [4, 0.5]] } };
const unaffected = { type: 'Feature', id: 'outside', properties: { keep: true }, geometry: { type: 'MultiLineString', coordinates: [[[-1, 2], [4, 2]]] } };
const context = { grid: fc([tile('A'), tile('B', 1), tile('C', 2)]), network: fc([crossing, unaffected]), boundaries: fc([]) };
function config() { return parseSidewalkEditConfig({ schema: 'curio.sidewalk-tile-edit/v1', overview: { datasetId: 'test', gridUrl: 'grid.json', networkUrl: 'base.json', boundariesUrl: 'bounds.json' }, byTile: {} }); }
function commit(c: any, id: string, corrected = network(id === 'A' ? 0 : 1), revision = 1) {
  return { ...c, byTile: { ...c.byTile, [tileStorageKey(c, id)]: { network: corrected, past: [], future: [], operations: [], revision, committedNetwork: corrected,
    provenance: { editRevision: revision, tileId: id }, committedEdit: { tileId: id, editRevision: revision, after: corrected } } } };
}
const renderedNetwork = (c: any) => buildOverview(context, c).data[1].data;
const saved = (c: any, id: string) => renderedNetwork(c).features.filter((f: any) => f.properties?.tile_id === id);

test('initial complete context retains grid IDs, metrics, original network, boundaries and ordering', () => {
  const result = buildOverview(context, config());
  expect(result.data.map((d: any) => d.layerName)).toEqual(['upstream', 'sidewalk_network', 'tile_boundaries']);
  expect(result.data[0].data).toEqual(context.grid);
  expect(result.data[1].data).toEqual(context.network);
  expect(result.data[1].layerType).toBe('roads');
});

test('A then B, resaving A, and saving empty A replace geometry while retaining other committed tiles', () => {
  const a = commit(config(), 'A');
  expect(saved(a, 'A')).toHaveLength(1);
  const ab = commit(a, 'B');
  expect(saved(ab, 'A')).toHaveLength(1); expect(saved(ab, 'B')).toHaveLength(1);
  const changed = network(); changed.features[0].geometry.coordinates[1] = [0.8, 0.6];
  const again = commit(ab, 'A', changed, 2);
  expect(saved(again, 'A')).toHaveLength(1); expect(saved(again, 'B')).toEqual(saved(ab, 'B'));
  expect(saved(again, 'A')[0].geometry.coordinates.at(-1)).toEqual([0.8, 0.6]);
  const empty = commit(again, 'A', fc([]), 3);
  expect(saved(empty, 'A')).toEqual([]); expect(saved(empty, 'B')).toHaveLength(1);
  expect(renderedNetwork(empty).features.filter((f: any) => f.properties?.original).flatMap((f: any) => f.geometry.coordinates)
    .some((p: number[]) => p[0] > 0 && p[0] < 1)).toBe(false);
});

test('crossing source lines keep outside segments and untouched multiline features remain byte-equivalent', () => {
  const result = renderedNetwork(commit(config(), 'A'));
  expect(result.features).toContainEqual(unaffected);
  const outside = result.features.filter((f: any) => f.properties?.original);
  expect(outside.map((f: any) => f.geometry.coordinates)).toEqual([
    [[-1, 0.5], [0, 0.5]], [[1, 0.5], [2, 0.5], [3, 0.5], [4, 0.5]],
  ]);
  expect(outside.every((f: any) => f.geometry.type === 'LineString' && f.properties.highway === 'path')).toBe(true);
  expect(context.network.features[0]).toEqual(crossing);
});

test('overview omits sub-centimetre clipping fragments while retaining the committed edit', () => {
  const tiny = { type: 'Feature', id: 'tiny', properties: { highway: 'path' }, geometry: {
    type: 'LineString', coordinates: [[0.5, 0.5], [0.50000005, 0.5]],
  } };
  const committed = fc([tiny]);
  const c = commit(config(), 'A', committed);
  const result = buildOverview(context, c);
  expect(result.data[1].data.features.some((f: any) => f.properties?.tile_id === 'A' && f.properties?.highway === 'path' && f.properties?.sidewalk_source_feature_id === 'tiny')).toBe(false);
  expect(result.metadata.committedEdits.A.editRevision).toBe(1);
  expect(savedTile(c, 'A').committedNetwork).toBe(committed);
});

test('a shared-border segment has one deterministic owner, including an empty committed tile', () => {
  const border = { ...crossing, geometry: { type: 'LineString', coordinates: [[1, 0.1], [1, 0.9]] } };
  const shared = { ...context, network: fc([border]) };
  expect(buildOverview(shared, commit(config(), 'B', fc([]))).data[1].data.features).toEqual([border]);
  expect(buildOverview(shared, commit(config(), 'A', fc([]))).data[1].data.features).toEqual([]);
  const both = commit(commit(config(), 'B', fc([border])), 'A', fc([border]));
  expect(buildOverview(shared, both).data[1].data.features).toHaveLength(1);
  expect(buildOverview(shared, both).data[1].data.features[0].properties.tile_id).toBe('A');
});

test('restoration and record insertion order produce deterministic output, unique IDs and intact provenance', () => {
  const ab = commit(commit(config(), 'A'), 'B');
  const ba = { ...ab, byTile: Object.fromEntries(Object.entries(ab.byTile).reverse()) };
  expect(buildOverview(context, ba)).toEqual(buildOverview(context, ab));
  expect(buildOverview(context, JSON.parse(JSON.stringify(ab)))).toEqual(buildOverview(context, ab));
  const result = buildOverview(context, ab);
  const ids = result.data[1].data.features.map((f: any) => f.id);
  expect(new Set(ids).size).toBe(ids.length);
  expect(saved(ab, 'A')[0].properties).toMatchObject({ highway: 'path', tile_id: 'A', sidewalk_dataset_id: 'test', sidewalk_edit_revision: 1, sidewalk_provenance_ref: 'A' });
  expect(result.metadata.committedEdits.A.provenance).toEqual({ tileId: 'A', editRevision: 1 });
});

test('working edits and pool selection flags leave committed signature and geometry unchanged', () => {
  const c = commit(config(), 'A');
  const draft = { ...c, byTile: { ...c.byTile, [tileStorageKey(c, 'A')]: { ...c.byTile[tileStorageKey(c, 'A')], network: fc([]), operations: ['delete_node'] } } };
  expect(committedSignature(draft, context.grid)).toBe(committedSignature(c, context.grid));
  const selected = { ...context, grid: fc(context.grid.features.map((f: any, i: number) => ({ ...f, properties: { ...f.properties, interacted: i ? '0' : '1' } }))) };
  expect(buildOverview(selected, draft)).toEqual(buildOverview(context, c));
});

test('dataset and resource identity isolate saved corrections, and latest-tile output is preserved explicitly', () => {
  const c = commit(config(), 'A');
  const different = { ...c, overview: { ...c.overview, datasetId: 'other' } };
  expect(renderedNetwork(different)).toEqual(context.network);
  const changedAsset = { ...c, overview: { ...c.overview, networkUrl: 'other.geojson' } };
  expect(renderedNetwork(changedAsset)).toEqual(context.network);
  const latest = { dataType: 'geodataframe', data: network() };
  expect(buildOverview(context, c, latest).metadata.latestTileOutput).toBe(latest);
});

test('invalid or duplicate grids fail explicitly instead of publishing partial context', () => {
  expect(() => buildOverview({ ...context, grid: fc([]) }, config())).toThrow('no tiles');
  expect(() => buildOverview({ ...context, grid: fc([tile('A'), tile('A', 1)]) }, config())).toThrow('unique');
});


test('legacy Recife commits migrate losslessly within byTile and never leak into another dataset', () => {
  const root = 'docs/examples/data/sidewalk-stewards-regions';
  const legacy = parseSidewalkEditConfig({ schema: 'curio.sidewalk-tile-edit/v1',
    imageUrlTemplate: `${root}/tiles/{tile_id}.png`, networkUrlTemplate: `${root}/tile-network/{tile_id}.geojson`, overview: {
    datasetId: 'recife-z19', gridUrl: `${root}/tile-grid.geojson`, networkUrl: `${root}/overview-network.geojson`, boundariesUrl: `${root}/tile-boundaries.geojson`,
  }, byTile: { A: { network: network(), committedNetwork: network(), revision: 5, past: [], future: [], operations: [] } } });
  expect(savedTile(legacy, 'A').revision).toBe(5);
  const migrated = scopeLegacyTiles(legacy);
  expect(Object.keys(migrated.byTile)).toEqual([tileStorageKey(legacy, 'A')]);
  expect(savedTile(migrated, 'A')).toEqual(legacy.byTile.A);
  expect(savedTile({ ...legacy, overview: { ...legacy.overview, datasetId: 'other' } }, 'A')).toBeUndefined();
});
