/**
 * The Spatial Join pairs its two inputs by an operation (#576).
 *
 * Input 0 arrives on the `in` circle and input 1 on `in_1`, and that is the
 * order they are joined in, whatever their geometry: the node used to sort
 * them into points and polygons by geometry type, so two polygon inputs never
 * joined. The body picks the operation and the output, both persisted on the
 * node, and the backend's counts reach the status line.
 */
import React from 'react';
import { renderHook, render, act, fireEvent, waitFor } from '@testing-library/react';
import type { NodeBehaviorData, UseNodeStateReturn } from '../../../registry/types';

jest.mock('reactflow', () => ({
  useEdges: () => [],
  Position: { Left: 'left', Right: 'right', Top: 'top', Bottom: 'bottom' },
}));

const mockUpdateDataNode = jest.fn();
const mockFlow = { dashboardOn: false };
jest.mock('../../../providers/FlowProvider', () => ({
  useFlowContext: () => ({ updateDataNode: mockUpdateDataNode, dashboardOn: mockFlow.dashboardOn }),
}));

const mockShowToast = jest.fn();
jest.mock('../../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));

// The artifact fetch the node uses to resolve `{ path, dataType }` inputs. Kept
// separate from the `global.fetch` mock, which stands in for the join route.
jest.mock('../../../services/api', () => ({
  fetchData: jest.fn(),
}));

import { useSpatialJoinBehavior } from '../../../adapters/node/spatialJoinBehavior';

const POINTS = {
  type: 'FeatureCollection',
  features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [-87.6, 41.8] }, properties: { name: 'photo-1.jpg' } }],
};
const POLYGONS = {
  type: 'FeatureCollection',
  features: [{
    type: 'Feature',
    geometry: { type: 'Polygon', coordinates: [[[-88, 41], [-87, 41], [-87, 42], [-88, 42], [-88, 41]]] },
    properties: { pri_neigh: 'Loop' },
  }],
};
const ZIPS = {
  type: 'FeatureCollection',
  features: [{
    type: 'Feature',
    geometry: { type: 'Polygon', coordinates: [[[-87.7, 41.7], [-87.5, 41.7], [-87.5, 41.9], [-87.7, 41.9], [-87.7, 41.7]]] },
    properties: { zip: '60614' },
  }],
};

const OPERATIONS = ['intersects', 'within', 'contains', 'touches', 'overlaps', 'crosses', 'nearest'];

function mockFetch(response: unknown) {
  const fetchMock = jest.fn().mockResolvedValue({ ok: true, json: async () => response });
  (global as any).fetch = fetchMock;
  return fetchMock;
}

/** A join answer: the features and the counts the backend reports. */
function joined(features: any[], metadata: Record<string, unknown> = {}) {
  return {
    type: 'FeatureCollection',
    features,
    metadata: {
      name: 'spatial_join_result', output: 'pairs', predicate: 'intersects',
      pairs: features.length, matched_left: features.length, left_rows: features.length,
      matched_right: features.length ? 1 : 0, right_rows: 1,
      ...metadata,
    },
  };
}

function makeData(overrides: Record<string, unknown> = {}): NodeBehaviorData {
  return {
    nodeId: 'sj-1',
    nodeType: 'curio.builtin/spatial-join@1',
    outputCallback: jest.fn(),
    propagationCallback: jest.fn(),
    interactionsCallback: jest.fn(),
    input: '',
    ...overrides,
  } as unknown as NodeBehaviorData;
}

function makeNodeState(): UseNodeStateReturn {
  return {
    output: { code: '', content: '' },
    setOutput: jest.fn(),
    code: '',
    setCode: jest.fn(),
    templateData: {},
  } as unknown as UseNodeStateReturn;
}

type Ports = Record<string, unknown>;

/** The node as the canvas holds it: the same data, with what each circle holds (`data.portInputs`) set by a prop. */
function renderJoin(overrides: Record<string, unknown> = {}, nodeState: UseNodeStateReturn = makeNodeState()) {
  const data = makeData(overrides);
  const hook = renderHook(
    ({ ports }: { ports: Ports }) =>
      useSpatialJoinBehavior({ ...data, portInputs: ports } as unknown as NodeBehaviorData, nodeState),
    { initialProps: { ports: ((data as any).portInputs ?? {}) as Ports } },
  );
  return { ...hook, data, nodeState };
}

