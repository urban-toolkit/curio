/**
 * The Spatial Join's polygon tag property is a setting, not a constant (#262).
 *
 * The backend had accepted `name_property` all along; the node sent the
 * literal 'name' and told users to rename their field upstream. Now the node
 * body carries the control, the value persists on the node, and a wrong
 * property is reported instead of silently tagging everything polygon_<i>.
 */
import React from 'react';
import { renderHook, render, act, fireEvent, waitFor } from '@testing-library/react';
import type { NodeBehaviorData, UseNodeStateReturn } from '../../../registry/types';

jest.mock('reactflow', () => ({
  useEdges: () => [],
  Position: { Left: 'left', Right: 'right', Top: 'top', Bottom: 'bottom' },
}));

const mockUpdateDataNode = jest.fn();
jest.mock('../../../providers/FlowProvider', () => ({
  useFlowContext: () => ({ updateDataNode: mockUpdateDataNode }),
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

import {
  useSpatialJoinBehavior,
  polygonPropertyNames,
  resolveNameProperty,
} from '../../../adapters/node/spatialJoinBehavior';

const POINTS = {
  type: 'FeatureCollection',
  features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [-87.6, 41.8] }, properties: {} }],
};
const POLYGONS = {
  type: 'FeatureCollection',
  features: [{
    type: 'Feature',
    geometry: { type: 'Polygon', coordinates: [[[-88, 41], [-87, 41], [-87, 42], [-88, 42], [-88, 41]]] },
    properties: { pri_neigh: 'Loop', sec_neigh: 'LOOP', shape_area: '1' },
  }],
};

function mockFetch(response: unknown) {
  const fetchMock = jest.fn().mockResolvedValue({ ok: true, json: async () => response });
  (global as any).fetch = fetchMock;
  return fetchMock;
}

