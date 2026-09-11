/**
 * A run that ends - by finishing, failing or being cancelled - releases the
 * runner, and a run in flight is visible (#271).
 *
 * `playAllStateRef` guarded Run All and run-up-to, and was released only when
 * every node in the level flipped its output to success or error. It lived in
 * a ref, so no button ever showed a run was active, a click during one silently
 * did nothing, and a wedged run (an Autark node that never reported) held the
 * whole dataflow until the ten-minute watchdog or a page reload. These tests
 * drive the REAL FlowProvider the way playAllFlakiness.test.tsx does.
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

const mockPersistDataflowForInstall = jest.fn().mockResolvedValue(undefined);
const mockShowToast = jest.fn();
const mockLoadProject = jest.fn().mockResolvedValue(undefined);
const mockLoadSharedProject = jest.fn().mockResolvedValue(undefined);
const mockCleanCanvas = jest.fn();
const mockDiscardProject = jest.fn();

const STALL_TIMEOUT_MS = 600_000;

jest.mock('../../hook/useWorkflowOperations', () => ({
  useWorkflowOperations: () => ({
    markNodeExecuted: jest.fn(),
    markNodeStale: jest.fn(),
    markDirty: jest.fn(),
    persistDataflowForInstall: mockPersistDataflowForInstall,
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
    loadProject: mockLoadProject,
    loadSharedProject: mockLoadSharedProject,
    cleanCanvas: mockCleanCanvas,
    discardProject: mockDiscardProject,
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

function makeNode(id: string) {
  return {
    id,
    type: 'curio.builtin/data-loading',
    position: { x: 0, y: 0 },
    data: { nodeId: id, nodeType: 'curio.builtin/data-loading' },
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

async function addEdge(source: string, target: string) {
  await act(async () => {
    api.onEdgesChange([
      {
        type: 'add',
        item: { id: `${source}->${target}`, source, target, sourceHandle: 'out', targetHandle: 'in' },
      } as any,
    ]);
  });
  await flush();
}

function triggerExecOf(id: string): number {
  const n = api.nodes.find((x: any) => x.id === id);
  return (n?.data?.triggerExec as number) ?? 0;
}

/** A -> B, seeded and ready to run. */
async function seedChain() {
  renderFlow();
  await flush();
  await addNodes([makeNode('A'), makeNode('B')]);
  await addEdge('A', 'B');
}

async function playAll() {
  await act(async () => {
    api.playAllNodes();
  });
  await flush();
}

async function signalDone(id: string) {
  await act(async () => {
    api.signalNodeExecDone(id);
  });
  await flush();
}

afterEach(() => {
  jest.clearAllMocks();
  jest.useRealTimers();
});

describe('the run guard is released and visible (#271)', () => {
  test('isRunActive is false, then true during a run, then false again', async () => {
    await seedChain();
    expect(api.isRunActive).toBe(false);

    await playAll();
    expect(api.isRunActive).toBe(true);

    await signalDone('A');
    expect(api.isRunActive).toBe(true); // level 1 (B) is now running
    await signalDone('B');
    expect(api.isRunActive).toBe(false);
  });

  test('a finished run releases the guard, so Run All can start again', async () => {
    await seedChain();
    await playAll();
    await signalDone('A');
    await signalDone('B');
    expect(triggerExecOf('A')).toBe(1);

    await playAll();
    expect(triggerExecOf('A')).toBe(2);
    expect(mockShowToast).not.toHaveBeenCalledWith(expect.stringMatching(/already in progress/), 'info');
  });

  test('a node that ERRORS releases its level like one that succeeds', async () => {
    // signalNodeExecDone is what UniversalNode calls on either terminal
    // output; the runner does not distinguish. This pins that a failed node
    // does not hold the run, which is the contract the Autark finally relies on.
    await seedChain();
    await playAll();
    await signalDone('A'); // "A" errored - same signal
    expect(triggerExecOf('B')).toBe(1);
    await signalDone('B');
    expect(api.isRunActive).toBe(false);
  });

  test('a second Run All while one is running toasts instead of silently doing nothing', async () => {
    await seedChain();
    await playAll();

    await playAll();

    expect(mockShowToast).toHaveBeenCalledWith(
      expect.stringMatching(/already in progress/),
      'info',
    );
    // ...and did not reset the run in flight.
    expect(triggerExecOf('A')).toBe(1);
    expect(api.isRunActive).toBe(true);
  });

  test('run-up-to during a run gets the same toast', async () => {
    await seedChain();
    await playAll();

    await act(async () => {
      api.playNodesUpTo('B');
    });
    await flush();

    expect(mockShowToast).toHaveBeenCalledWith(
      expect.stringMatching(/already in progress/),
      'info',
    );
    expect(triggerExecOf('A')).toBe(1);
  });

  test('cancelRun abandons the run: later signals are ignored and the watchdog is disarmed', async () => {
    jest.useFakeTimers();
    await seedChain();
    await playAll();
    expect(api.isRunActive).toBe(true);

    await act(async () => {
      api.cancelRun();
    });
    await flush();
    expect(api.isRunActive).toBe(false);

    // A straggler from the abandoned level must not start level 1.
    await signalDone('A');
    expect(triggerExecOf('B')).toBe(0);

    // The stall watchdog belonged to the abandoned run.
    await act(async () => {
      jest.advanceTimersByTime(STALL_TIMEOUT_MS + 1000);
    });
    expect(mockShowToast).not.toHaveBeenCalledWith(expect.stringMatching(/didn't finish/), 'warning');

    // And a new run is accepted immediately.
    await playAll();
    expect(triggerExecOf('A')).toBe(2);
  });

  test('cancelRun does not fire the finishing install-save', async () => {
    // A cancelled run has nothing new to persist, and on "New workflow" the
    // user has just agreed to discard changes - saving there would be wrong.
    await seedChain();
    await playAll();
    mockPersistDataflowForInstall.mockClear();

    await act(async () => {
      api.cancelRun();
    });
    await flush();

    expect(mockPersistDataflowForInstall).not.toHaveBeenCalled();
  });

  test.each([
    ['loadProject', () => api.loadProject('p1'), mockLoadProject],
    ['loadSharedProject', () => api.loadSharedProject('p1'), mockLoadSharedProject],
    ['cleanCanvas', () => api.cleanCanvas(), mockCleanCanvas],
    ['discardProject', () => api.discardProject(), mockDiscardProject],
  ])('%s cancels a run in flight before delegating', async (_name, invoke, delegate) => {
    await seedChain();
    await playAll();
    expect(api.isRunActive).toBe(true);

    await act(async () => {
      await invoke();
    });
    await flush();

    expect(delegate).toHaveBeenCalledTimes(1);
    expect(api.isRunActive).toBe(false);
    // The next dataflow's first Run All is not refused.
    await playAll();
    expect(mockShowToast).not.toHaveBeenCalledWith(expect.stringMatching(/already in progress/), 'info');
  });

  test('the stall toast names the stuck nodes and points at Cancel', async () => {
    jest.useFakeTimers();
    await seedChain();
    await playAll();

    await act(async () => {
      jest.advanceTimersByTime(STALL_TIMEOUT_MS + 1000);
    });

    expect(mockShowToast).toHaveBeenCalledWith(
      expect.stringMatching(/\(A\).*cancel/i),
      'warning',
    );
  });
});