/** Both inputs, one after the other, as the canvas delivers them: each stays on its circle. */
async function feed(rerender: (props: { ports: Ports }) => void, input0: unknown = POINTS, input1: unknown = POLYGONS) {
  await act(async () => { rerender({ ports: { in: input0 } }); });
  await act(async () => { rerender({ ports: { in: input0, in_1: input1 } }); });
  await act(async () => { await Promise.resolve(); });
}

function posted(fetchMock: jest.Mock, call = 0) {
  return JSON.parse(fetchMock.mock.calls[call][1].body);
}

/** The body as it renders now, unmounted again so a test can look twice. */
function readBody(contentComponent: React.ReactNode) {
  const { container, unmount } = render(<>{contentComponent}</>);
  const select = (label: string) => {
    const el = container.querySelector(`select[aria-label="${label}"]`) as HTMLSelectElement | null;
    return el && { value: el.value, options: Array.from(el.options).map(o => o.value) };
  };
  const label = container.querySelector('[data-curio-spatial-join-operation-label]');
  const status = container.querySelector('[data-curio-spatial-join-status]');
  const read = {
    operation: select('Operation'),
    output: select('Output'),
    labelText: label?.textContent ?? null,
    labelSwatches: label
      ? Array.from(label.querySelectorAll('[data-curio-handle-swatch]')).map(el => el.getAttribute('data-curio-handle-swatch'))
      : [],
    status: status?.textContent ?? null,
    statusSwatches: status
      ? Array.from(status.querySelectorAll('[data-curio-handle-swatch]')).map(el => el.getAttribute('data-curio-handle-swatch'))
      : [],
  };
  unmount();
  return read;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockFlow.dashboardOn = false;
});

describe('which input is which (#576)', () => {
  test('the inputs follow the circles, not their geometry: polygons on input 0 are the left side', async () => {
    const fetchMock = mockFetch(joined([]));
    const { rerender } = renderJoin();

    await feed(rerender, POLYGONS, POINTS);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const body = posted(fetchMock);
    expect(body.left).toEqual(POLYGONS);
    expect(body.right).toEqual(POINTS);
  });

  test('two polygon inputs join', async () => {
    // Both used to land in the polygons slot, and the join never ran.
    const fetchMock = mockFetch(joined([]));
    const { rerender } = renderJoin();

    await feed(rerender, POLYGONS, ZIPS);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(posted(fetchMock)).toEqual(expect.objectContaining({ left: POLYGONS, right: ZIPS }));
  });

  test('one input on both circles joins with itself', async () => {
    // Example 25's touches flow: the neighborhoods on input 0 and input 1.
    const fetchMock = mockFetch(joined([]));
    const { rerender } = renderJoin();

    await act(async () => { rerender({ ports: { in: POLYGONS, in_1: POLYGONS } }); });
    await act(async () => { await Promise.resolve(); });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(posted(fetchMock)).toEqual(expect.objectContaining({ left: POLYGONS, right: POLYGONS }));
  });
});

