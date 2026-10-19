import fs from 'fs';
import path from 'path';
import { createHash } from 'crypto';
const { prepareContext, contextOutput, readPreparedContext } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/beforeAfterContext');
const { parseSidewalkEditConfig } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/SidewalkTileEditor');
const root = path.resolve(__dirname, '../../../../../../../');
const folder = 'docs/examples/data/sidewalk-synthetic';
const read = (name: string) => JSON.parse(fs.readFileSync(path.join(root, name), 'utf8'));
const sha = (name: string) => createHash('sha256').update(fs.readFileSync(path.join(root, name))).digest('hex');

test('review export preserves eight connected nodes, selectable Before and sparse PCP tables', () => {
  const { dataflow: flow } = read('docs/examples/28-sidewalk-review-workflow.json');
  expect(flow.nodes).toHaveLength(8);
  expect(flow.edges).toHaveLength(12);
  expect(flow.packages).toEqual(['curio.builtin@1', 'curio.sidewalk-stewards@1', 'curio.streetvision@1']);
  const node = (id: string) => flow.nodes.find((entry: any) => entry.id === `sidewalk24-${id}`);
  expect(node('prepare').type).toBe('curio.sidewalk-stewards/sidewalk-prepare');
  expect(node('editor').type).toBe('curio.sidewalk-stewards/sidewalk-tile-edit');
  expect(node('street-context').type).toBe('curio.streetvision/street-view-panorama');
  const before = JSON.parse(node('before').content);
  expect(before.map.layerRefs).toEqual([
    { dataRef: 'sidewalk_network', opacity: 0.9 },
    { dataRef: 'upstream', opacity: 0.14, isPick: true, getFnv: 'Segments', getFnvType: 'quantitative', selectFields: ['tile_id'] },
  ]);
  const pcp = JSON.parse(node('pcp').content);
  expect(pcp.plot).toMatchObject({ dataRef: 'sidewalk_typology', mapRef: 'upstream' });
  expect(read(`${folder}/tile-measurements.geojson`).features).toHaveLength(3);
  expect(read(`${folder}/tile-grid.geojson`).features).toHaveLength(6);
  expect(JSON.stringify(flow)).not.toMatch(/io\.github\.lzml0\.sidewalk-stewards\/sidewalk-|\/Users\/|\/private\/|AIza/);
});

test('portable six-tile resources validate and restore through the actual Prepare contract', async () => {
  const provenance = read(`${folder}/mosaic-provenance.json`);
  expect(sha(`${folder}/synthetic.tif`)).toBe(provenance.mosaic.sha256);
  expect(sha(`${folder}/tile-grid.geojson`)).toBe(provenance.gridSha256);
  const grid = read(`${folder}/tile-grid.geojson`);
  for (const feature of grid.features) {
    const image = fs.readFileSync(path.join(root, folder, 'tiles', feature.properties.tile_id + '.png'));
    expect(image.subarray(1, 4).toString()).toBe('PNG');
  }
  const original = read(`${folder}/overview-network.geojson`);
  const image = { kind: 'sidewalk-image', datasetId: 'synthetic-six-tiles', sha256: provenance.mosaic.sha256,
    source: { type: 'geotiff', geotiffFileUrl: `${folder}/synthetic.tif`, outputTableName: 'synthetic_rgb', coordinateFormat: 'EPSG:4326' },
    gridUrl: `${folder}/tile-grid.geojson`, boundariesUrl: `${folder}/tile-boundaries.geojson`, imageUrlTemplate: `${folder}/tiles/{tile_id}.png`,
    georeferencing: { crs: 'EPSG:4326', bounds: provenance.mosaic.bounds, gridSha256: provenance.gridSha256, mapping: provenance.mosaic.mapping } };
  const network = { kind: 'sidewalk-network', datasetId: image.datasetId, url: `${folder}/overview-network.geojson`,
    sha256: sha(`${folder}/overview-network.geojson`), crs: 'EPSG:4326', data: original };
  const context = await prepareContext({ dataType: 'outputs', data: [image, network].map(data => ({ dataType: 'dict', data })) },
    async (name: string) => read(name), async (text: string) => createHash('sha256').update(text).digest('hex'));
  const output = contextOutput(context, parseSidewalkEditConfig({ schema: 'curio.sidewalk-tile-edit/v1', mode: 'input-overview' }));
  expect(output.data[0].data.features).toHaveLength(6);
  expect(output.data[1].data).toEqual(original);
  expect(await readPreparedContext(output)).toEqual(context);
});
