import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

// Exercise the unchanged upstream adapter, stubbing only its renderer/services.
jest.mock('../../../providers/FlowProvider', () => require('../../_support/autkNodeMocks').flowProviderModule);
jest.mock('../../../providers/ToastProvider', () => require('../../_support/autkNodeMocks').toastProviderModule);
jest.mock('../../../services/api', () => require('../../_support/autkNodeMocks').apiModule);
jest.mock('../../../JavaScriptInterpreter', () => ({ JavaScriptInterpreter: class {} }));
jest.mock('@urban-toolkit/autk-grammar', () => require('../../_support/autkNodeMocks').autkGrammarModule, { virtual: true });
jest.mock('@urban-toolkit/autk-compute', () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });
import { NodeType, VisInteractionType } from '../../../constants';
import { grammarRuns, resetAutkNodeMocks } from '../../_support/autkNodeMocks';
import { lastSelection, mountAutkNode, stubWebGpu, unstubWebGpu } from '../../_support/autkNode';

beforeEach(() => { resetAutkNodeMocks(); stubWebGpu(); });
afterEach(unstubWebGpu);

const { useSidewalkTileEditBehavior } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/sidewalkTileEditBehavior');

const tile = (id: string, west: number) => ({
  type: 'Feature',
  properties: { tile_id: id, west, south: 0, image_url: 'data:image/jpeg;base64,AA==', network_url: `tile-network/${id}.geojson` },
  geometry: { type: 'Polygon', coordinates: [[[west, 0], [west + 1, 0], [west + 1, 1], [west, 1], [west, 0]]] },
});

const tiles = { type: 'FeatureCollection', features: [tile('first', 0), tile('second', 1)] };

test('resolves an Autark picked row against the separate tile data input and replaces the active tile', async () => {
  const previousFetch = global.fetch;
  const fetchMock = jest.fn(async (url: string) => ({
    ok: true,
    json: async () => ({
      type: 'FeatureCollection',
      features: [{ type: 'Feature', id: 'second-edge', properties: {},
        geometry: { type: 'LineString', coordinates: url.includes('/first.geojson')
          ? [[0.1, 0.1], [0.9, 0.9]] : [[1.1, 0.1], [1.9, 0.9]] } }],
    }),
  }));
  global.fetch = fetchMock as unknown as typeof fetch;
  const emit = jest.fn();
  const persist = jest.fn();
  const nodeState = { code: '', setCode: persist, setOutput: jest.fn() };
  const event = (indices: number[], kind: 'map-pick' | 'plot-brush', activeIndex: number | null = null) => [{
    details: { autk_selection: {
      data: indices, priority: 1,
      selectionOrigin: kind === 'map-pick'
        ? { version: 1, kind, activeIndex }
        : { version: 1, kind, candidateIndices: indices },
    } },
  }];

  function Host({ selection }: { selection: ReturnType<typeof event> | null }) {
    const data = {
      nodeId: 'sidewalk-editor', input: tiles,
      interactions: selection ?? [],
      outputCallback: (_nodeId: string, value: unknown) => emit(value),
      interactionsCallback: jest.fn(),
    };
    return useSidewalkTileEditBehavior(data, nodeState).contentComponent;
  }

  try {
    const view = render(<Host selection={null} />);
    expect(screen.getByText(/Waiting for tile selection/)).toBeInTheDocument();

    view.rerender(<Host selection={event([0], 'map-pick', 0)} />);
    await waitFor(() => expect(screen.getByText("Tile first")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('tile-network/first.geojson'), expect.objectContaining({ signal: expect.any(AbortSignal) }));

    // Autark retains A in its legacy set; the versioned active index identifies B.
    view.rerender(<Host selection={event([0, 1], 'map-pick', 1)} />);
    await waitFor(() => expect(screen.getByText("Tile second")).toBeInTheDocument());
    expect(screen.queryByText("Tile first")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('tile-network/second.geojson'), expect.objectContaining({ signal: expect.any(AbortSignal) }));

    view.rerender(<Host selection={event([0, 1], 'plot-brush')} />);
    await waitFor(() => expect(screen.getByText("Tile second")).toBeInTheDocument());

    fireEvent.load(screen.getByRole('img'));
    fireEvent.click(screen.getByRole('button', { name: 'Save network' }));
    await waitFor(() => expect(emit).toHaveBeenCalledWith(expect.objectContaining({
      data: expect.objectContaining({ metadata: expect.objectContaining({ sidewalkTileId: 'second' }) }),
    })));
    expect(persist).toHaveBeenCalled();

    view.rerender(<Host selection={event([], 'map-pick')} />);
    await waitFor(() => expect(screen.getByText(/Waiting for tile selection/)).toBeInTheDocument());
  } finally {
    global.fetch = previousFetch;
  }
});


test('legacy host selections require an explicit active-tile choice, including single-row brushes and clear', async () => {
  const previousFetch = global.fetch;
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ type: 'FeatureCollection', features: [] }) })) as unknown as typeof fetch;
  const legacy = (data: number[]) => [{ details: { autk_selection: { data, priority: 1 } } }];
  function Host({ indices }: { indices: number[] }) {
    return useSidewalkTileEditBehavior({ nodeId: 'legacy', input: tiles, interactions: legacy(indices), outputCallback: jest.fn(), interactionsCallback: jest.fn() }, { code: '', setCode: jest.fn(), setOutput: jest.fn() }).contentComponent;
  }
  try {
    const view = render(<Host indices={[0]} />);
    expect(screen.getByText(/Waiting for tile selection/)).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Active tile from legacy selection'), { target: { value: '0' } });
    await screen.findByAltText('Satellite image for tile first'); fireEvent.load(screen.getByRole('img'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save network' })).toBeEnabled());
    view.rerender(<Host indices={[]} />);
    await waitFor(() => expect(screen.getByText(/Waiting for tile selection/)).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Save network' })).toBeDisabled();
    view.rerender(<Host indices={[0]} />);
    expect(screen.getByText(/Waiting for tile selection/)).toBeInTheDocument();
    expect(screen.getByLabelText('Active tile from legacy selection')).toHaveValue('');
  } finally { global.fetch = previousFetch; }
});

// Required acceptance gate. Fresh main emits keyed selection sets without selectionOrigin.
// Kept failing while the prerequisite is unresolved; do not publish this branch.
test.each([true, false])('upstream map selection automatically opens the selected editor tile (keyed=%s)', async keyed => {
  const before = mountAutkNode('before', tiles);
  await before.run({ map: { layerRefs: [{ dataRef: 'input_0', isPick: true, ...(keyed ? { selectFields: ['tile_id'] } : {}) }] } });
  expect(before.lastOutput()).toMatchObject({ code: 'success' });
  act(() => grammarRuns[0].pick([1]));
  const detail = lastSelection(before);
  expect(detail).toEqual({ type: VisInteractionType.POINT, data: keyed ? [{ tile_id: 'second' }] : [1],
    priority: 1, source: NodeType.AUTK_GRAMMAR, layerRef: 'input_0' });
  const previousFetch = global.fetch;
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ type: 'FeatureCollection', features: [] }) })) as any;
  function Host() {
    return useSidewalkTileEditBehavior({ nodeId: 'upstream-compat', input: tiles,
      interactions: [{ nodeId: 'before', priority: 1, details: { autk_selection: detail } }], outputCallback: jest.fn(), interactionsCallback: jest.fn(),
    }, { code: '', setCode: jest.fn(), setOutput: jest.fn() }).contentComponent;
  }
  try {
    render(<Host />);
    await screen.findByAltText('Satellite image for tile second');
  } finally { global.fetch = previousFetch; }
});

