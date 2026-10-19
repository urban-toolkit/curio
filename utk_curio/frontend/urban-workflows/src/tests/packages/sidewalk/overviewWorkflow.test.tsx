import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { readAutkInput, autkSourcesFrom } from '../../../utils/autkInput';
import { tile, network, ready, canvas, draw } from '../../_support/sidewalkEditorHarness';
const { useSidewalkTileEditBehavior } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/sidewalkTileEditBehavior');
const fc = (features: any[]) => ({ type: 'FeatureCollection', features });
const grid = fc([tile('A'), tile('B', 1), tile('C', 2)]);
const base = fc([...network().features, ...network(1).features, ...network(2).features]);
const configuration = { schema: 'curio.sidewalk-tile-edit/v1', overview: { datasetId: 'test', gridUrl: 'grid.json', networkUrl: 'base.json', boundariesUrl: 'bounds.json' }, byTile: {} };
const pick = (index: number) => [{ details: { autk_selection: { type: 'POINT', data: [index], layerRef: 'upstream', selectionOrigin: { version: 1, kind: 'map-pick', activeIndex: index } } } }];
let originalFetch: typeof fetch;
beforeEach(() => {
  originalFetch = global.fetch;
  global.fetch = jest.fn(async (url: any) => ({ ok: true, json: async () => String(url).endsWith('grid.json') ? grid
    : String(url).endsWith('base.json') ? base : String(url).endsWith('bounds.json') ? fc([])
      : network(String(url).includes('B') ? 1 : String(url).includes('C') ? 2 : 0) })) as unknown as typeof fetch;
});
afterEach(() => { global.fetch = originalFetch; });
function Host({ selection = [], input = { dataType: 'geodataframe', data: grid }, initialConfig = configuration, emit, persist = jest.fn() }:
  { selection?: any[]; input?: any; initialConfig?: any; emit: jest.Mock; persist?: jest.Mock }) {
  const [code, setCode] = React.useState(JSON.stringify(initialConfig));
  return useSidewalkTileEditBehavior({ nodeId: 'overview-editor', input, interactions: selection,
    outputCallback: (_id: string, output: unknown) => emit(output), interactionsCallback: jest.fn() },
  { code, setCode: (next: string) => { persist(JSON.parse(next)); setCode(next); }, setOutput: jest.fn() }).contentComponent;
}
const bundleNetwork = (emit: jest.Mock) => emit.mock.calls.at(-1)![0].data[1].data;
const correctedTiles = (emit: jest.Mock) => [...new Set(bundleNetwork(emit).features.map((f: any) => f.properties?.tile_id).filter(Boolean))];

test('bootstraps without selection and ordinary output resolves to the existing Autark input tables', async () => {
  const emit = jest.fn(); render(<Host emit={emit} />);
  expect(screen.getByText('Loading complete overview context…')).toBeInTheDocument();
  await waitFor(() => expect(emit).toHaveBeenCalledTimes(1));
  expect(screen.getByText('Waiting for tile selection')).toBeInTheDocument();
  const read = await readAutkInput(emit.mock.calls[0][0]);
  const prepared = autkSourcesFrom(read, { map: { layerRefs: [{ dataRef: 'upstream' }, { dataRef: 'sidewalk_network' }, { dataRef: 'tile_boundaries' }] } });
  expect(prepared.tables).toEqual(['upstream', 'sidewalk_network', 'tile_boundaries']);
  expect(prepared.sources[0].geojsonObject.features.map(f => f.properties?.tile_id)).toEqual(['A', 'B', 'C']);
  expect(prepared.sources[1].layerType).toBe('roads');
});

