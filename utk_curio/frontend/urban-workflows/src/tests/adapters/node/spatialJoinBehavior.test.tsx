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

async function feedBoth(result: { current: any }) {
  await act(async () => {
    result.current.setOutputCallbackOverride!(POINTS, 0);
    result.current.setOutputCallbackOverride!(POLYGONS, 1);
  });
  await act(async () => {
    await Promise.resolve();
  });
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
});

describe('useSpatialJoinBehavior', () => {
  test('sends the default property when none is chosen', async () => {
    const fetchMock = mockFetch(joined([]));
    const { result } = renderHook(() => useSpatialJoinBehavior(makeData(), makeNodeState()));

    await feedBoth(result);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.name_property).toBe('name');
  });

  test('sends the persisted property', async () => {
    const fetchMock = mockFetch(joined([]));
    const { result } = renderHook(() =>
      useSpatialJoinBehavior(makeData({ spatialJoin: { nameProperty: 'pri_neigh' } }), makeNodeState()),
    );

    await feedBoth(result);

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.name_property).toBe('pri_neigh');
  });

  test('committing the control persists the property on the node', async () => {
    mockFetch(joined([]));
    const data = makeData();
    const { result } = renderHook(() => useSpatialJoinBehavior(data, makeNodeState()));

    const { container } = render(<>{result.current.contentComponent}</>);
    const input = container.querySelector('input[aria-label="Polygon property used as the tag"]') as HTMLInputElement;
    expect(input).not.toBeNull();
    expect(input.value).toBe('name');

    fireEvent.change(input, { target: { value: 'pri_neigh' } });
    fireEvent.blur(input, { target: { value: 'pri_neigh' } });

    expect(mockUpdateDataNode).toHaveBeenCalledWith(
      'sj-1',
      expect.objectContaining({ spatialJoin: { nameProperty: 'pri_neigh' } }),
    );
  });

  test('Enter commits too, and a blank falls back to the default', async () => {
    mockFetch(joined([]));
    const data = makeData({ spatialJoin: { nameProperty: 'pri_neigh' } });
    const { result } = renderHook(() => useSpatialJoinBehavior(data, makeNodeState()));

    const { container } = render(<>{result.current.contentComponent}</>);
    const input = container.querySelector('input[aria-label="Polygon property used as the tag"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '   ' } });
    fireEvent.keyDown(input, { key: 'Enter', target: { value: '   ' } });

    expect(mockUpdateDataNode).toHaveBeenCalledWith(
      'sj-1',
      expect.objectContaining({ spatialJoin: { nameProperty: 'name' } }),
    );
  });

  test('the datalist offers the polygon input\'s properties', async () => {
    mockFetch(joined([]));
    const { result } = renderHook(() => useSpatialJoinBehavior(makeData(), makeNodeState()));
    await feedBoth(result);

    const { container } = render(<>{result.current.contentComponent}</>);
    const options = Array.from(container.querySelectorAll('datalist option')).map((o) => (o as HTMLOptionElement).value);
    expect(options).toEqual(['pri_neigh', 'sec_neigh', 'shape_area']);
  });

  test('a backend warning reaches the body, the output and a toast; the join still completes', async () => {
    const warning = "No polygon has a 'name' property, so tags fall back to polygon_<index>. Available properties: pri_neigh, sec_neigh.";
    mockFetch(joined(
      [{ type: 'Feature', geometry: null, properties: { neighborhood_name: 'polygon_0' } }],
      [warning],
    ));
    const data = makeData();
    const nodeState = makeNodeState();
    const { result } = renderHook(() => useSpatialJoinBehavior(data, nodeState));

    await feedBoth(result);

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

    const { rerender } = renderHook(
      ({ input }: { input: unknown }) => useSpatialJoinBehavior(makeData({ input }), nodeState),
      { initialProps: { input: { path: 'points-artifact', dataType: 'geodataframe' } } },
    );
    await waitFor(() => expect(fetchData).toHaveBeenCalledWith('points-artifact'));
    rerender({ input: { path: 'polygons-artifact', dataType: 'geodataframe' } });
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

    const { rerender } = renderHook(
      ({ input }: { input: unknown }) => useSpatialJoinBehavior(makeData({ input }), nodeState),
      { initialProps: { input: { path: 'polygons-artifact', dataType: 'geodataframe' } } },
    );
    await waitFor(() => expect(fetchData).toHaveBeenCalledWith('polygons-artifact'));
    // The points reference arrives before the polygon download has finished.
    rerender({ input: { path: 'points-artifact', dataType: 'geodataframe' } });
    await waitFor(() => expect(fetchData).toHaveBeenCalledWith('points-artifact'));
    await act(async () => { releasePolygons({ dataType: 'geodataframe', data: POLYGONS, schema: {} }); });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.points.features).toHaveLength(1);
    expect(body.polygons.features[0].properties.pri_neigh).toBe('Loop');
  });

  test('before any input the body says what to connect', () => {
    mockFetch(joined([]));
    const { result } = renderHook(() => useSpatialJoinBehavior(makeData(), makeNodeState()));
    const { container } = render(<>{result.current.contentComponent}</>);
    expect(container.querySelector('[data-curio-spatial-join-status]')!.textContent).toMatch(/Connect points/);
  });
});