// Characterization checks: these confirm the payloads above are real upstream output,
// not invented acceptance data. They intentionally do not repair ambiguous events.
describe.each([true, false])('unchanged upstream selection payloads (keyed=%s)', keyed => {
  const mapSpec = () => ({ map: { layerRefs: [{ dataRef: 'input_0', isPick: true,
    ...(keyed ? { selectFields: ['tile_id'] } : {}) }] } });
  const plotSpec = () => ({ plot: { dataRef: 'input_0', mark: 'parallel-coordinates',
    axis: ['west', 'south'], events: ['brushY'], ...(keyed ? { selectFields: ['tile_id'] } : {}) } });
  const expected = (rows: number[]) => ({ type: rows.length ? VisInteractionType.POINT : VisInteractionType.UNDETERMINED,
    data: keyed ? rows.map(i => ({ tile_id: tiles.features[i].properties.tile_id })) : rows,
    priority: 1, source: NodeType.AUTK_GRAMMAR, layerRef: 'input_0' });
  test('map picks and PCP brushes of the same rows have identical details', async () => {
    const before = mountAutkNode('before', tiles);
    await before.run(mapSpec());
    const pcp = mountAutkNode('pcp', tiles);
    await pcp.run(plotSpec());
    expect(before.lastOutput()).toMatchObject({ code: 'success' });
    expect(pcp.lastOutput()).toMatchObject({ code: 'success' });
    for (const rows of [[1], [0, 1], []]) {
      act(() => grammarRuns[0].pick(rows));
      act(() => grammarRuns[1].brush(rows));
      expect(lastSelection(before)).toEqual(expected(rows));
      expect(lastSelection(pcp)).toEqual(lastSelection(before));
      // Sender IDs survive the callback; event kind and hit identity do not.
      expect(before.interactions.mock.calls.at(-1)?.[1]).toBe('before');
      expect(pcp.interactions.mock.calls.at(-1)?.[1]).toBe('pcp');
    }
  });
  test('forwards a repeated-click post-toggle sequence; equal sets have no sequence ID', async () => {
    const before = mountAutkNode('before', tiles);
    await before.run(mapSpec());
    for (const rows of [[1], [], [1], [0, 1], [1]]) {
      act(() => grammarRuns[0].pick(rows));
      expect(lastSelection(before)).toEqual(expected(rows));
    }
    const prior = lastSelection(before);
    act(() => grammarRuns[0].pick([1]));
    expect(lastSelection(before)).toEqual(prior);
    expect(lastSelection(before)).not.toBe(prior);
  });
});
