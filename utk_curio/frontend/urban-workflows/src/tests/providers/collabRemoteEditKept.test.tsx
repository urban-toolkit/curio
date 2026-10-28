/**
 * An editor's change that lands on the owner's canvas is kept: the owner's
 * tab, the one that saves the dataflow, marks it Unsaved, so its next save
 * (or the 30 second auto-save, which waits for an Unsaved dataflow) writes
 * the change. A tab that does not save the dataflow, an editor's or a
 * watcher's, marks nothing: its leave guard has nothing of its own to lose.
 *
 * Drives the REAL FlowProvider with collaboration enabled, as
 * collabInteractions.test.tsx does.
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

const mockMarkDirty = jest.fn();
let mockViewerMode: 'owner' | 'shared' = 'owner';
jest.mock('../../hook/useWorkflowOperations', () => ({
  useWorkflowOperations: () => ({
    viewerMode: mockViewerMode,
    markNodeExecuted: jest.fn(),
    markNodeStale: jest.fn(),
    markDirty: mockMarkDirty,
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

jest.mock('../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));

const mockHandlers: Record<string, (payload: any) => void> = {};
const mockNoop = () => undefined;
const mockCollab = {
  enabled: true,
  lockedNodes: {},
  participantId: 'p-1',
  role: 'owner',
  lockNode: mockNoop,
  unlockNode: mockNoop,
  signalExecDisplay: mockNoop,
  broadcastOutputProduced: mockNoop,
  broadcastNodeAdded: mockNoop,
  broadcastNodeRemoved: mockNoop,
  broadcastEdgeAdded: mockNoop,
  broadcastEdgeRemoved: mockNoop,
  onRemote: (event: string, handler: (payload: any) => void) => {
    mockHandlers[event] = handler;
    return () => {
      if (mockHandlers[event] === handler) delete mockHandlers[event];
    };
  },
};
jest.mock('../../providers/CollaborationProvider', () => ({
  useCollab: () => mockCollab,
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

import FlowProvider, { useFlowContext } from '../../providers/FlowProvider';
import { CURIO_UNIVERSAL_NODE_TYPE } from '../../constants';

const Bridge: React.FC = () => {
  const ctx = useFlowContext();
  return (
    <div style={{ width: 800, height: 600 }}>
      <ReactFlow nodes={ctx.nodes} edges={ctx.edges} onNodesChange={ctx.onNodesChange} onEdgesChange={ctx.onEdgesChange} />
    </div>
  );
};

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

async function renderFlow() {
  render(
    <ReactFlowProvider>
      <FlowProvider>
        <Bridge />
      </FlowProvider>
    </ReactFlowProvider>,
  );
  await flush();
}

function remoteNode(id: string, x: number) {
  return {
    id,
    type: CURIO_UNIVERSAL_NODE_TYPE,
    position: { x, y: 0 },
    data: { nodeId: id, nodeType: 'curio.builtin/python-computation@1', input: '', inputTypes: [] },
  };
}

// Every change a peer's tab relays, in an order that leaves each applicable.
const PEER_CHANGES: Array<[string, any]> = [
  ['node_added', { node: remoteNode('a', 0) }],
  ['node_added', { node: remoteNode('b', 300) }],
  ['edge_added', { edge: { id: 'a-b', source: 'a', target: 'b', sourceHandle: 'out', targetHandle: 'in' } }],
  ['node_updated', { nodeId: 'a', patch: { position: { x: 40, y: 80 } } }],
  ['edge_removed', { edgeId: 'a-b' }],
  ['node_removed', { nodeId: 'b' }],
];

async function fromPeer(event: string, payload: any) {
  expect(typeof mockHandlers[event]).toBe('function');
  await act(async () => {
    mockHandlers[event](payload);
  });
  await flush();
}

beforeEach(() => {
  mockMarkDirty.mockClear();
});

afterEach(() => {
  for (const key of Object.keys(mockHandlers)) delete mockHandlers[key];
});

test.each(PEER_CHANGES.map(([event], i) => [event, i]))(
  "the owner's tab marks the dataflow Unsaved when a peer's %s lands",
  async (_event, index) => {
    mockViewerMode = 'owner';
    await renderFlow();
    for (const [event, payload] of PEER_CHANGES.slice(0, index as number)) await fromPeer(event, payload);
    mockMarkDirty.mockClear();

    const [event, payload] = PEER_CHANGES[index as number];
    await fromPeer(event, payload);

    expect(mockMarkDirty).toHaveBeenCalled();
  },
);

test("a tab that does not save the dataflow marks nothing when a peer's change lands", async () => {
  mockViewerMode = 'shared';
  await renderFlow();

  for (const [event, payload] of PEER_CHANGES) await fromPeer(event, payload);

  expect(mockMarkDirty).not.toHaveBeenCalled();
});
