/**
 * Regression test for #195 — clicking a node in the Provenance graph crashed the app.
 *
 * `onConnect` resolved its target with `nodes.find(...) as Node` and never checked
 * the result, then dereferenced it in the cycle checks. Provenance versions
 * recorded before #186 was fixed contain edges whose endpoint nodes are absent
 * from that same version (they are on disk today), so switching to one replayed
 * those edges here against an empty node list:
 *
 *     can't access property "id", target is undefined
 *     ./src/providers/FlowProvider.tsx/FlowProvider/onConnect
 *
 * `switchProvenanceTrill` wraps the call in try/catch, but that cannot help: the
 * replay happens inside a `setNodes` updater on a later render, long after the
 * try block returned. With no error boundary in the app, React tore down the root.
 *
 * Drives the REAL FlowProvider (`api.onConnect`) with the same minimal
 * <ReactFlow> bridge as connectionFanInGuard.test.tsx.
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


let warnSpy: jest.SpyInstance;
beforeEach(() => {
  warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {});
});
afterEach(() => {
  warnSpy.mockRestore();
});

afterEach(() => {
  jest.clearAllMocks();
});

describe('onConnect with a missing endpoint (#195)', () => {
  test('an edge whose target is not on the canvas is dropped, not dereferenced', async () => {
    renderFlow();
    await flush();
    await addNodes([makeNode('a', 'curio.builtin/data-loading@1')]);

    // The exact shape a pre-#186 provenance version replays: a live edge, and a
    // target that version never held.
    await expect(
      (async () => connect('a', 'ghost-target', 'in', true))(),
    ).resolves.not.toThrow();

    expect(api.edges).toHaveLength(0);
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining('endpoint not on the canvas'),
    );
  });

  test('an edge whose source is not on the canvas is dropped too', async () => {
    renderFlow();
    await flush();
    await addNodes([makeNode('b', 'curio.builtin/computation-analysis@1')]);

    await connect('ghost-source', 'b', 'in', true);

    expect(api.edges).toHaveLength(0);
  });

  test('the worst case — the whole version is empty — still does not throw', async () => {
    renderFlow();
    await flush();

    await connect('ghost-source', 'ghost-target', 'in', true);

    expect(api.edges).toHaveLength(0);
  });

  test('a well-formed edge between two present nodes still connects', async () => {
    renderFlow();
    await flush();
    await addNodes([
      makeNode('a', 'curio.builtin/data-loading@1'),
      makeNode('b', 'curio.builtin/computation-analysis@1'),
    ]);

    await connect('a', 'b');

    expect(api.edges).toHaveLength(1);
    expect(api.edges[0]).toMatchObject({ source: 'a', target: 'b' });
  });
});
