/**
 * A Spatial Join whose two inputs land in one render keeps both.
 *
 * Example 10's Run All e2e (`test_run_all_draws_every_chart_without_an_empty_render`)
 * failed now and then with one join saying "The Spatial Join has no polygons to
 * join" (or "no points"), while the node feeding it read Done and the twin
 * join, fed seconds apart, worked. In each of the five failed runs the Data
 * Transformation, which hands both joins their polygons, finished 46 to 57 ms
 * after the Image Segmentation above the failing join, whose Simple View
 * hands that join its points. Both inputs then reached the join in one render,
 * and the failing join never fetched the input it lost: the browser log shows
 * that artifact fetched once, by the twin join only.
 *
 * Drives the REAL FlowProvider (applyNewOutput -> propagateDownstreamInputs,
 * hydrateRestoredOutputs) and the real React Flow store, with the join's real
 * behavior rendered as its canvas node, and asks the join as Run All does
 * (its sendCodeOverride). Two outputs in one `act` are one render, as two
 * outputs landing before React renders are in the browser.
 */
import React, { useRef } from 'react';
import { render, act } from '@testing-library/react';
import { Position, ReactFlow, ReactFlowProvider } from 'reactflow';
import { faCircle } from '@fortawesome/free-solid-svg-icons';

// ── jsdom polyfills ReactFlow needs ────────────────────────────────────────
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(global as any).ResizeObserver = ResizeObserverStub;
if (!(global as any).DOMMatrixReadOnly) {
  (global as any).DOMMatrixReadOnly = class { m22 = 1; constructor() {} };
}

// ── Mocks: replace the heavy/IO collaborators, keep reactflow REAL ──────────
jest.mock('../../hook/useWorkflowOperations', () => ({
  useWorkflowOperations: () => ({
    markNodeExecuted: jest.fn(),
    markNodeStale: jest.fn(),
    markDirty: jest.fn(),
    persistDataflowForInstall: jest.fn().mockResolvedValue(undefined),
    beginPendingInstall: jest.fn(),
    endPendingInstall: jest.fn(),
    failPendingInstall: jest.fn(),
    applyRemoveChanges: jest.fn(),
    applyReviewedRemovals: jest.fn(),
    allMinimized: false,
    setAllMinimized: jest.fn(),
    expandStatus: {},
    setExpandStatus: jest.fn(),
    updateDataNode: jest.fn(),
    updateDefaultCode: jest.fn(),
    workflowGoal: '',
    acceptSuggestion: jest.fn(),
  }),
}));

jest.mock('../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));

jest.mock('../../providers/CollaborationProvider', () => ({
  useCollab: () => ({
    enabled: false,
    lockedNodes: {},
    currentUserId: null,
    lockNode: jest.fn(),
    unlockNode: jest.fn(),
    signalExecDisplay: jest.fn(),
    broadcastOutputProduced: jest.fn(),
    broadcastNodeAdded: jest.fn(),
    broadcastNodeRemoved: jest.fn(),
    broadcastEdgeAdded: jest.fn(),
    broadcastEdgeRemoved: jest.fn(),
    onRemote: jest.fn(),
  }),
}));

jest.mock('../../hook/useCode', () => ({
  pythonInterpreter: {},
  jsInterpreter: {},
}));

jest.mock('../../hook/useVega', () => ({
  useVega: () => ({ handleCompileGrammar: jest.fn().mockResolvedValue(undefined) }),
}));
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });

// The artifact fetch the join resolves `{ path, dataType }` inputs with. The
// join's own POST goes through `global.fetch`, stubbed in beforeEach.
const mockFetchData = jest.fn();
jest.mock('../../services/api', () => ({
  ...jest.requireActual('../../services/api'),
  fetchData: (...args: unknown[]) => mockFetchData(...args),
}));

import FlowProvider, { useFlowContext } from '../../providers/FlowProvider';
import { CURIO_UNIVERSAL_NODE_TYPE, NodeType, SupportedType } from '../../constants';
import { registerNode } from '../../registry/nodeRegistry';
import type { NodeDescriptor } from '../../registry/types';
import { useSpatialJoinBehavior } from '../../adapters/node/spatialJoinBehavior';
import { behaviorDataView } from '../../utils/behaviorDataView';

/** The node type example 10 and example 15 give their joins. */
const JOIN_TYPE = 'curio.builtin/spatial-join';

const PHOTOS = {
  type: 'FeatureCollection',
  features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [-87.63, 41.88] }, properties: { name: 'photo-1.jpg' } }],
};
const NEIGHBORHOODS = {
  type: 'FeatureCollection',
  features: [{
    type: 'Feature',
    geometry: { type: 'Polygon', coordinates: [[[-88, 41], [-87, 41], [-87, 42], [-88, 42], [-88, 41]]] },
    properties: { neighborhood: 'Loop' },
  }],
};

