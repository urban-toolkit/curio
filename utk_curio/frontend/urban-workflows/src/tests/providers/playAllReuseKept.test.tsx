/**
 * A Run All's node requests say `reuseKept`, so the backend answers a node
 * whose key holds what its maker's runs kept without running it, as a
 * dashboard visitor's step is answered (dataflow audit step 6, step 9). The
 * nodes a run is asked for, a Play's node among them, always run: their
 * requests say nothing of reuse, while the nodes above them that the play
 * runs may reuse. A run that ends, a node it skips and a cancelled run leave
 * no mark behind, so a later Play runs.
 *
 * These tests drive the REAL FlowProvider as playAllRelease.test.tsx does,
 * and post each node's request as both interpreters post it
 * (`runNodeOnBackend`), reading the body the backend is sent.
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

const mockRecordOutputs = jest.fn().mockResolvedValue(undefined);
const mockShowToast = jest.fn();

jest.mock('../../hook/useWorkflowOperations', () => ({
  useWorkflowOperations: () => ({
    markNodeExecuted: jest.fn(),
    markNodeStale: jest.fn(),
    markDirty: jest.fn(),
    recordOutputs: mockRecordOutputs,
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
    loadProject: jest.fn().mockResolvedValue(undefined),
    loadSharedProject: jest.fn().mockResolvedValue(undefined),
    cleanCanvas: jest.fn(),
    discardProject: jest.fn(),
  }),
}));

jest.mock('../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));

jest.mock('../../providers/CollaborationProvider', () => ({
  useCollab: () => ({
    lockedNodes: {},
    lockNode: jest.fn(),
    unlockNode: jest.fn(),
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
import { runNodeOnBackend } from '../../utils/nodeRunRequest';

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

function makeNode(id: string) {
  return {
    id,
    type: 'curio.builtin/python-computation',
    position: { x: 0, y: 0 },
    data: { nodeId: id, nodeType: 'curio.builtin/python-computation' },
  } as any;
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

/** A -> B, seeded and ready to run. */
async function seedChain() {
  render(
    <ReactFlowProvider>
      <FlowProvider>
        <Bridge />
      </FlowProvider>
    </ReactFlowProvider>,
  );
  await flush();
  await act(async () => {
    [makeNode('A'), makeNode('B')].forEach((n) => api.addNode(n, undefined, false));
  });
  await flush();
  await act(async () => {
    api.onEdgesChange([
      { type: 'add', item: { id: 'A->B', source: 'A', target: 'B', sourceHandle: 'out', targetHandle: 'in' } } as any,
    ]);
  });
  await flush();
}

/** The bodies the backend was sent, in order. */
let bodies: Array<Record<string, unknown>> = [];

beforeEach(() => {
  bodies = [];
  (global as any).fetch = jest.fn((_url: string, init: any) => {
    bodies.push(JSON.parse(init.body));
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ stdout: [], stderr: '', output: { path: 'p', dataType: 'str' } }),
    });
  });
});

afterEach(() => {
  jest.clearAllMocks();
});

/** The node's run posted as both interpreters post it; the body it sent. */
async function requestOf(id: string): Promise<Record<string, unknown>> {
  await act(async () => {
    runNodeOnBackend('/processPythonCode', { code: '    return 1\n', nodeType: 'curio.builtin/python-computation', nodeId: id },
      id, () => undefined, () => undefined);
  });
  await flush();
  const sent = bodies.filter((body) => body.nodeId === id);
  return sent[sent.length - 1];
}

async function signalDone(id: string, failed = false) {
  await act(async () => {
    api.signalNodeExecDone(id, failed ? { failed: true } : undefined);
  });
  await flush();
}

describe("a Run All's requests may reuse what was kept; the nodes a run is asked for run", () => {
  test("every node a Run All runs says reuseKept", async () => {
    await seedChain();
    await act(async () => { api.playAllNodes(); });
    await flush();

    expect(await requestOf('A')).toMatchObject({ reuseKept: true });
    await signalDone('A');
    expect(await requestOf('B')).toMatchObject({ reuseKept: true });
  });

  test("a Play's node says nothing of reuse, and the node above it that the play runs may reuse", async () => {
    await seedChain();
    await act(async () => { api.playNodesUpTo('B'); });
    await flush();

    expect(await requestOf('A')).toMatchObject({ reuseKept: true });
    await signalDone('A');
    const played = await requestOf('B');
    expect(played.nodeId).toBe('B');
    expect(played).not.toHaveProperty('reuseKept');
  });

  test('a run that ends, a node it skips and a cancelled run leave no mark behind', async () => {
    await seedChain();
    await act(async () => { api.playAllNodes(); });
    await flush();
    expect(await requestOf('A')).toMatchObject({ reuseKept: true });
    await signalDone('A', true);
    // B was skipped: A, which feeds it, failed. The run is over.
    expect(api.isRunActive).toBe(false);
    expect(await requestOf('A')).not.toHaveProperty('reuseKept');
    expect(await requestOf('B')).not.toHaveProperty('reuseKept');

    await act(async () => { api.playAllNodes(); });
    await flush();
    await act(async () => { api.cancelRun(); });
    await flush();
    expect(await requestOf('A')).not.toHaveProperty('reuseKept');
  });
});
