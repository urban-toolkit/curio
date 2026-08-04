/**
 * INTEGRATION regression for the dev/48 apply→canvas bridge (memo dev/51).
 *
 * Drives the REAL FlowProvider + REAL reactflow + REAL useCode/usePosition +
 * REAL useAgentCanvasMutations — only IO collaborators (interpreters, sockets,
 * toasts, vega) are stubbed. The unit suite mocked useCode and the RF store,
 * which is exactly where the shipped bug lived: this test dispatches the real
 * window event and asserts the node lands in FlowProvider state (what the
 * canvas renders) without any refresh.
 */
import React from 'react';
import { render, act } from '@testing-library/react';
import { ReactFlow, ReactFlowProvider } from 'reactflow';

// ── jsdom polyfills ReactFlow needs (same as playAllFlakiness) ─────────────
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

jest.mock('../../hook/useWorkflowOperations', () => ({
  useWorkflowOperations: () => ({
    markNodeExecuted: jest.fn(),
    markNodeStale: jest.fn(),
    markDirty: jest.fn(),
    persistDataflowForInstall: jest.fn().mockResolvedValue(undefined),
    beginPendingInstall: jest.fn(),
    endPendingInstall: jest.fn(),
    applyRemoveChanges: jest.fn(),
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

// Interpreters open socket.io pools at module scope — stub the classes only,
// keeping useCode's real logic.
jest.mock('../../PythonInterpreter', () => ({ PythonInterpreter: class {} }));
jest.mock('../../JavaScriptInterpreter', () => ({ JavaScriptInterpreter: class {} }));

// vega is ESM; same stubs as the other FlowProvider integration suite.
jest.mock('../../hook/useVega', () => ({
  useVega: () => ({ handleCompileGrammar: jest.fn().mockResolvedValue(undefined) }),
}));
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });

// Registry refresh does network I/O; the plain node.create path never calls it.
const mockRefreshPackageRegistry = jest.fn(() => Promise.resolve());
jest.mock('../../registry/packageRegistryBootstrap', () => ({
  refreshPackageRegistry: () => mockRefreshPackageRegistry(),
}));

import FlowProvider, { useFlowContext } from '../../providers/FlowProvider';
import ProvenanceProvider from '../../providers/ProvenanceProvider';
import { useAgentCanvasMutations } from '../../components/agents/attach/useAgentCanvasMutations';
import { notifyAgentCanvasMutation } from '../../utils/agentCanvasEvents';

type FlowApi = ReturnType<typeof useFlowContext>;
let api: FlowApi;

/** Mirrors AgentDockOverlay's placement: a FlowProvider child, beside <ReactFlow>. */
const BridgeHost: React.FC = () => {
  useAgentCanvasMutations();
  return null;
};

const Canvas: React.FC = () => {
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
      <BridgeHost />
    </div>
  );
};

function renderCanvas() {
  return render(
    <ReactFlowProvider>
      <ProvenanceProvider>
        <FlowProvider>
          <Canvas />
        </FlowProvider>
      </ProvenanceProvider>
    </ReactFlowProvider>,
  );
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

const CREATED = {
  id: 'server-minted-node-id',
  type: 'curio.builtin/computation-analysis',
  content: "print('new')",
  goal: 'sum it',
  x: 500,
  y: 60,
};

describe('apply→canvas bridge integration (dev/48 §3.3 / dev/51 regression)', () => {
  it('a node-created event lands the node in FlowProvider state immediately', async () => {
    renderCanvas();
    await flush();
    await act(async () => {
      notifyAgentCanvasMutation({ kind: 'node-created', node: CREATED });
    });
    await flush();
    const inserted = api.nodes.find((n: any) => n.id === CREATED.id);
    expect(inserted).toBeDefined();
    expect(inserted?.data?.nodeType).toBe('curio.builtin/computation-analysis');
    expect(inserted?.position).toEqual({ x: 500, y: 60 });
    // The serialized content field carries the applied content (the next
    // canvas save must round-trip it — the dev/48 clobber guarantee).
    expect(inserted?.data?.code).toBe("print('new')");
  });

  it('a duplicate event does not double-insert (idempotence)', async () => {
    renderCanvas();
    await flush();
    await act(async () => {
      notifyAgentCanvasMutation({ kind: 'node-created', node: CREATED });
    });
    await flush();
    await act(async () => {
      notifyAgentCanvasMutation({ kind: 'node-created', node: CREATED });
    });
    await flush();
    expect(api.nodes.filter((n: any) => n.id === CREATED.id)).toHaveLength(1);
  });

  it('node-content-applied updates the live node data.code (the dev/41 clobber fix)', async () => {
    renderCanvas();
    await flush();
    await act(async () => {
      notifyAgentCanvasMutation({ kind: 'node-created', node: CREATED });
    });
    await flush();
    await act(async () => {
      notifyAgentCanvasMutation({
        kind: 'node-content-applied',
        nodeId: CREATED.id,
        content: 'print(2)',
      });
    });
    await flush();
    const node = api.nodes.find((n: any) => n.id === CREATED.id);
    expect(node?.data?.code).toBe('print(2)');
  });
});
