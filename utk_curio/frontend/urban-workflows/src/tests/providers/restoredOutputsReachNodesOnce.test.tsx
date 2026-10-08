/**
 * A load hands each output it restores to each node below it once.
 *
 * Opening a dataflow, a shared link to it or its dashboard restores its saved
 * outputs (`ProjectLoader.applyResult`): `outputs` gets them, for a save and a
 * play's `reuse`, and `hydrateRestoredOutputs` passes them down the edges the
 * load built. The load builds those edges by replaying each saved edge through
 * `onConnect`, which hands a new edge its source's output from `outputsRef`;
 * `setOutputs` writes that ref at once, before the replay runs, so the replay
 * found the restored outputs there and handed them over as well. Every node
 * below a restored output got it twice, and a Data Pool fetched its artifact
 * twice.
 *
 * The real ProjectLoader, FlowProvider, useWorkflowOperations and useCode run
 * here, under a router on the dataflow's or the dashboard's address; the
 * projects and runs APIs are mocked. A delivery is a new `data.input` on a
 * node: each one is a fresh object (`normalizeFlowInput`), and a node's effects
 * run again on it, so the bridge records every value a node commits.
 */
import React, { useEffect } from 'react';
import { render, act, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { Position, ReactFlow, ReactFlowProvider } from 'reactflow';
import { faCircle } from '@fortawesome/free-solid-svg-icons';

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(global as any).ResizeObserver = ResizeObserverStub;
if (!(global as any).DOMMatrixReadOnly) {
  (global as any).DOMMatrixReadOnly = class { m22 = 1; constructor() {} };
}

const mockShowToast = jest.fn();
const mockGetProject = jest.fn();
const mockGetShared = jest.fn();
const mockUpdateProject = jest.fn();

jest.mock('../../api/projectsApi', () => {
  const actual = jest.requireActual('../../api/projectsApi');
  return {
    ...actual,
    projectsApi: {
      ...actual.projectsApi,
      get: (...args: any[]) => mockGetProject(...args),
      getShared: (...args: any[]) => mockGetShared(...args),
      update: (...args: any[]) => mockUpdateProject(...args),
    },
  };
});

jest.mock('../../services/runs/runsApi', () => {
  const actual = jest.requireActual('../../services/runs/runsApi');
  return {
    ...actual,
    runsApi: {
      ...actual.runsApi,
      // A reopened canvas asks for the dataflow's last run: it has none.
      listForProject: () => Promise.resolve([]),
    },
  };
});

jest.mock('../../registry/packageRegistryBootstrap', () => ({
  refreshPackageRegistry: () => Promise.resolve(),
}));

jest.mock('../../providers/packages/useEnsureWorkflowDeps', () => ({
  useEnsureWorkflowDeps: () => () => {},
}));

jest.mock('../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
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
    broadcastNodeUpdated: jest.fn(),
    broadcastEdgeAdded: jest.fn(),
    broadcastEdgeRemoved: jest.fn(),
    onRemote: jest.fn(),
  }),
}));

jest.mock('../../hook/useVega', () => ({
  useVega: () => ({ handleCompileGrammar: jest.fn().mockResolvedValue(undefined) }),
}));
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });

import FlowProvider, { useFlowContext } from '../../providers/FlowProvider';
import { ProjectLoader } from '../../components/ProjectLoader';
import { useScenarioActions } from '../../components/scenarios/useScenarioActions';
import { NodeType, SupportedType } from '../../constants';
import { registerNode } from '../../registry/nodeRegistry';
import type { NodeDescriptor } from '../../registry/types';

const PROJECT_ID = '5f0c7a2e-91d4-4b6a-8c3e-2d7f1a9b4e60';

const DATA_LOADING = 'curio.builtin/data-loading';
const DATA_POOL = 'curio.builtin/data-pool';
const VEGA = 'curio.builtin/vis-vega';
/** Python Computation: one input port that grows a circle per edge. */
const COMPUTATION = 'curio.builtin/computation-analysis';