describe('the operation and the output (#576)', () => {
  test('the operation select lists the seven operations and starts on intersects', async () => {
    const fetchMock = mockFetch(joined([]));
    const { result, rerender } = renderJoin();
    await feed(rerender);

    expect(readBody(result.current.contentComponent).operation).toEqual({ value: 'intersects', options: OPERATIONS });
    expect(posted(fetchMock).predicate).toBe('intersects');
  });

  test('a saved operation is sent, and picking another saves it on the node', async () => {
    const fetchMock = mockFetch(joined([]));
    const { result, rerender } = renderJoin({ spatialJoin: { predicate: 'within' } });
    await feed(rerender);

    expect(posted(fetchMock).predicate).toBe('within');
    const { container } = render(<>{result.current.contentComponent}</>);
    fireEvent.change(container.querySelector('select[aria-label="Operation"]')!, { target: { value: 'nearest' } });
    expect(mockUpdateDataNode).toHaveBeenCalledWith('sj-1', expect.objectContaining({
      spatialJoin: { predicate: 'nearest' },
    }));
  });

  test('the output is one row per pair unless counts is saved, and picking it saves it', async () => {
    const fetchMock = mockFetch(joined([]));
    const { result, rerender } = renderJoin({ spatialJoin: { predicate: 'within', output: 'counts' } });
    await feed(rerender);

    expect(posted(fetchMock)).toEqual(expect.objectContaining({ predicate: 'within', output: 'counts' }));
    const body = readBody(result.current.contentComponent);
    expect(body.output).toEqual({ value: 'counts', options: ['pairs', 'counts'] });

    const { container } = render(<>{result.current.contentComponent}</>);
    fireEvent.change(container.querySelector('select[aria-label="Output"]')!, { target: { value: 'pairs' } });
    expect(mockUpdateDataNode).toHaveBeenCalledWith('sj-1', expect.objectContaining({
      spatialJoin: { predicate: 'within', output: 'pairs' },
    }));
  });

  test('with nothing saved the output is pairs', async () => {
    const fetchMock = mockFetch(joined([]));
    const { result, rerender } = renderJoin();
    await feed(rerender);

    expect(posted(fetchMock).output).toBe('pairs');
    expect(readBody(result.current.contentComponent).output!.value).toBe('pairs');
  });
});

describe('what the body says (#576)', () => {
  test('before any input it says which input goes on which circle', () => {
    mockFetch(joined([]));
    const { result } = renderHook(() => useSpatialJoinBehavior(makeData(), makeNodeState()));
    const body = readBody(result.current.contentComponent);
    expect(body.status).toMatch(/input 0 to the blue circle and input 1 to the green circle/);
    expect(body.statusSwatches).toEqual(['#3b82f6', '#22c55e']);
  });

  test('the operation reads as a sentence, each input wearing its circle', async () => {
    mockFetch(joined([]));
    const { result, rerender } = renderJoin();
    const before = readBody(result.current.contentComponent);
    expect(before.labelText).toBe('Pair each input 0 row with the input 1 rows it');
    expect(before.labelSwatches).toEqual(['#3b82f6', '#22c55e']);

    await feed(rerender);
    expect(readBody(result.current.contentComponent).labelSwatches).toEqual(['#3b82f6', '#22c55e']);
  });

  test('a pairs answer says how many pairs and how many input 0 rows matched', async () => {
    const pair = { type: 'Feature', geometry: POINTS.features[0].geometry, properties: { name: 'photo-1.jpg', pri_neigh: 'Loop' } };
    mockFetch(joined([pair, pair, pair], { pairs: 3, matched_left: 2, left_rows: 5 }));
    const { result, rerender } = renderJoin();
    await feed(rerender);

    await waitFor(() => expect(readBody(result.current.contentComponent).status).toBe('3 pairs: 2 of 5 input 0 rows matched.'));
  });

  test('one pair is one pair', async () => {
    mockFetch(joined([{ type: 'Feature', geometry: null, properties: {} }], { pairs: 1, matched_left: 1, left_rows: 3 }));
    const { result, rerender } = renderJoin();
    await feed(rerender);

    await waitFor(() => expect(readBody(result.current.contentComponent).status).toBe('1 pair: 1 of 3 input 0 rows matched.'));
  });

  test('a counts answer says how many input 1 rows have pairs', async () => {
    mockFetch(joined(POLYGONS.features, { output: 'counts', pairs: 7, matched_right: 2, right_rows: 4 }));
    const { result, rerender } = renderJoin({ spatialJoin: { output: 'counts' } });
    await feed(rerender);

    await waitFor(() => expect(readBody(result.current.contentComponent).status).toBe(
      '2 of 4 input 1 rows have pairs (7 in all); each row carries point_count.',
    ));
  });

  test('a backend warning reaches the body, the output and a toast; the join still completes', async () => {
    const warning = 'No pairs: a polygon is never within a point. Pick contains, or swap the two inputs.';
    mockFetch(joined([], { predicate: 'within', pairs: 0, matched_left: 0, left_rows: 1, warnings: [warning] }));
    const { result, rerender, data, nodeState } = renderJoin({ spatialJoin: { predicate: 'within' } });

    await feed(rerender, POLYGONS, POINTS);

    expect(data.outputCallback).toHaveBeenCalledWith('sj-1', expect.objectContaining({ dataType: 'geodataframe' }));
    expect(nodeState.setOutput).toHaveBeenLastCalledWith({ code: 'success', content: warning });
    expect(mockShowToast).toHaveBeenCalledWith(warning, 'warning');

    const { container } = render(<>{result.current.contentComponent}</>);
    expect(container.querySelector('[data-curio-spatial-join-warning]')!.textContent).toBe(warning);
    expect(container.querySelector('[data-curio-spatial-join-status]')!.textContent).toBe('0 pairs: 0 of 1 input 0 rows matched.');
  });

  test('a run with an input missing is told which one', async () => {
    mockFetch(joined([]));
    const { result, rerender, nodeState } = renderJoin();
    await act(async () => { rerender({ ports: { in: POINTS } }); });

    await act(async () => { await (result.current.sendCodeOverride as () => Promise<void>)(); });
    const last = (nodeState.setOutput as jest.Mock).mock.calls.at(-1)[0];
    expect(last.code).toBe('error');
    expect(last.content).toBe('The Spatial Join has no input 1 to join: connect it and run the nodes feeding it.');
  });
});

