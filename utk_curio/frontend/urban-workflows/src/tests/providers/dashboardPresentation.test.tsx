/**
 * What the provider does differently for a dashboard, driven through the REAL
 * FlowProvider (the harness playAllRelease.test.tsx established).
 *
 * Three things, and each one is a way the old canvas mode would have misbehaved
 * now that the dashboard is a page someone else can open:
 *
 *  - `dashboardOn` is a PROP. It says which route mounted the tree, so nothing
 *    inside can toggle it and there is no second set of coordinates to keep.
 *  - the install sync follows PINS, not just the per-node Save toggle. That is
 *    what puts the output behind a tile into the Data Catalog, which is the only
 *    reason a dashboard can draw without a run.
 *  - and it never runs from the dashboard itself. A tile that auto-renders emits
 *    an output like any run; on the canvas that schedules a save, and from a
 *    dashboard that would either rewrite the owner's dataflow or throw at a
 *    visitor who did nothing but open a link.
 */
import React from 'react';
import { render, act } from '@testing-library/react';
import { ReactFlow, ReactFlowProvider } from 'reactflow';

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(global as any).ResizeObserver = ResizeObserverStub;
if (!(global as any).DOMMatrixReadOnly) {
  (global as any).DOMMatrixReadOnly = class { m22 = 1; constructor() {} };
}

const mockBeginPendingInstall = jest.fn();
const mockPersistDataflowForInstall = jest.fn().mockResolvedValue({ saved: true, failedNodeIds: [] });
const mockMarkDirty = jest.fn();
const mockShowToast = jest.fn();

jest.mock('../../hook/useWorkflowOperations', () => ({
  useWorkflowOperations: () => ({
    markNodeExecuted: jest.fn(),
    markNodeStale: jest.fn(),
    markNodeErrored: jest.fn(),
    markDirty: mockMarkDirty,
    persistDataflowForInstall: mockPersistDataflowForInstall,
    beginPendingInstall: mockBeginPendingInstall,
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
    loadProject: jest.fn(),
    loadSharedProject: jest.fn(),
    cleanCanvas: jest.fn(),
    discardProject: jest.fn(),
  }),
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
    broadcastEdgeAdded: jest.fn(),
    broadcastEdgeRemoved: jest.fn(),
    broadcastNodeUpdated: jest.fn(),
    onRemote: jest.fn(),
  }),
}));
jest.mock('../../hook/useCode', () => ({ pythonInterpreter: {}, jsInterpreter: {} }));
jest.mock('../../hook/useVega', () => ({
  useVega: () => ({ handleCompileGrammar: jest.fn().mockResolvedValue(undefined) }),
}));
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });

import FlowProvider, { useFlowContext } from '../../providers/FlowProvider';
import { CURIO_UNIVERSAL_NODE_TYPE, NodeType } from '../../constants';

type FlowApi = ReturnType<typeof useFlowContext>;
let api: FlowApi;

const Bridge: React.FC = () => {
  const ctx = useFlowContext();
  api = ctx;
  return (
    <div style={{ width: 800, height: 600 }}>
      <ReactFlow
        nodes={ctx.nodes}
        edges={ctx.edges}
        onNodesChange={ctx.onNodesChange}
        onEdgesChange={ctx.onEdgesChange}
      />
    </div>
  );
};

function renderFlow(dashboardOn = false) {
  return render(
    <ReactFlowProvider>
      <FlowProvider dashboardOn={dashboardOn}>
        <Bridge />
      </FlowProvider>
    </ReactFlowProvider>,
  );
}

function makeNode(id: string, nodeType: string, data: Record<string, unknown> = {}) {
  return {
    id,
    type: CURIO_UNIVERSAL_NODE_TYPE,
    position: { x: 0, y: 0 },
    data: { nodeId: id, nodeType, input: '', inputTypes: [], ...data },
  } as any;
}

async function flush() {
  await act(async () => { await Promise.resolve(); });
}

/** Build a producer feeding a pinned chart, the shape a dashboard is made of. */
async function addPinnedChain(saveOutputDataset?: boolean) {
  await act(async () => {
    api.addNode(makeNode('py', NodeType.COMPUTATION_ANALYSIS,
      saveOutputDataset === undefined ? {} : { saveOutputDataset }), undefined, false);
    api.addNode(makeNode('chart', NodeType.VIS_VEGA, { dashboardPinned: true }), undefined, false);
  });
  await flush();
  await connect('py', 'chart');
}

/**
 * Connect two nodes the way a LOAD does: with validation skipped.
 *
 * The type check needs the node-descriptor registry, which no unit test boots,
 * so an interactively-validated connect silently drops the edge here. The load
 * path passes the same flag for persisted edges, and a dashboard is only ever
 * built from those.
 */
async function connect(source: string, target: string) {
  await act(async () => {
    api.onConnect(
      { source, target, sourceHandle: 'out', targetHandle: 'in' } as any,
      undefined, undefined, undefined, false, true,
    );
  });
  await flush();
}

beforeEach(() => jest.clearAllMocks());