// The node a load restores, and the nodes below it.
/** A frame, saved. */
const PRODUCER = 'producer';
/** A tuple, saved as a bundle. */
const TUPLE = 'tuple';
/** Never ran: nothing saved. */
const IDLE = 'idle';
/** The producer's one input. */
const POOL = 'pool';
/** The producer on its one circle. */
const SUMMARY = 'summary';
/** The producer on circle 0 and the tuple on circle 1. */
const JOIN = 'join';
/** Below the pool, which never runs here. */
const CHART = 'chart';
/** The idle node on its one circle. */
const WAITING = 'waiting';
const IDS = [PRODUCER, TUPLE, IDLE, POOL, SUMMARY, JOIN, CHART, WAITING];

/** The saved outputs, as `GET /api/projects/<id>` lists them. */
const SAVED = [
  { node_id: PRODUCER, filename: 'art_producer', data_type: 'dataframe' },
  { node_id: TUPLE, filename: 'art_tuple', data_type: 'outputs' },
];
/** Each saved output as the nodes below it take it in. */
const FRAME = { path: 'art_producer', dataType: 'dataframe' };
const TUPLE_REF = { path: 'art_tuple', dataType: 'outputs' };

beforeAll(() => {
  // Python Computation as its shipped manifest declares its input: `[1,n]`.
  const descriptor: NodeDescriptor = {
    id: `${COMPUTATION}@1` as NodeType,
    category: 'computation',
    label: 'Python Computation',
    icon: faCircle,
    inputPorts: [{ types: [SupportedType.DATAFRAME], cardinality: '[1,n]' }],
    outputPorts: [{ types: [SupportedType.DATAFRAME] }],
    editor: 'code',
    inPalette: true,
    description: '',
    hasCode: true,
    hasWidgets: false,
    hasGrammar: false,
    adapter: {
      handles: [
        { id: 'in', type: 'target', position: Position.Left },
        { id: 'out', type: 'source', position: Position.Right },
      ],
      editor: { code: true, grammar: false, widgets: false },
      container: {},
      useNodeBehavior: () => ({}),
    },
  };
  registerNode(descriptor);
});

function spec() {
  const node = (id: string, type: string, x: number, y: number) => ({
    id, type, x, y, content: '', in: 'DEFAULT', out: 'DEFAULT', goal: '', metadata: { keywords: [] },
  });
  const edge = (source: string, target: string, targetHandle: string) => ({
    id: `${source}->${target}:${targetHandle}`, source, target, sourceHandle: 'out', targetHandle,
  });
  return {
    dataflow: {
      name: 'Restored once',
      task: '',
      description: '',
      packages: [],
      datasets: [],
      nodes: [
        node(PRODUCER, DATA_LOADING, 0, 0),
        node(TUPLE, COMPUTATION, 0, 500),
        node(IDLE, DATA_LOADING, 0, 1000),
        node(POOL, DATA_POOL, 700, 0),
        node(SUMMARY, COMPUTATION, 700, 500),
        node(JOIN, COMPUTATION, 700, 1000),
        node(WAITING, COMPUTATION, 700, 1500),
        node(CHART, VEGA, 1400, 0),
      ],
      edges: [
        edge(PRODUCER, POOL, 'in'),
        edge(PRODUCER, SUMMARY, 'in'),
        edge(PRODUCER, JOIN, 'in'),
        edge(TUPLE, JOIN, 'in_1'),
        edge(IDLE, WAITING, 'in'),
        edge(POOL, CHART, 'in'),
      ],
    },
  };
}

/** What `GET /api/projects/<id>` (or its shared twin) answers. */
function loadResponse() {
  return {
    project: {
      id: PROJECT_ID, name: 'Restored once', spec_revision: 2,
      updated_at: '2026-10-08T09:00:00Z', categories: {},
    },
    spec: spec(),
    outputs: SAVED.map((ref) => ({ ...ref })),
  };
}

type FlowApi = ReturnType<typeof useFlowContext>;
let api: FlowApi;
let scenarioActions: ReturnType<typeof useScenarioActions>;
/** Every value each node's `data.input` committed, in order: one per delivery. */
let delivered: Map<string, unknown[]>;

const Bridge: React.FC = () => {
  api = useFlowContext();
  scenarioActions = useScenarioActions();
  const { nodes } = api;
  useEffect(() => {
    for (const node of nodes) {
      const input = node.data?.input;
      if (input === undefined || input === null || input === '') continue;
      const values = delivered.get(node.id) ?? [];
      if (!values.includes(input)) values.push(input);
      delivered.set(node.id, values);
    }
  }, [nodes]);
  return (
    <div style={{ width: 800, height: 600 }}>
      <ReactFlow
        nodes={api.nodes}
        edges={api.edges}
        onNodesChange={api.onNodesChange}
        onEdgesChange={api.onEdgesChange}
      />
    </div>
  );
};

