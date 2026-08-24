/**
 * Regression tests for the "Play All" flaky dataset-generation fix.
 *
 * Drives the REAL FlowProvider orchestration (playAllNodes / triggerLevel /
 * signalNodeExecDone and the debounced install scheduler). A minimal <ReactFlow>
 * mirrors how MainCanvas wires FlowContext.nodes into the store so
 * reactFlow.getNodes() (which the runner reads) returns the seeded graph.
 *
 * Pins the two front-end fixes from the investigation:
 *   Vector 1 — a node that never signals done used to wedge every downstream
 *              level forever. The stall watchdog now force-advances the run.
 *   Vector 2 — the 500ms install-save debounce used to be dropped on unmount.
 *              It is now flushed, so the last burst's datasets are persisted.
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
const mockPersistDataflowForInstall = jest.fn().mockResolvedValue(undefined);
const mockBeginPendingInstall = jest.fn();
const mockEndPendingInstall = jest.fn();
const mockShowToast = jest.fn();

// Watchdog timeout in FlowProvider (PLAY_ALL_STALL_TIMEOUT_MS). Kept in sync here
// so the recovery test advances just past it.
const STALL_TIMEOUT_MS = 600_000;

jest.mock('../../hook/useWorkflowOperations', () => ({
  useWorkflowOperations: () => ({
    markNodeExecuted: jest.fn(),
    markNodeStale: jest.fn(),
    markDirty: jest.fn(),
    persistDataflowForInstall: mockPersistDataflowForInstall,
    beginPendingInstall: mockBeginPendingInstall,
    endPendingInstall: mockEndPendingInstall,
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

// useCode pulls in socket.io etc. at import; the orchestration tests drive
// completion manually, so a light stub is enough.
jest.mock('../../hook/useCode', () => ({
  pythonInterpreter: {},
  jsInterpreter: {},
}));

// FlowProvider -> ConnectionValidator -> registry -> vegaBehavior -> useVega
// pulls in vega (ESM). Stub it so the registry loads under jest.
jest.mock('../../hook/useVega', () => ({
  useVega: () => ({ handleCompileGrammar: jest.fn().mockResolvedValue(undefined) }),
}));
// The registry also statically requires vega/vega-lite (ESM) via the Vega-Lite
// adapter; stub them so the module graph parses.
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });

import FlowProvider, { useFlowContext } from '../../providers/FlowProvider';

// Captures the live FlowContext so the test can call the real orchestration API.
type FlowApi = ReturnType<typeof useFlowContext>;
let api: FlowApi;

const Bridge: React.FC = () => {
  const ctx = useFlowContext();
  api = ctx;
  // Mirror MainCanvas: feed FlowContext nodes/edges into the RF store so
  // reactFlow.getNodes()/getEdges() (read by playAllNodes) stay in sync.
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

function makeNode(id: string, extraData: Record<string, unknown> = {}) {
  return {
    id,
    type: 'curio.builtin/data-loading', // producer; not a sink / palette node
    position: { x: 0, y: 0 },
    data: { nodeId: id, nodeType: 'curio.builtin/data-loading', ...extraData },
  } as any;
}

async function flush() {
  // let RF sync controlled props into the store + run effects
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

async function addEdge(source: string, target: string) {
  await act(async () => {
    api.onEdgesChange([
      {
        type: 'add',
        item: {
          id: `${source}->${target}`,
          source,
          target,
          sourceHandle: 'out',
          targetHandle: 'in',
        },
      } as any,
    ]);
  });
  await flush();
}

/** Read a node's current triggerExec from the live FlowContext nodes. */
function triggerExecOf(id: string): number {
  const n = api.nodes.find((x: any) => x.id === id);
  return (n?.data?.triggerExec as number) ?? 0;
}

afterEach(() => {
  jest.clearAllMocks();
});