describe('the presentation flag', () => {
  test('it comes from the route, not from state', async () => {
    renderFlow(true);
    await flush();
    expect(api.dashboardOn).toBe(true);
  });

  test('a canvas tree is not a dashboard', async () => {
    renderFlow(false);
    await flush();
    expect(api.dashboardOn).toBe(false);
    // Tiles start locked either way: the dashboard unlocks explicitly.
    expect(api.dashboardLocked).toBe(true);
  });
});

describe('which outputs get saved', () => {
  test('a producer feeding a pinned tile is a dashboard source', async () => {
    renderFlow();
    await addPinnedChain();

    expect(api.isDashboardSource('py')).toBe(true);
    // The chart itself is not: it passes its input through.
    expect(api.isDashboardSource('chart')).toBe(false);
  });

  test('its output schedules an install even with its toggle off', async () => {
    renderFlow();
    await addPinnedChain(false);

    await act(async () => {
      api.applyNewOutput({ nodeId: 'py', output: { path: 'art_py', dataType: 'dataframe' } });
    });
    await flush();

    // Without this the tile would render an empty box on a page the owner shared,
    // because nothing would have put the rows in the Data Catalog.
    expect(mockBeginPendingInstall).toHaveBeenCalledWith(
      expect.objectContaining({ producerNodeId: 'py' }),
    );
  });

  test('a producer that feeds nothing pinned is left alone', async () => {
    renderFlow();
    await act(async () => {
      api.addNode(makeNode('py', NodeType.COMPUTATION_ANALYSIS, { saveOutputDataset: false }), undefined, false);
    });
    await flush();

    await act(async () => {
      api.applyNewOutput({ nodeId: 'py', output: { path: 'art_py', dataType: 'dataframe' } });
    });
    await flush();

    expect(mockBeginPendingInstall).not.toHaveBeenCalled();
  });

  test('nothing is saved from the dashboard itself', async () => {
    renderFlow(true);
    await addPinnedChain(true);

    await act(async () => {
      api.applyNewOutput({ nodeId: 'py', output: { path: 'art_py', dataType: 'dataframe' } });
    });
    await flush();

    // A tile drawing itself is not an edit, and a visitor holding a link cannot
    // save at all - the attempt would surface as an error toast on a page they
    // only opened to look at.
    expect(mockBeginPendingInstall).not.toHaveBeenCalled();
    expect(mockPersistDataflowForInstall).not.toHaveBeenCalled();
  });
});

describe('pinning', () => {
  test('it marks the dataflow dirty', async () => {
    renderFlow();
    await act(async () => {
      api.addNode(makeNode('chart', NodeType.VIS_VEGA), undefined, false);
    });
    await flush();
    mockMarkDirty.mockClear();

    await act(async () => { api.setPinForDashboard('chart', true); });
    await flush();

    // A pin is part of the saved spec. Unsaved, the dashboard would not show it.
    expect(mockMarkDirty).toHaveBeenCalled();
  });

  test('it says which outputs will be saved', async () => {
    renderFlow();
    await act(async () => {
      api.addNode(makeNode('py', NodeType.COMPUTATION_ANALYSIS, { templateName: 'Load trips' }), undefined, false);
      api.addNode(makeNode('chart', NodeType.VIS_VEGA), undefined, false);
    });
    await flush();
    await connect('py', 'chart');
    mockShowToast.mockClear();

    await act(async () => { api.setPinForDashboard('chart', true); });
    await flush();

    const said = mockShowToast.mock.calls.map((call: any[]) => String(call[0])).join(' ');
    expect(said).toContain('Data Catalog');
  });

  test('unpinning says nothing', async () => {
    renderFlow();
    await act(async () => {
      api.addNode(makeNode('chart', NodeType.VIS_VEGA, { dashboardPinned: true }), undefined, false);
    });
    await flush();
    mockShowToast.mockClear();

    await act(async () => { api.setPinForDashboard('chart', false); });
    await flush();

    expect(mockShowToast).not.toHaveBeenCalled();
  });
});

describe('restoring outputs', () => {
  test('hydration can be told which edges to use', async () => {
    renderFlow(true);
    await act(async () => {
      api.addNode(makeNode('py', NodeType.COMPUTATION_ANALYSIS), undefined, false);
      api.addNode(makeNode('chart', NodeType.VIS_VEGA, { dashboardPinned: true }), undefined, false);
    });
    await flush();

    // No edge has been committed to React Flow's store, which is the state right
    // after a load: the store is written from an effect. The dashboard has no
    // Play to fall back on, so the restore has to work from the edges the load
    // built rather than from the store.
    jest.useFakeTimers();
    try {
      act(() => {
        api.hydrateRestoredOutputs(
          [{ nodeId: 'py', output: { path: 'art_py', dataType: 'dataframe' } }],
          [{ id: 'e', source: 'py', target: 'chart', sourceHandle: 'out', targetHandle: 'in' }],
        );
        jest.runAllTimers();
      });
    } finally {
      jest.useRealTimers();
    }
    await flush();

    const chart = api.nodes.find((node: any) => node.id === 'chart') as any;
    expect(chart.data.input).toEqual({ path: 'art_py', dataType: 'dataframe' });
  });
});