/** What each input's artifact holds, as `/get` answers it. */
const ARTIFACTS: Record<string, unknown> = {
  'photos-artifact': { dataType: 'geodataframe', data: PHOTOS, schema: {} },
  'neighborhoods-artifact': { dataType: 'geodataframe', data: NEIGHBORHOODS, schema: {} },
};

/** What a Simple View hands on: the Image Segmentation's artifact, as it received it. */
const POINTS_OUT = { path: 'photos-artifact', dataType: 'geodataframe' };
/** What the Data Transformation's finished step hands on. */
const POLYGONS_OUT = { path: 'neighborhoods-artifact', dataType: 'geodataframe' };

beforeAll(() => {
  const descriptor: NodeDescriptor = {
    id: JOIN_TYPE as NodeType,
    category: 'data',
    label: 'Spatial Join',
    icon: faCircle,
    // As the shipped manifest declares them: the points and the polygons, one edge each.
    inputPorts: [
      { types: [SupportedType.GEODATAFRAME], cardinality: '1' },
      { types: [SupportedType.GEODATAFRAME], cardinality: '1' },
    ],
    outputPorts: [{ types: [SupportedType.GEODATAFRAME] }],
    editor: 'none',
    inPalette: true,
    description: '',
    hasCode: false,
    hasWidgets: false,
    hasGrammar: false,
    adapter: {
      handles: [
        { id: 'in_points', type: 'target', position: Position.Left },
        { id: 'in_polygons', type: 'target', position: Position.Left },
        { id: 'out', type: 'source', position: Position.Right },
      ],
      editor: { code: false, grammar: false, widgets: false },
      container: {},
      useNodeBehavior: useSpatialJoinBehavior,
    },
  };
  registerNode(descriptor);
});

type FlowApi = ReturnType<typeof useFlowContext>;
let api: FlowApi;

/** Each rendered join: its behavior as last rendered, and every outcome it set. */
const joins = new Map<string, { behavior: any; outcomes: any[] }>();

/** The join as its canvas node runs it: the store's node data, through the behavior. */
const JoinNode: React.FC<{ data: any }> = ({ data }) => {
  const held = useRef<{ outcomes: any[]; nodeState: any } | null>(null);
  if (!held.current) {
    const outcomes: any[] = [];
    held.current = {
      outcomes,
      // Stable for the node's lifetime, as useNodeState's is.
      nodeState: {
        output: { code: '', content: '' },
        setOutput: (output: any) => { outcomes.push(output); },
        code: '',
        setCode: () => {},
        templateData: {},
      },
    };
  }
  const behavior = useSpatialJoinBehavior(behaviorDataView(data), held.current.nodeState);
  joins.set(data.nodeId, { behavior, outcomes: held.current.outcomes });
  return <div data-testid={`join-${data.nodeId}`}>{behavior.contentComponent}</div>;
};

const NODE_TYPES = { join: JoinNode };

const Bridge: React.FC = () => {
  const ctx = useFlowContext();
  api = ctx;
  return (
    <div style={{ width: 800, height: 600 }}>
      <ReactFlow
        nodes={ctx.nodes}
        edges={ctx.edges}
        nodeTypes={NODE_TYPES}
        onNodesChange={ctx.onNodesChange}
        onEdgesChange={ctx.onEdgesChange}
      />
    </div>
  );
};

function makeNode(id: string, nodeType: string, type: string = CURIO_UNIVERSAL_NODE_TYPE) {
  return {
    id,
    type,
    position: { x: 0, y: 0 },
    data: {
      nodeId: id,
      nodeType,
      input: '',
      inputTypes: [],
      // What a canvas node's data carries (useCode): its output, downstream.
      outputCallback: (nodeId: string, output: unknown, options?: object) =>
        api.applyNewOutput({ nodeId, output, ...options } as any),
    },
  } as any;
}

async function flush() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

async function addEdge(source: string, target: string, targetHandle: string) {
  await act(async () => {
    api.onEdgesChange([
      {
        type: 'add',
        item: {
          id: `reactflow__edge-${source}out-${target}${targetHandle}`,
          source,
          target,
          sourceHandle: 'out',
          targetHandle,
        },
      } as any,
    ]);
  });
  await flush();
}