/** Open the saved dataflow at its address, as the canvas or as its dashboard. */
function open(page: 'dataflow' | 'dashboard') {
  const dashboard = page === 'dashboard';
  render(
    <MemoryRouter initialEntries={[`/${page}/${PROJECT_ID}`]}>
      <Routes>
        <Route
          path={`/${page}/:id`}
          element={
            <ReactFlowProvider>
              <FlowProvider dashboardOn={dashboard}>
                <ProjectLoader presentation={dashboard}>
                  <Bridge />
                </ProjectLoader>
              </FlowProvider>
            </ReactFlowProvider>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

const deliveriesTo = (id: string) => delivered.get(id) ?? [];

async function wait(ms: number) {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });
}

/** The load landed and passed its outputs on; anything later has had its turn. */
async function settle() {
  await waitFor(() => expect(deliveriesTo(JOIN)).not.toHaveLength(0), { timeout: 5000 });
  // The restored outputs go down a tick after the load (hydrateRestoredOutputs).
  await wait(50);
}

function expectEachRestoredOutputOnce() {
  expect({
    [POOL]: deliveriesTo(POOL),
    [SUMMARY]: deliveriesTo(SUMMARY),
    [JOIN]: deliveriesTo(JOIN),
    [CHART]: deliveriesTo(CHART),
    [WAITING]: deliveriesTo(WAITING),
  }).toEqual({
    [POOL]: [FRAME],
    [SUMMARY]: [FRAME],
    // Both circles in one value, in circle order: never one of them alone.
    [JOIN]: [{ dataType: 'outputs', data: [FRAME, TUPLE_REF] }],
    // The pool never runs here, and nothing was saved for the idle node.
    [CHART]: [],
    [WAITING]: [],
  });
}

beforeEach(() => {
  delivered = new Map();
  mockGetProject.mockResolvedValue(loadResponse());
  mockGetShared.mockResolvedValue(loadResponse());
  mockUpdateProject.mockImplementation(async (id: string) => ({
    id, name: 'Restored once', spec_revision: 3, spec: spec(), categories: {}, outputs: [],
  }));
});

afterEach(() => {
  jest.clearAllMocks();
});

describe('a load hands each restored output to each node below it once', () => {
  test('when the dataflow is reopened', async () => {
    open('dataflow');
    await settle();

    expect(mockGetShared).not.toHaveBeenCalled();
    expectEachRestoredOutputOnce();
  });

  test('when a shared link opens it', async () => {
    mockGetProject.mockRejectedValue(Object.assign(new Error('not found'), { status: 404 }));

    open('dataflow');
    await settle();

    expect(mockGetShared).toHaveBeenCalledWith(PROJECT_ID);
    expectEachRestoredOutputOnce();
  });

  test('when its dashboard opens', async () => {
    open('dashboard');
    await settle();

    expectEachRestoredOutputOnce();
  });
});

// These two pass before the change too. They pin what the edge replay still
// does: set up a circle whose source has nothing to give, and hand a node the
// canvas already had a new edge's output.
describe('what the load still does', () => {
  test('a circle whose source has no saved output is wired and waits', async () => {
    open('dataflow');
    await settle();

    const waiting = api.nodes.find((n) => n.id === WAITING);
    expect(waiting?.data?.input).toBe('');
    expect(Array.isArray(waiting?.data?.inputSlots)).toBe(true);
    expect(waiting?.data?.sourceSlots?.[0]).toBe(IDLE);
  });

  test('Duplicate selection hands the copy the output that feeds it', async () => {
    open('dataflow');
    await settle();

    await act(async () => {
      api.onNodesChange([{ id: SUMMARY, type: 'select', selected: true }]);
    });
    await act(async () => {
      scenarioActions.duplicate(false);
    });
    await wait(50);

    const copies = api.nodes.filter((n) => !IDS.includes(n.id));
    expect(copies).toHaveLength(1);
    expect(api.edges.some((e) => e.source === PRODUCER && e.target === copies[0].id)).toBe(true);
    expect(copies[0].data?.input).toEqual(FRAME);
  });
});
