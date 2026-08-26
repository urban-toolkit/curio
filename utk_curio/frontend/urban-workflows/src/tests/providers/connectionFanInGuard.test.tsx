/**
 * dev/67-3 (DEC-051) — the onConnect fan-in guard: one edge per rendered
 * input handle. Before the guard, a second edge into an occupied non-merge
 * handle was accepted and silently overwrote `data.input` (last writer wins);
 * merge's slot machinery stays the only multi-edge surface, byte-identical.
 *
 * Drives the REAL FlowProvider (`api.onConnect`) with the same minimal
 * <ReactFlow> bridge as mergeFlowPropagation.test.tsx.
 */
import React from 'react';
import { render, act } from '@testing-library/react';
import { ReactFlow, ReactFlowProvider } from 'reactflow';

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

const mockShowToast = jest.fn();
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

// Type compatibility is 67-3-orthogonal — the guard under test is arity.
jest.mock('../../ConnectionValidator', () => ({
  ConnectionValidator: { checkBoxCompatibility: () => true },
}));

import FlowProvider, { useFlowContext } from '../../providers/FlowProvider';
import { CURIO_UNIVERSAL_NODE_TYPE } from '../../constants';

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

function renderFlow() {
  return render(
    <ReactFlowProvider>
      <FlowProvider>
        <Bridge />
      </FlowProvider>
    </ReactFlowProvider>,
  );
}

function makeNode(id: string, nodeType: string) {
  return {
    id,
    type: CURIO_UNIVERSAL_NODE_TYPE,
    position: { x: 0, y: 0 },
    data: { nodeId: id, nodeType, input: '', inputTypes: [] },
  } as any;
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

async function addNodes(nodes: any[]) {
  await act(async () => {
    nodes.forEach((n) => api.addNode(n, undefined, false));
  });
  await flush();
}

async function connect(source: string, target: string, targetHandle = 'in', skipValidation = false) {
  await act(async () => {
    api.onConnect(
      { source, target, sourceHandle: 'out', targetHandle } as any,
      undefined, undefined, undefined, false, skipValidation,
    );
  });
  await flush();
}

afterEach(() => {
  jest.clearAllMocks();
});

describe('onConnect fan-in guard (dev/67-3, DEC-051)', () => {
  test('a second edge into an occupied non-merge handle is refused with the Merge suggestion', async () => {
    renderFlow();
    await flush();
    await addNodes([
      makeNode('a', 'curio.builtin/data-loading@1'),
      makeNode('b', 'curio.builtin/data-loading@1'),
      makeNode('c', 'curio.builtin/computation-analysis@1'),
    ]);
    await connect('a', 'c');
    expect(api.edges).toHaveLength(1);
    await connect('b', 'c');
    expect(api.edges).toHaveLength(1); // refused — never silently overwritten
    expect(mockShowToast).toHaveBeenCalledWith(
      'This input already has a connection — route multiple flows through a Merge node.',
      'warning',
    );
  });

  test('merge slot behavior is byte-identical (two edges land on in_0/in_1)', async () => {
    renderFlow();
    await flush();
    await addNodes([
      makeNode('a', 'curio.builtin/data-loading@1'),
      makeNode('b', 'curio.builtin/data-loading@1'),
      makeNode('m', 'curio.builtin/merge-flow@1'),
    ]);
    await connect('a', 'm');
    await connect('b', 'm');
    expect(api.edges).toHaveLength(2);
    expect(api.edges.map((e: any) => e.targetHandle).sort()).toEqual(['in_0', 'in_1']);
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  test('distinct named handles on one node each accept their own edge (spatial-join shape)', async () => {
    renderFlow();
    await flush();
    await addNodes([
      makeNode('pts', 'curio.builtin/data-loading@1'),
      makeNode('polys', 'curio.builtin/data-loading@1'),
      makeNode('sj', 'curio.builtin/spatial-join@1'),
    ]);
    await connect('pts', 'sj', 'in_points');
    await connect('polys', 'sj', 'in_polygons');
    expect(api.edges).toHaveLength(2); // per-handle, not per-node
    await connect('pts', 'sj', 'in_polygons');
    expect(api.edges).toHaveLength(2); // occupied handle refused
  });

  test('the load path warns but NEVER drops a persisted multi-input edge', async () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => undefined);
    try {
      renderFlow();
      await flush();
      await addNodes([
        makeNode('a', 'curio.builtin/data-loading@1'),
        makeNode('b', 'curio.builtin/data-loading@1'),
        makeNode('c', 'curio.builtin/computation-analysis@1'),
      ]);
      await connect('a', 'c', 'in', true);
      await connect('b', 'c', 'in', true); // persisted duplicate on load
      expect(api.edges).toHaveLength(2); // surfaced, never destroyed
      expect(warn).toHaveBeenCalledWith(expect.stringContaining('multi-input'));
      expect(mockShowToast).not.toHaveBeenCalledWith(
        expect.stringContaining('already has a connection'),
        'warning',
      );
    } finally {
      warn.mockRestore();
    }
  });
});