function joined(features: any[], warnings?: string[]) {
  return {
    type: 'FeatureCollection',
    features,
    metadata: { name: 'spatial_join_result', aggregates: [], ...(warnings ? { warnings } : {}) },
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

/** The node as the canvas holds it: the same data, with what each port holds (`data.portInputs`) set by a prop. */
function renderJoin(overrides: Record<string, unknown> = {}, nodeState: UseNodeStateReturn = makeNodeState()) {
  const data = makeData(overrides);
  const hook = renderHook(
    ({ ports }: { ports: Ports }) =>
      useSpatialJoinBehavior({ ...data, portInputs: ports } as unknown as NodeBehaviorData, nodeState),
    { initialProps: { ports: ((data as any).portInputs ?? {}) as Ports } },
  );
  return { ...hook, data, nodeState };
}

/** Both inputs, one after the other, as the canvas delivers them: each stays on its port. */
async function feedBoth(rerender: (props: { ports: Ports }) => void) {
  await act(async () => { rerender({ ports: { in_points: POINTS } }); });
  await act(async () => { rerender({ ports: { in_points: POINTS, in_polygons: POLYGONS } }); });
  await act(async () => { await Promise.resolve(); });
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe('resolveNameProperty / polygonPropertyNames', () => {
  test('defaults to name, trims, and ignores blanks', () => {
    expect(resolveNameProperty({})).toBe('name');
    expect(resolveNameProperty({ spatialJoin: { nameProperty: '  pri_neigh ' } })).toBe('pri_neigh');
    expect(resolveNameProperty({ spatialJoin: { nameProperty: '   ' } })).toBe('name');
  });

  test('lists the polygon properties, sorted and de-duplicated', () => {
    expect(polygonPropertyNames(POLYGONS)).toEqual(['pri_neigh', 'sec_neigh', 'shape_area']);
    expect(polygonPropertyNames(null)).toEqual([]);
  });

  test('lists a column that only a late feature carries', () => {
    // The list is the only way to pick a column, so a sample of the first
    // features would put a later one out of reach.
    const fc = {
      type: 'FeatureCollection',
      features: [
        ...Array.from({ length: 25 }, () => ({ type: 'Feature', geometry: null, properties: { zone: 'A' } })),
        { type: 'Feature', geometry: null, properties: { zone: 'B', ward: 7 } },
      ],
    };
    expect(polygonPropertyNames(fc)).toEqual(['ward', 'zone']);
  });
});

const COLUMN_SELECT = 'select[aria-label="Tag each point with this polygon column"]';

/** The body as it renders now, unmounted again so a test can look twice. */
function readBody(contentComponent: React.ReactNode) {
  const { container, unmount } = render(<>{contentComponent}</>);
  const select = container.querySelector(COLUMN_SELECT) as HTMLSelectElement | null;
  const label = container.querySelector('[data-curio-spatial-join-column-label]');
  const read = {
    select: select && {
      value: select.value,
      disabled: select.disabled,
      options: Array.from(select.options).map(o => [o.value, o.textContent]),
    },
    labelText: label?.textContent ?? null,
    labelSwatches: label
      ? Array.from(label.querySelectorAll('[data-curio-handle-swatch]')).map(el => el.getAttribute('data-curio-handle-swatch'))
      : [],
    status: container.querySelector('[data-curio-spatial-join-status]')?.textContent ?? null,
  };
  unmount();
  return read;
}

describe('useSpatialJoinBehavior', () => {
  test('sends the default property when none is chosen', async () => {
    const fetchMock = mockFetch(joined([]));
    const { rerender } = renderJoin();

    await feedBoth(rerender);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.name_property).toBe('name');
  });

  test('sends the persisted property', async () => {
    const fetchMock = mockFetch(joined([]));
    const { rerender } = renderJoin({ spatialJoin: { nameProperty: 'pri_neigh' } });

    await feedBoth(rerender);

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.name_property).toBe('pri_neigh');
  });

  test('picking a column from the list persists it on the node', async () => {
    mockFetch(joined([]));
    const { result, rerender } = renderJoin();
    await feedBoth(rerender);

    const { container } = render(<>{result.current.contentComponent}</>);
    const select = container.querySelector(COLUMN_SELECT) as HTMLSelectElement;
    expect(select).not.toBeNull();
    expect(select.disabled).toBe(false);
    // A dropdown, not a box to type in.
    expect(container.querySelector('input[type="text"]')).toBeNull();

    fireEvent.change(select, { target: { value: 'pri_neigh' } });

    expect(mockUpdateDataNode).toHaveBeenCalledWith(
      'sj-1',
      expect.objectContaining({ spatialJoin: { nameProperty: 'pri_neigh' } }),
    );
  });

  test('the list holds the polygon columns, and says when the chosen one is not among them', async () => {
    mockFetch(joined([]));
    const { result, rerender } = renderJoin();
    await feedBoth(rerender);

    // The default `name` stays the choice, flagged, rather than the select
    // showing pri_neigh while the node joins on `name`.
    expect(readBody(result.current.contentComponent).select).toEqual({
      value: 'name',
      disabled: false,
      options: [
        ['name', 'name (not in the polygons)'],
        ['pri_neigh', 'pri_neigh'],
        ['sec_neigh', 'sec_neigh'],
        ['shape_area', 'shape_area'],
      ],
    });
  });

  test('a chosen column the polygons carry is listed once', async () => {
    mockFetch(joined([]));
    const { result, rerender } = renderJoin({ spatialJoin: { nameProperty: 'sec_neigh' } });
    await feedBoth(rerender);

    const { select } = readBody(result.current.contentComponent);
    expect(select!.value).toBe('sec_neigh');
    expect(select!.options.map(([v]) => v)).toEqual(['pri_neigh', 'sec_neigh', 'shape_area']);
  });

  test('a saved column is the choice before the polygons arrive', () => {
    mockFetch(joined([]));
    const { result } = renderHook(() =>
      useSpatialJoinBehavior(makeData({ spatialJoin: { nameProperty: 'zip' } }), makeNodeState()),
    );

    // Nothing to pick from yet: the saved choice shows, and the list waits.
    expect(readBody(result.current.contentComponent).select).toEqual({
      value: 'zip',
      disabled: true,
      options: [['zip', 'zip']],
    });
  });

  test('the column label wears both circles, before and after the join', async () => {
    mockFetch(joined([{ type: 'Feature', geometry: POINTS.features[0].geometry, properties: { name: 'Loop' } }]));
    const { result, rerender } = renderJoin();

    const before = readBody(result.current.contentComponent);
    expect(before.labelText).toMatch(/point.*polygon column/);
    expect(before.labelSwatches).toEqual(['#3b82f6', '#22c55e']);

    await feedBoth(rerender);

    // The status line no longer names the circles once the join answers; the
    // label still does.
    const after = readBody(result.current.contentComponent);
    expect(after.status).toMatch(/Tagged 1 of 1/);
    expect(after.labelSwatches).toEqual(['#3b82f6', '#22c55e']);
  });

  test('a backend warning reaches the body, the output and a toast; the join still completes', async () => {
    const warning = "No polygon has a 'name' property, so tags fall back to polygon_<index>. Available properties: pri_neigh, sec_neigh.";
    mockFetch(joined(
      [{ type: 'Feature', geometry: null, properties: { name: 'polygon_0' } }],
      [warning],
    ));
    const { result, rerender, data, nodeState } = renderJoin();

    await feedBoth(rerender);

    expect(data.outputCallback).toHaveBeenCalledWith('sj-1', expect.objectContaining({ dataType: 'geodataframe' }));
    expect(nodeState.setOutput).toHaveBeenLastCalledWith({ code: 'success', content: warning });
    expect(mockShowToast).toHaveBeenCalledWith(warning, 'warning');

    const { container } = render(<>{result.current.contentComponent}</>);
    expect(container.querySelector('[data-curio-spatial-join-warning]')!.textContent).toBe(warning);
    expect(container.querySelector('[data-curio-spatial-join-status]')!.textContent).toMatch(/Tagged 1 of 1/);
  });

  test('an artifact reference is fetched and classified before the join', async () => {
    // What every Python node hands a consumer is `{ path, dataType }`, not rows
    // (normalizeFlowInput). Classifying that by geometry type found nothing, so
    // a join fed by a sandbox node never fired; example 10's polygons come out
    // of a Data Transformation node and never reached the polygon slot.
    const { fetchData } = require('../../../services/api');
    (fetchData as jest.Mock)
      .mockResolvedValueOnce({ dataType: 'geodataframe', data: POINTS, schema: {} })
      .mockResolvedValueOnce({ dataType: 'geodataframe', data: POLYGONS, schema: {} });
    const fetchMock = mockFetch(joined([]));
    const nodeState = makeNodeState();
    const points = { path: 'points-artifact', dataType: 'geodataframe' };

    const { rerender } = renderHook(
      ({ ports }: { ports: Ports }) => useSpatialJoinBehavior(makeData({ portInputs: ports }), nodeState),
      { initialProps: { ports: { in_points: points } as Ports } },
    );
    await waitFor(() => expect(fetchData).toHaveBeenCalledWith('points-artifact'));
    rerender({ ports: { in_points: points, in_polygons: { path: 'polygons-artifact', dataType: 'geodataframe' } } });
    await waitFor(() => expect(fetchData).toHaveBeenCalledWith('polygons-artifact'));

    // Both slots resolved and classified: the join fires with the rows, not the references.
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.points.features).toHaveLength(1);
    expect(body.polygons.features[0].properties.pri_neigh).toBe('Loop');
    expect(nodeState.setOutput).not.toHaveBeenCalledWith(expect.objectContaining({ code: 'error' }));
  });

  test('a second input arriving while the first still resolves does not lose the first', async () => {
    // Example 15's order: polygons loader first, points loader right behind it.
    // The polygon artifact is still downloading when the points reference
    // lands; a cancel-on-new-input cleanup dropped it and the join waited
    // forever for polygons it had been handed.
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
      { initialProps: { ports: { in_polygons: polygons } as Ports } },
    );
    await waitFor(() => expect(fetchData).toHaveBeenCalledWith('polygons-artifact'));
    // The points reference arrives before the polygon download has finished.
    rerender({ ports: { in_polygons: polygons, in_points: { path: 'points-artifact', dataType: 'geodataframe' } } });
    await waitFor(() => expect(fetchData).toHaveBeenCalledWith('points-artifact'));
    await act(async () => { releasePolygons({ dataType: 'geodataframe', data: POLYGONS, schema: {} }); });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.points.features).toHaveLength(1);
    expect(body.polygons.features[0].properties.pri_neigh).toBe('Loop');
  });

  test('the polygon output is sent along and persisted like the property', async () => {
    const fetchMock = mockFetch(joined([]));
    const { result, rerender } = renderJoin({ spatialJoin: { nameProperty: 'zip', output: 'polygons' } });

    await feedBoth(rerender);

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.output).toBe('polygons');
    expect(body.name_property).toBe('zip');

    // Switching the control persists the choice on the node, beside the property.
    const { container } = render(<>{result.current.contentComponent}</>);
    const select = container.querySelector('select[aria-label="Output"]') as HTMLSelectElement;
    expect(select.value).toBe('polygons');
    fireEvent.change(select, { target: { value: 'points' } });
    expect(mockUpdateDataNode).toHaveBeenCalledWith('sj-1', expect.objectContaining({
      spatialJoin: expect.objectContaining({ nameProperty: 'zip', output: 'points' }),
    }));
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
      portInputs: { in_points: points },
    });
    const order: string[] = [];
    (data.outputCallback as jest.Mock).mockImplementation(() => order.push('rows downstream'));
    (nodeState.setOutput as jest.Mock).mockImplementation((o: any) => order.push(`outcome ${o.code}`));

    await waitFor(() => expect(fetchData).toHaveBeenCalledWith('points-artifact'));
    rerender({ ports: { in_points: points, in_polygons: { path: 'polygons-artifact', dataType: 'geodataframe' } } });
    await waitFor(() => expect(fetchData).toHaveBeenCalledWith('polygons-artifact'));

    // The run asks while the polygons are still downloading.
    let done = false;
    let run: Promise<void> = Promise.resolve();
    act(() => { run = (result.current.sendCodeOverride as () => Promise<void>)().then(() => { done = true; }); });
    await act(async () => { releasePolygons({ dataType: 'geodataframe', data: POLYGONS, schema: {} }); });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(done).toBe(false);

    await act(async () => {
      answer({ ok: true, json: async () => joined([{ type: 'Feature', geometry: POINTS.features[0].geometry, properties: { name: 'Loop' } }]) });
      await run;
    });
    expect(done).toBe(true);
    // The rows went downstream before the outcome that tells the run it is done.
    expect(order).toEqual(['rows downstream', 'outcome success']);
  });

  test('a join that already answered says so again when a run asks', async () => {
    mockFetch(joined([]));
    const { result, rerender, nodeState } = renderJoin();
    await feedBoth(rerender);
    await waitFor(() => expect(nodeState.setOutput).toHaveBeenCalledWith(expect.objectContaining({ code: 'success' })));
    (nodeState.setOutput as jest.Mock).mockClear();

    await act(async () => { await (result.current.sendCodeOverride as () => Promise<void>)(); });
    expect(nodeState.setOutput).toHaveBeenCalledWith({ code: 'success', content: '' });
  });

  test('a run with an input missing is told which one', async () => {
    mockFetch(joined([]));
    const { result, rerender, nodeState } = renderJoin();
    await act(async () => { rerender({ ports: { in_points: POINTS } }); });

    await act(async () => { await (result.current.sendCodeOverride as () => Promise<void>)(); });
    const last = (nodeState.setOutput as jest.Mock).mock.calls.at(-1)[0];
    expect(last.code).toBe('error');
    expect(last.content).toContain('no polygons');
  });

  test("a run's status for the node never lands in an input slot", async () => {
    // UniversalNode sets a node's own status through `setOutputCallbackOverride`
    // when the behavior has one: `{ code: "exec" }` when a run asks it, the
    // skip reason when a run passes it by. The join's override filled its
    // points slot with that, and posted it as the points: "Tagged 0 of 0
    // points" on example 10, and 0 rows for every chart after it. Its inputs
    // come through `data.portInputs`, so it has no such override.
    const fetchMock = mockFetch(joined([]));
    const { result, rerender } = renderJoin();
    expect(result.current.setOutputCallbackOverride).toBeUndefined();

    await feedBoth(rerender);
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.points).toEqual(POINTS);
    expect(body.polygons).toEqual(POLYGONS);
  });

  test('before any input the body says what to connect', () => {
    mockFetch(joined([]));
    const { result } = renderHook(() => useSpatialJoinBehavior(makeData(), makeNodeState()));
    const { container } = render(<>{result.current.contentComponent}</>);
    expect(container.querySelector('[data-curio-spatial-join-status]')!.textContent).toMatch(/Connect points/);
    // The words name the input circles by colour, and each name carries its swatch.
    const status = container.querySelector('[data-curio-spatial-join-status]')!;
    expect(status.textContent).toMatch(/blue circle.*green circle/);
    const swatches = Array.from(status.querySelectorAll('[data-curio-handle-swatch]')).map(el => el.getAttribute('data-curio-handle-swatch'));
    expect(swatches).toEqual(['#3b82f6', '#22c55e']);
  });
});