test('selection echoes and PCP brushing do not republish; saves accumulate and resaving replaces without a loop', async () => {
  const emit = jest.fn(), persist = jest.fn();
  const view = render(<Host emit={emit} persist={persist} />);
  await waitFor(() => expect(emit).toHaveBeenCalledTimes(1));
  view.rerender(<Host emit={emit} persist={persist} selection={pick(0)} />);
  await ready('A'); await draw(canvas(view.container));
  expect(emit).toHaveBeenCalledTimes(1); // unsaved working geometry
  fireEvent.click(screen.getByRole('button', { name: 'Save network' }));
  await waitFor(() => expect(emit).toHaveBeenCalledTimes(2));
  expect(correctedTiles(emit)).toEqual(['A']);
  const savedA = bundleNetwork(emit).features.filter((f: any) => f.properties?.tile_id === 'A');
  const selectedGrid = fc(grid.features.map((f: any, i: number) => ({ ...f, properties: { ...f.properties, interacted: i === 1 ? '1' : '0' } })));
  view.rerender(<Host emit={emit} persist={persist} selection={pick(1)} input={{ dataType: 'geodataframe', data: selectedGrid }} />);
  await ready('B'); expect(emit).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByRole('button', { name: 'Save network' }));
  await waitFor(() => expect(emit).toHaveBeenCalledTimes(3));
  expect(correctedTiles(emit)).toEqual(['A', 'B']);
  expect(bundleNetwork(emit).features.filter((f: any) => f.properties?.tile_id === 'A')).toEqual(savedA);
  view.rerender(<Host emit={emit} persist={persist} selection={pick(0)} />); await ready('A');
  fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
  expect(emit).toHaveBeenCalledTimes(3);
  fireEvent.click(screen.getByRole('button', { name: 'Save network' }));
  await waitFor(() => expect(emit).toHaveBeenCalledTimes(4));
  expect(correctedTiles(emit)).toEqual(['A', 'B']);
  expect(bundleNetwork(emit).features.filter((f: any) => f.properties?.tile_id === 'A')).toHaveLength(1);
  expect(emit.mock.calls.at(-1)![0].metadata.latestTileOutput.data.metadata).toMatchObject({ sidewalkTileId: 'A', editRevision: 2 });
  view.rerender(<Host emit={emit} persist={persist} selection={pick(2)} />); await ready('C');
  view.rerender(<Host emit={emit} persist={persist} selection={[{ details: { autk_selection: { data: [0, 1], selectionOrigin: { version: 1, kind: 'plot-brush', candidateIndices: [0, 1] } } } }]} />);
  expect(screen.getByText(/Tile C/)).toBeInTheDocument();
  await act(async () => { await Promise.resolve(); });
  expect(emit).toHaveBeenCalledTimes(4);
  const restored = persist.mock.calls.at(-1)![0]; view.unmount();
  const restoreEmit = jest.fn(); render(<Host emit={restoreEmit} initialConfig={restored} />);
  await waitFor(() => expect(restoreEmit).toHaveBeenCalledTimes(1));
  expect(bundleNetwork(restoreEmit)).toEqual(bundleNetwork(emit));
});

test('overview resource failures are visible and never emit an empty placeholder', async () => {
  global.fetch = jest.fn(async () => ({ ok: false, status: 404 })) as unknown as typeof fetch;
  const emit = jest.fn(); render(<Host emit={emit} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Overview resource failed (HTTP 404)');
  expect(emit).not.toHaveBeenCalled();
});

test('an aborted old dataset cannot overwrite a new completed dataset', async () => {
  let release: (value: unknown) => void = () => {};
  const deferred = new Promise(resolve => { release = resolve; });
  global.fetch = jest.fn(async (url: any) => String(url).includes('old-grid') ? { ok: true, json: () => deferred }
    : { ok: true, json: async () => String(url).includes('grid') ? grid : String(url).includes('base') ? base : fc([]) }) as unknown as typeof fetch;
  const emit = jest.fn();
  const old = { ...configuration, overview: { ...configuration.overview, gridUrl: 'old-grid.json' } };
  function Switch({ next }: { next: boolean }) {
    return useSidewalkTileEditBehavior({ nodeId: 'switch', input: grid, interactions: [], outputCallback: (_id: string, output: unknown) => emit(output), interactionsCallback: jest.fn() },
      { code: JSON.stringify(next ? configuration : old), setCode: jest.fn(), setOutput: jest.fn() }).contentComponent;
  }
  const view = render(<Switch next={false} />); view.rerender(<Switch next />);
  await waitFor(() => expect(emit).toHaveBeenCalledTimes(1));
  await act(async () => release(grid)); expect(emit).toHaveBeenCalledTimes(1);
  expect(emit.mock.calls[0][0].metadata.datasetIdentity).not.toContain('old-grid');
});