/** A join with *points* wired to its blue circle and *polygons* to its green one. */
async function openJoin(points: { id: string; type: string }, polygons: { id: string; type: string }) {
  render(
    <ReactFlowProvider>
      <FlowProvider>
        <Bridge />
      </FlowProvider>
    </ReactFlowProvider>,
  );
  await flush();
  await act(async () => {
    [makeNode(points.id, points.type), makeNode(polygons.id, polygons.type), makeNode('join', JOIN_TYPE, 'join')]
      .forEach((n) => api.addNode(n, undefined, false));
  });
  await flush();
  await addEdge(points.id, 'join', 'in_points');
  await addEdge(polygons.id, 'join', 'in_polygons');
  expect(joins.has('join')).toBe(true);
}

/** Example 10's route: a Simple View's points and the Data Transformation's polygons. */
const ROUTE = {
  points: { id: 'view', type: 'curio.builtin/vis-simple' },
  polygons: { id: 'transform', type: 'curio.builtin/data-transformation' },
};

/** What the join answers when a run asks it, as Run All asks it. */
async function askTheJoin(): Promise<any> {
  const join = joins.get('join')!;
  await act(async () => {
    await join.behavior.sendCodeOverride();
  });
  return join.outcomes.at(-1);
}

/** The inputs of every join posted to the backend. */
const posted: Array<{ points: unknown; polygons: unknown }> = [];

beforeEach(() => {
  joins.clear();
  posted.length = 0;
  mockFetchData.mockImplementation(async (path: string) => ARTIFACTS[path]);
  (global as any).fetch = jest.fn(async (url: string, init?: { body?: string }) => {
    if (!String(url).endsWith('/spatial_join')) return { ok: false, status: 404, json: async () => ({}) };
    const body = JSON.parse(init?.body ?? '{}');
    posted.push({ points: body.points, polygons: body.polygons });
    return {
      ok: true,
      json: async () => ({
        type: 'FeatureCollection',
        features: body.points.features.map((f: any) => ({ ...f, properties: { ...f.properties, neighborhood: 'Loop' } })),
        metadata: { tag_column: 'neighborhood', output: 'points', warnings: [] },
      }),
    };
  });
});

afterEach(() => {
  jest.clearAllMocks();
});

const JOINED = { asked: { code: 'success', content: '' }, posted: [{ points: PHOTOS, polygons: NEIGHBORHOODS }] };

describe('a Spatial Join whose two inputs land in one render', () => {
  test('the polygons, then the points: the join gets both and joins them', async () => {
    // Run 37238862475 (#717), twice: the polygons were lost.
    await openJoin(ROUTE.points, ROUTE.polygons);

    await act(async () => {
      api.applyNewOutput({ nodeId: 'transform', output: POLYGONS_OUT } as any);
      api.applyNewOutput({ nodeId: 'view', output: POINTS_OUT } as any);
    });
    await flush();

    expect({ asked: await askTheJoin(), posted }).toEqual(JOINED);
  });

  test('the points, then the polygons: the join gets both and joins them', async () => {
    // Runs 37196358465 (#703), 37224332761 and 37480444036 (#760): the points were lost.
    await openJoin(ROUTE.points, ROUTE.polygons);

    await act(async () => {
      api.applyNewOutput({ nodeId: 'view', output: POINTS_OUT } as any);
      api.applyNewOutput({ nodeId: 'transform', output: POLYGONS_OUT } as any);
    });
    await flush();

    expect({ asked: await askTheJoin(), posted }).toEqual(JOINED);
  });

  test('the two inputs in two renders: the join gets both and joins them', async () => {
    // The order every passing run had: the Data Transformation seconds apart.
    await openJoin(ROUTE.points, ROUTE.polygons);

    await act(async () => {
      api.applyNewOutput({ nodeId: 'transform', output: POLYGONS_OUT } as any);
    });
    await flush();
    await act(async () => {
      api.applyNewOutput({ nodeId: 'view', output: POINTS_OUT } as any);
    });
    await flush();

    expect({ asked: await askTheJoin(), posted }).toEqual(JOINED);
  });

  test('a reopened dataflow: both restored inputs reach the join, and a play of it joins them', async () => {
    // Example 15's shape: two Data Loading nodes feed the join. A load
    // restores every saved output in one tick (hydrateRestoredOutputs).
    await openJoin(
      { id: 'photos', type: 'curio.builtin/data-loading' },
      { id: 'neighborhoods', type: 'curio.builtin/data-loading' },
    );

    await act(async () => {
      api.hydrateRestoredOutputs([
        { nodeId: 'neighborhoods', output: 'neighborhoods-artifact' },
        { nodeId: 'photos', output: 'photos-artifact' },
      ] as any);
      await new Promise((r) => setTimeout(r, 5)); // hydration defers one tick
    });
    await flush();

    expect({ asked: await askTheJoin(), posted }).toEqual(JOINED);
  });
});