describe('Play All orchestration — flakiness vectors', () => {
  test('happy path: a level only advances after its node signals done', async () => {
    renderFlow();
    await flush();
    await addNodes([makeNode('A'), makeNode('B')]);
    await addEdge('A', 'B'); // A -> B : levels [[A],[B]]

    await act(async () => {
      api.playAllNodes();
    });
    await flush();

    // Level 0 (A) fired; level 1 (B) is still waiting.
    expect(triggerExecOf('A')).toBe(1);
    expect(triggerExecOf('B')).toBe(0);

    // A completes -> level advances -> B fires.
    await act(async () => {
      api.signalNodeExecDone('A');
    });
    await flush();
    expect(triggerExecOf('B')).toBe(1);
  });

  test('VECTOR 1 (manual): completing the stuck node still advances the run', async () => {
    renderFlow();
    await flush();
    // A, A2 -> B : levels [[A, A2], [B]]
    await addNodes([makeNode('A'), makeNode('A2'), makeNode('B')]);
    await addEdge('A', 'B');
    await addEdge('A2', 'B');

    await act(async () => {
      api.playAllNodes();
    });
    await flush();
    expect(triggerExecOf('A')).toBe(1);
    expect(triggerExecOf('A2')).toBe(1);

    // Only A completes -> pending still holds A2 -> B is held back (not stuck
    // forever now; the watchdog is the safety net, asserted in the next test).
    await act(async () => {
      api.signalNodeExecDone('A');
    });
    await flush();
    expect(triggerExecOf('B')).toBe(0);

    // A2 completes -> level empties -> B fires.
    await act(async () => {
      api.signalNodeExecDone('A2');
    });
    await flush();
    expect(triggerExecOf('B')).toBe(1);
  });

  test('VECTOR 1 (fix): the stall watchdog force-advances when a node never signals', async () => {
    jest.useFakeTimers();
    try {
      renderFlow();
      await act(async () => {
        await Promise.resolve();
      });
      await act(async () => {
        api.addNode(makeNode('A'), undefined, false);
        api.addNode(makeNode('A2'), undefined, false);
        api.addNode(makeNode('B'), undefined, false);
      });
      await act(async () => {
        await Promise.resolve();
      });
      await act(async () => {
        api.onEdgesChange([
          { type: 'add', item: { id: 'A->B', source: 'A', target: 'B', sourceHandle: 'out', targetHandle: 'in' } } as any,
          { type: 'add', item: { id: 'A2->B', source: 'A2', target: 'B', sourceHandle: 'out', targetHandle: 'in' } } as any,
        ]);
      });
      await act(async () => {
        await Promise.resolve();
      });

      await act(async () => {
        api.playAllNodes();
      });
      await act(async () => {
        await Promise.resolve();
      });

      // A finishes; A2 never does. Before the timeout B is held back.
      await act(async () => {
        api.signalNodeExecDone('A');
      });
      await act(async () => {
        await Promise.resolve();
      });
      expect(triggerExecOf('B')).toBe(0);

      // Watchdog fires -> warns + force-advances past the stuck node -> B runs.
      await act(async () => {
        jest.advanceTimersByTime(STALL_TIMEOUT_MS + 1);
        await Promise.resolve();
      });
      expect(triggerExecOf('B')).toBe(1);
      expect(mockShowToast).toHaveBeenCalledWith(
        expect.stringContaining("didn't finish"),
        'warning',
      );
    } finally {
      jest.useRealTimers();
    }
  });

  test('VECTOR 2 (fix): the pending install-save is flushed on unmount, not dropped', async () => {
    jest.useFakeTimers();
    try {
      const { unmount } = renderFlow();
      // flush mount under fake timers
      await act(async () => {
        await Promise.resolve();
      });
      await act(async () => {
        api.addNode(makeNode('A', { saveOutputDataset: true }), undefined, false);
      });
      await act(async () => {
        await Promise.resolve();
      });

      // A produced an output -> schedules the debounced install save.
      act(() => {
        api.applyNewOutput({ nodeId: 'A', output: { dataType: 'dataframe', data: {} } } as any);
      });

      // Within the debounce window the timer hasn't fired on its own yet.
      act(() => {
        jest.advanceTimersByTime(499);
      });
      expect(mockPersistDataflowForInstall).not.toHaveBeenCalled();

      // Provider unmounts inside the window -> cleanup now FLUSHES the save.
      unmount();

      // The save fired despite the early unmount -> A's dataset is persisted.
      expect(mockPersistDataflowForInstall).toHaveBeenCalledTimes(1);
    } finally {
      jest.useRealTimers();
    }
  });

  test('control: without an unmount, the debounced save fires once after 500ms', async () => {
    jest.useFakeTimers();
    try {
      renderFlow();
      await act(async () => {
        await Promise.resolve();
      });
      await act(async () => {
        api.addNode(makeNode('A', { saveOutputDataset: true }), undefined, false);
      });
      await act(async () => {
        await Promise.resolve();
      });

      act(() => {
        api.applyNewOutput({ nodeId: 'A', output: { dataType: 'dataframe', data: {} } } as any);
      });
      act(() => {
        jest.advanceTimersByTime(500);
      });

      expect(mockPersistDataflowForInstall).toHaveBeenCalledTimes(1);
    } finally {
      jest.useRealTimers();
    }
  });
});