describe('inputs that take time, and runs (#576 keeps #151 and #792)', () => {
  test('an artifact reference is fetched before the join', async () => {
    // What every Python node hands a consumer is `{ path, dataType }`, not rows
    // (normalizeFlowInput); the join posts the rows.
    const { fetchData } = require('../../../services/api');
    (fetchData as jest.Mock)
      .mockResolvedValueOnce({ dataType: 'geodataframe', data: POINTS, schema: {} })
      .mockResolvedValueOnce({ dataType: 'geodataframe', data: POLYGONS, schema: {} });
    const fetchMock = mockFetch(joined([]));
    const nodeState = makeNodeState();
    const points = { path: 'points-artifact', dataType: 'geodataframe' };

    const { rerender } = renderHook(
      ({ ports }: { ports: Ports }) => useSpatialJoinBehavior(makeData({ portInputs: ports }), nodeState),
      { initialProps: { ports: { in: points } as Ports } },
    );
    await waitFor(() => expect(fetchData).toHaveBeenCalledWith('points-artifact'));
    rerender({ ports: { in: points, in_1: { path: 'polygons-artifact', dataType: 'geodataframe' } } });
    await waitFor(() => expect(fetchData).toHaveBeenCalledWith('polygons-artifact'));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const body = posted(fetchMock);
    expect(body.left).toEqual(POINTS);
    expect(body.right).toEqual(POLYGONS);
    expect(nodeState.setOutput).not.toHaveBeenCalledWith(expect.objectContaining({ code: 'error' }));
  });

  test('a second input arriving while the first still resolves does not lose the first', async () => {
    // Input 1 first, input 0 right behind it, while input 1's artifact is
    // still downloading: a cancel-on-new-input cleanup dropped it and the join
    // waited forever for an input it had been handed.
    const { fetchData } = require('../../../services/api');
    let releasePolygons: (v: unknown) => void = () => {};
    (fetchData as jest.Mock)
      .mockImplementationOnce(() => new Promise(resolve => { releasePolygons = resolve; }))
      .mockResolvedValueOnce({ dataType: 'geodataframe', data: POINTS, schema: {} });
    const fetchMock = mockFetch(joined([]));
    const nodeState = makeNodeState();
    const polygons = { path: 'polygons-artifact', dataType: 'geodataframe' };

    const { rerender } = renderHook(
      ({ ports }: { ports: Ports }) => useSpatialJoinBehavior(makeData({ portInputs: ports }), nodeState),
      { initialProps: { ports: { in_1: polygons } as Ports } },
    );
    await waitFor(() => expect(fetchData).toHaveBeenCalledWith('polygons-artifact'));
    rerender({ ports: { in_1: polygons, in: { path: 'points-artifact', dataType: 'geodataframe' } } });
    await waitFor(() => expect(fetchData).toHaveBeenCalledWith('points-artifact'));
    await act(async () => { releasePolygons({ dataType: 'geodataframe', data: POLYGONS, schema: {} }); });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const body = posted(fetchMock);
    expect(body.left).toEqual(POINTS);
    expect(body.right).toEqual(POLYGONS);
  });

  test('a Run All waits for inputs still on their way and for the join they start', async () => {
    // Example 10 on dev: the run counted the join done the moment it asked,
    // moved on to the charts, and they compiled before the join had answered
    // ("0 rows arrived", over a chart that drew a moment later).
    const { fetchData } = require('../../../services/api');
    let releasePolygons: (v: unknown) => void = () => {};
    (fetchData as jest.Mock)
      .mockResolvedValueOnce({ dataType: 'geodataframe', data: POINTS, schema: {} })
      .mockImplementationOnce(() => new Promise(resolve => { releasePolygons = resolve; }));
    let answer: (v: unknown) => void = () => {};
    const fetchMock = jest.fn(() => new Promise(resolve => { answer = resolve; }));
    (global as any).fetch = fetchMock;
    const points = { path: 'points-artifact', dataType: 'geodataframe' };
    const { result, rerender, data, nodeState } = renderJoin({
      portInputs: { in: points },
    });
    const order: string[] = [];
    (data.outputCallback as jest.Mock).mockImplementation(() => order.push('rows downstream'));
    (nodeState.setOutput as jest.Mock).mockImplementation((o: any) => order.push(`outcome ${o.code}`));

    await waitFor(() => expect(fetchData).toHaveBeenCalledWith('points-artifact'));
    rerender({ ports: { in: points, in_1: { path: 'polygons-artifact', dataType: 'geodataframe' } } });
    await waitFor(() => expect(fetchData).toHaveBeenCalledWith('polygons-artifact'));

    // The run asks while input 1 is still downloading.
    let done = false;
    let run: Promise<void> = Promise.resolve();
    act(() => { run = (result.current.sendCodeOverride as () => Promise<void>)().then(() => { done = true; }); });
    await act(async () => { releasePolygons({ dataType: 'geodataframe', data: POLYGONS, schema: {} }); });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(done).toBe(false);

    await act(async () => {
      answer({ ok: true, json: async () => joined([{ type: 'Feature', geometry: POINTS.features[0].geometry, properties: { pri_neigh: 'Loop' } }]) });
      await run;
    });
    expect(done).toBe(true);
    // The rows went downstream before the outcome that tells the run it is done.
    expect(order).toEqual(['rows downstream', 'outcome success']);
  });

  test('a join that already answered says so again when a run asks', async () => {
    mockFetch(joined([]));
    const { result, rerender, nodeState } = renderJoin();
    await feed(rerender);
    await waitFor(() => expect(nodeState.setOutput).toHaveBeenCalledWith(expect.objectContaining({ code: 'success' })));
    (nodeState.setOutput as jest.Mock).mockClear();

    await act(async () => { await (result.current.sendCodeOverride as () => Promise<void>)(); });
    expect(nodeState.setOutput).toHaveBeenCalledWith({ code: 'success', content: '' });
  });

  test("a run's status for the node never lands in an input slot", async () => {
    // UniversalNode sets a node's own status through `setOutputCallbackOverride`
    // when the behavior has one: `{ code: "exec" }` when a run asks it. The
    // join's inputs come through `data.portInputs`, so it has no such override.
    const fetchMock = mockFetch(joined([]));
    const { result, rerender } = renderJoin();
    expect(result.current.setOutputCallbackOverride).toBeUndefined();

    await feed(rerender);
    const body = posted(fetchMock);
    expect(body.left).toEqual(POINTS);
    expect(body.right).toEqual(POLYGONS);
  });

  test('a dashboard never joins: it shows what was saved (#609)', async () => {
    mockFlow.dashboardOn = true;
    const fetchMock = mockFetch(joined([]));
    const { rerender } = renderJoin();

    await feed(rerender);

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
