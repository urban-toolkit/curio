/**
 * Defining a scenario makes its context and outcome nodes save their outputs
 * (#662), so another project can read them: the rule a pinned dashboard tile
 * follows, read through the same `isDashboardSource` at run time. Driven
 * through the REAL FlowProvider, with the harness of
 * dashboardPresentation.test.tsx.
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
let mockScenarios: any[] = [];

jest.mock('../../hook/useWorkflowOperations', () => ({
  useWorkflowOperations: () => ({
    markNodeExecuted: jest.fn(),
    markNodeStale: jest.fn(),
    markNodeErrored: jest.fn(),
    markDirty: jest.fn(),
    persistDataflowForInstall: jest.fn().mockResolvedValue({ saved: true, failedNodeIds: [] }),
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
    saveCurrentProject: jest.fn().mockResolvedValue(undefined),
    projectId: 'project-1',
    viewerMode: 'owner',
    scenarios: mockScenarios,
    scenariosRef: { current: mockScenarios },
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
      <ReactFlow nodes={ctx.nodes} edges={ctx.edges} onNodesChange={ctx.onNodesChange} onEdgesChange={ctx.onEdgesChange} />
    </div>
  );
};

const makeNode = (id: string) =>
  ({
    id,
    type: CURIO_UNIVERSAL_NODE_TYPE,
    position: { x: 0, y: 0 },
    data: { nodeId: id, nodeType: NodeType.COMPUTATION_ANALYSIS, input: '', inputTypes: [], saveOutputDataset: false },
  }) as any;

async function flush() {
  await act(async () => { await Promise.resolve(); });
}

/** load -> a -> b, each with its Save toggle off. */
async function addChain() {
  render(
    <ReactFlowProvider>
      <FlowProvider>
        <Bridge />
      </FlowProvider>
    </ReactFlowProvider>,
  );
  await flush();
  await act(async () => {
    ['load', 'a', 'b'].forEach((id) => api.addNode(makeNode(id), undefined, false));
  });
  await flush();
  for (const [source, target] of [['load', 'a'], ['a', 'b']]) {
    await act(async () => {
      api.onConnect({ source, target, sourceHandle: 'out', targetHandle: 'in' } as any, undefined, undefined, undefined, false, true);
    });
    await flush();
  }
}

beforeEach(() => {
  jest.clearAllMocks();
  mockScenarios.length = 0;
});

describe('a scenario saves its context and outcomes', () => {
  test('its context producer and its outcome are saved, the node between them is not', async () => {
    mockScenarios.push({ id: 's1', name: 'Twice as tall', color: '#e86a3c', nodes: ['a', 'b'] });
    await addChain();
    expect(['load', 'a', 'b'].map((id) => api.isDashboardSource(id))).toEqual([true, false, true]);
  });

  test("the context's output schedules an install with its toggle off", async () => {
    mockScenarios.push({ id: 's1', name: 'Twice as tall', color: '#e86a3c', nodes: ['a', 'b'] });
    await addChain();
    await act(async () => {
      api.applyNewOutput({ nodeId: 'load', output: { path: 'art_load', dataType: 'dataframe' } });
    });
    await flush();
    expect(mockBeginPendingInstall).toHaveBeenCalledWith(expect.objectContaining({ producerNodeId: 'load' }));
  });

  test('without a scenario, the same chain saves nothing', async () => {
    await addChain();
    expect(['load', 'a', 'b'].map((id) => api.isDashboardSource(id))).toEqual([false, false, false]);
    await act(async () => {
      api.applyNewOutput({ nodeId: 'load', output: { path: 'art_load', dataType: 'dataframe' } });
    });
    await flush();
    expect(mockBeginPendingInstall).not.toHaveBeenCalled();
  });
});
