import React from 'react';
import { render, waitFor, screen, fireEvent } from '@testing-library/react';
import { tile, network, ready, canvas, draw } from '../../_support/sidewalkEditorHarness';
const packageRoot = '../../../../../../../packages/curio.sidewalk-stewards@1/sources/';
const { prepareContext, contextOutput, contextConfig, readPreparedContext, withTileMeasurements } = require(packageRoot + 'beforeAfterContext');
const { parseSidewalkEditConfig } = require(packageRoot + 'SidewalkTileEditor');
const { useSidewalkTileEditBehavior } = require(packageRoot + 'sidewalkTileEditBehavior');
const { useSidewalkPreparation } = require(packageRoot + 'sidewalkPreparation');
const { savedTile } = require(packageRoot + 'overviewData');
const { readAutkInput } = require('../../../utils/autkInput');
const { nodeInputFromSlots } = require('../../../utils/inputSlots');
const fc = (features: any[]) => ({ type: 'FeatureCollection', features });
const grid = fc([tile('A'), tile('B', 1), tile('C', 2)]), base = fc([...network().features, ...network(1).features, ...network(2).features]);
const image = { kind: 'sidewalk-image', datasetId: 'test', sha256: 'a'.repeat(64), source: { type: 'geotiff', geotiffFileUrl: 'image.tif', outputTableName: 'satellite', coordinateFormat: 'EPSG:3857' }, gridUrl: 'grid.json', boundariesUrl: 'bounds.json', imageUrlTemplate: 'tiles/{tile_id}.png', georeferencing: { crs: 'EPSG:3857', bounds: [0, 0, 1, 1], gridSha256: 'b'.repeat(64), mapping: 'declared grid' } };
const original = { kind: 'sidewalk-network', datasetId: 'test', sha256: 'c'.repeat(64), url: 'base.json', crs: 'EPSG:4326', data: base };
const bundle = (i: any = image, n: any = original) => ({ dataType: 'outputs', data: [{ dataType: 'dict', data: i }, { dataType: 'dict', data: n }] });
const digest = async (s: string) => require('crypto').createHash('sha256').update(s).digest('hex');
const load = async (url: string) => url === 'grid.json' ? grid : fc([]);
const configured = () => ({ ...parseSidewalkEditConfig(''), mode: 'input-overview' });
let oldFetch: typeof fetch;
beforeEach(() => { oldFetch = global.fetch; global.fetch = jest.fn(async (url: any) => ({ ok: true, json: async () => String(url).endsWith('grid.json') ? grid : fc([]) })) as any; });
afterEach(() => { global.fetch = oldFetch; });
test('two real source dicts produce complete independent Before with immutable original and stable grid/metrics', async () => {
  const input = bundle(), before = JSON.stringify(input), loader = jest.fn(load);
  const context = await prepareContext(input, loader, digest);
  expect(loader.mock.calls.map(c => c[0])).toEqual(['grid.json', 'bounds.json']);
  const output = contextOutput(context, configured());
  expect(output.data[0].layerName).toBe('upstream');
  expect(output.data[0].data.features.map((f: any) => f.properties.tile_id)).toEqual(['A','B','C']);
  expect(output.data[1].data).toEqual(base); expect(output.data[3].data).toEqual(image.source);
  expect(output.metadata.committedEdits).toEqual({}); expect(JSON.stringify(input)).toBe(before);
  expect(await readPreparedContext(output)).toEqual(context);
});
test('Prepare exposes only measured PCP rows alongside its unchanged full grid and edit identity', async () => {
  const originalContext = await prepareContext(bundle(), load, digest);
  const measured = fc([{ ...tile('B', 1), properties: { tile_id: 'B', Plaza: 42, Walkway: 7 } }]);
  const enriched = withTileMeasurements(originalContext, measured, ['Plaza', 'Walkway']);
  const output = contextOutput(enriched, configured());
  expect(output.data[0].data.features).toHaveLength(3);
  expect(output.data[0].data.features[1].properties).not.toHaveProperty('Plaza');
  expect(output.data[0].data.features[0].properties).not.toHaveProperty('Plaza');
  expect(output.data[4].layerName).toBe('sidewalk_typology');
  expect(output.data[4].data.features).toHaveLength(1);
  expect(output.data[4].data.features[0].properties).toEqual({ tile_id: 'B', Plaza: 42, Walkway: 7 });
  expect(enriched.sourceIdentity).toBe(originalContext.sourceIdentity);
  expect(originalContext.grid.features[1].properties).not.toHaveProperty('Plaza');
  expect((await readPreparedContext(output)).measurements.features[0].properties.Plaza).toBe(42);
  expect(() => withTileMeasurements(originalContext, fc([measured.features[0], measured.features[0]]), ['Plaza'])).toThrow(/duplicate/);
});
test('current Curio preserves source provenance but does not mistake the typed RGB reference for a supported raster', async () => {
  const context = await prepareContext(bundle(), load, digest);
  const output = contextOutput(context, configured());
  const read = await readAutkInput(output);
  expect(output.metadata.sidewalkContext.image.source).toEqual(image.source);
  expect(output.data[3].data).toEqual(image.source);
  expect(read).not.toHaveProperty('geoTiffSources');
  expect(read.frames.map((frame: any) => frame.layerName ?? frame.name)).toEqual(expect.arrayContaining(['upstream', 'sidewalk_network']));
});
test('current Curio bundles two direct Sidewalk Prepare input circles in source order', async () => {
  const input = nodeInputFromSlots([{ dataType: 'dict', data: image }, { dataType: 'dict', data: original }], [0, 1]);
  expect(input).toMatchObject({ dataType: 'outputs' });
  expect((await prepareContext(input, load, digest)).sourceIdentity).toBe((await prepareContext(bundle(), load, digest)).sourceIdentity);
});
test('image URL and original geometry changes change identities; prior records never apply to another input', async () => {
  const a = await prepareContext(bundle(), load, digest);
  const b = await prepareContext(bundle({ ...image, source: { ...image.source, geotiffFileUrl: 'other.tif' } }), load, digest);
  const c = await prepareContext(bundle(image, { ...original, data: fc([]) }), load, digest);
  expect(new Set([a.sourceIdentity,b.sourceIdentity,c.sourceIdentity]).size).toBe(3);
  const config = contextConfig(a, configured());
  const { tileStorageKey } = require(packageRoot + 'overviewData');
  config.byTile[tileStorageKey(config,'A')] = { network: fc([]), committedNetwork: fc([]), past:[],future:[],operations:[],revision:1 };
  expect(savedTile(contextConfig(b,config),'A')).toBeUndefined();
  expect(contextOutput(c,config).data[1].data.features).toHaveLength(0);
});
test.each([null,{ dataType:'outputs',data:[{ dataType:'dict',data:image }] },bundle(image,{ ...original,datasetId:'other' }),bundle({ ...image,source:{ ...image.source,geotiffFileUrl:'javascript:bad' } }),bundle({ ...image,sha256:'missing' })])('fresh missing/invalid inputs fail with no fixed fixture fallback: %p', async input => {
  const loader=jest.fn(load); await expect(prepareContext(input,loader,digest)).rejects.toThrow(/Required inputs|Invalid or mismatched/); expect(loader).not.toHaveBeenCalled();
});
function Host({ input, selection=[], initial=configured(), emit, persist=jest.fn() }: any) {
  const [code,setCode]=React.useState(JSON.stringify(initial));
  return useSidewalkTileEditBehavior({ nodeId:'input-editor',input,interactions:selection,outputCallback:(_id:string,value:any)=>emit(value),interactionsCallback:jest.fn() },{ code,setCode:(next:string)=>{persist(JSON.parse(next));setCode(next);},setOutput:jest.fn() }).contentComponent;
}
const pick=(i:number)=>[{ details:{ autk_selection:{ type:'POINT',data:[i],layerRef:'upstream',selectionOrigin:{version:1,kind:'map-pick',activeIndex:i} } } }];
test('input editor uses original network without fetching legacy network and publishes cumulative saves, not drafts or selection',async()=>{
  const context=await prepareContext(bundle(),load,digest), input=contextOutput(context,configured()),emit=jest.fn(),persist=jest.fn();
  const view=render(<Host input={input} emit={emit} persist={persist}/>);
  await waitFor(()=>expect(emit).toHaveBeenCalledTimes(1));
  expect(screen.getByText('Waiting for tile selection')).toBeInTheDocument();
  expect(global.fetch).not.toHaveBeenCalled();
  view.rerender(<Host input={input} emit={emit} persist={persist} selection={pick(0)}/>); await ready('A');await draw(canvas(view.container));
  expect(emit).toHaveBeenCalledTimes(1);fireEvent.click(screen.getByRole('button',{name:'Save network'}));
  await waitFor(()=>expect(emit).toHaveBeenCalledTimes(2));
  view.rerender(<Host input={input} emit={emit} persist={persist} selection={pick(1)}/>);await ready('B');
  expect(emit).toHaveBeenCalledTimes(2);fireEvent.click(screen.getByRole('button',{name:'Save network'}));await waitFor(()=>expect(emit).toHaveBeenCalledTimes(3));
  expect(Object.keys(emit.mock.calls[2][0].metadata.committedEdits)).toEqual(['A','B']);
  view.rerender(<Host input={input} emit={emit} persist={persist} selection={pick(0)}/>);await ready('A');fireEvent.click(screen.getByRole('button',{name:'Undo'}));fireEvent.click(screen.getByRole('button',{name:'Save network'}));await waitFor(()=>expect(emit).toHaveBeenCalledTimes(4));
  const expected=emit.mock.calls[3][0], saved=persist.mock.calls.at(-1)[0];view.unmount();
  const restored=jest.fn();render(<Host input={input} emit={restored} initial={saved}/>);await waitFor(()=>expect(restored).toHaveBeenCalledTimes(1));
  expect(restored.mock.calls[0][0].data).toEqual(expected.data);expect(global.fetch).not.toHaveBeenCalled();
});
test('fresh input editor missing preparation reports required inputs and never fetches hidden resources',async()=>{
  const emit=jest.fn();render(<Host input={null} emit={emit} selection={pick(0)}/>);
  expect(await screen.findByRole('alert')).toHaveTextContent('Prepared satellite and original-network inputs are required');expect(global.fetch).not.toHaveBeenCalled();expect(emit).not.toHaveBeenCalled();
});