describe('install-sync scoping (#180): the save is told which nodes it covers', () => {
  // The unit coverage for the filter itself lives in
  // useWorkflowOperations.installSync.test.ts. These pin the other half: that
  // FlowProvider hands the hook the real pending set, and exactly that set.
  async function mountWith(nodes: any[]) {
    const rendered = renderFlow();
    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => {
      nodes.forEach((n) => api.addNode(n, undefined, false));
    });
    await act(async () => {
      await Promise.resolve();
    });
    return rendered;
  }

  const output = (nodeId: string) =>
    ({ nodeId, output: { dataType: 'dataframe', data: {} } }) as any;

  test('a single producer scopes the save to its own id', async () => {
    jest.useFakeTimers();
    try {
      await mountWith([makeNode('A', { saveOutputDataset: true })]);

      act(() => {
        api.applyNewOutput(output('A'));
      });
      act(() => {
        jest.advanceTimersByTime(500);
      });

      expect(mockPersistDataflowForInstall).toHaveBeenCalledWith(['A']);
    } finally {
      jest.useRealTimers();
    }
  });

  test('a debounced burst scopes the one save to every producer in it', async () => {
    // The Play All shape: two nodes finish inside the 500ms window and collapse
    // into a single save, which must still be allowed to warn about BOTH.
    jest.useFakeTimers();
    try {
      await mountWith([
        makeNode('A', { saveOutputDataset: true }),
        makeNode('B', { saveOutputDataset: true }),
      ]);

      act(() => {
        api.applyNewOutput(output('A'));
        jest.advanceTimersByTime(200); // still inside the window
        api.applyNewOutput(output('B'));
        jest.advanceTimersByTime(500);
      });

      expect(mockPersistDataflowForInstall).toHaveBeenCalledTimes(1);
      const [ids] = mockPersistDataflowForInstall.mock.calls[0];
      expect([...ids].sort()).toEqual(['A', 'B']);
    } finally {
      jest.useRealTimers();
    }
  });

  test('a node whose save-output toggle is OFF is never in the scope', async () => {
    jest.useFakeTimers();
    try {
      await mountWith([
        makeNode('A', { saveOutputDataset: true }),
        makeNode('C', { saveOutputDataset: false }),
      ]);

      act(() => {
        api.applyNewOutput(output('C'));
        api.applyNewOutput(output('A'));
        jest.advanceTimersByTime(500);
      });

      const [ids] = mockPersistDataflowForInstall.mock.calls[0];
      expect([...ids]).toEqual(['A']);
    } finally {
      jest.useRealTimers();
    }
  });

  test('the unmount flush keeps the scope (Vector 2 + #180 together)', async () => {
    jest.useFakeTimers();
    try {
      const { unmount } = await mountWith([makeNode('A', { saveOutputDataset: true })]);

      act(() => {
        api.applyNewOutput(output('A'));
      });
      act(() => {
        jest.advanceTimersByTime(499);
      });
      unmount();

      expect(mockPersistDataflowForInstall).toHaveBeenCalledWith(['A']);
    } finally {
      jest.useRealTimers();
    }
  });
});
