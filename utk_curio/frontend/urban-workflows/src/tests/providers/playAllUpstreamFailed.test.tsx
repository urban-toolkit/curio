/**
 * A node that fails stops the nodes after it, in Run All and in a node's own
 * Play (#603).
 *
 * The report: a Python Computation node reading `arg['sp_units']` failed with
 * "This node received no input but its code references `arg`", although its
 * input was wired. The node feeding it had failed a moment earlier in the same
 * run, and the runner went on to the next level anyway, so the downstream node
 * ran on nothing and reported a wiring problem instead of the real one.
 *
 * A failure travels in the signal that completes the node, so the runner
 * decides what to skip from the signal itself rather than from React state
 * that may not have committed yet. Drives the REAL FlowProvider the way
 * playAllRelease.test.tsx does.
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

const mockMarkNodeErrored = jest.fn();

jest.mock('../../hook/useWorkflowOperations', () => ({
  useWorkflowOperations: () => ({
    markNodeExecuted: jest.fn(),
    markNodeStale: jest.fn(),
    markNodeErrored: mockMarkNodeErrored,
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

/** A node that has never run, named so the reason can be checked by name. */
function makeNode(id: string, label: string = `Node ${id}`) {
  return {
    id,
    type: 'curio.builtin/computation-analysis',
    position: { x: 0, y: 0 },
    data: {
      nodeId: id,
      nodeType: 'curio.builtin/computation-analysis',
      packageTemplateLabel: label,
      output: { code: '', content: '' },
    },
  } as any;
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

async function seed(nodes: any[], edges: Array<[string, string]>) {
  render(
    <ReactFlowProvider>
      <FlowProvider>
        <Bridge />
      </FlowProvider>
    </ReactFlowProvider>,
  );
  await flush();
  await act(async () => {
    nodes.forEach((n) => api.addNode(n, undefined, false));
  });
  await flush();
  for (const [source, target] of edges) {
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
}

function dataOf(id: string): any {
  return api.nodes.find((x: any) => x.id === id)?.data ?? {};
}

const triggerExecOf = (id: string): number => (dataOf(id).triggerExec as number) ?? 0;

async function playAll() {
  await act(async () => {
    api.playAllNodes();
  });
  await flush();
}

async function playUpTo(id: string) {
  await act(async () => {
    api.playNodesUpTo(id);
  });
  await flush();
}

/** What CodeEditor does when the sandbox reports a failure. */
async function fail(id: string) {
  await act(async () => {
    api.signalNodeExecDone(id, { failed: true });
  });
  await flush();
}

async function succeed(id: string) {
  await act(async () => {
    api.signalNodeExecDone(id);
  });
  await flush();
}

afterEach(() => {
  jest.clearAllMocks();
});

describe('Run All stops below a failed node (#603)', () => {
  test('the child of a failed node is never run, and the run still ends', async () => {
    await seed([makeNode('A', 'Load parcels'), makeNode('B')], [['A', 'B']]);
    await playAll();
    expect(triggerExecOf('A')).toBe(1);

    await fail('A');

    expect(triggerExecOf('B')).toBe(0);
    expect(api.isRunActive).toBe(false);
  });

  test('an unrelated branch in the same run still runs', async () => {
    await seed(
      [makeNode('A'), makeNode('B'), makeNode('C'), makeNode('D')],
      [['A', 'B'], ['C', 'D']],
    );
    await playAll();
    expect(triggerExecOf('A')).toBe(1);
    expect(triggerExecOf('C')).toBe(1);

    await fail('A');
    await succeed('C');

    expect(triggerExecOf('B')).toBe(0);
    expect(triggerExecOf('D')).toBe(1);
    expect(api.isRunActive).toBe(true); // D is running

    await succeed('D');
    expect(api.isRunActive).toBe(false);
  });

  test('the stop is transitive: nothing below the failed node runs', async () => {
    await seed([makeNode('A'), makeNode('B'), makeNode('C')], [['A', 'B'], ['B', 'C']]);
    await playAll();

    await fail('A');

    expect(triggerExecOf('B')).toBe(0);
    expect(triggerExecOf('C')).toBe(0);
    expect(api.isRunActive).toBe(false);
  });

  test('a node with one failed input and one good input is not run', async () => {
    await seed([makeNode('A'), makeNode('C'), makeNode('B')], [['A', 'B'], ['C', 'B']]);
    await playAll();

    await succeed('C');
    await fail('A');

    expect(triggerExecOf('B')).toBe(0);
    expect(api.isRunActive).toBe(false);
  });

  test('a node that was not run says which node feeding it failed', async () => {
    await seed([makeNode('A', 'Load parcels'), makeNode('B', 'Index'), makeNode('C')], [['A', 'B'], ['B', 'C']]);
    await playAll();

    await fail('A');

    expect(dataOf('B').skipExec).toBe(1);
    expect(String(dataOf('B').skipReason)).toContain('The node feeding this one');
    expect(String(dataOf('B').skipReason)).toContain('Load parcels');
    // C is fed by B, which did not run: C names B, the node it is wired to.
    expect(String(dataOf('C').skipReason)).toContain('Index');
    // Marked errored, so the nodes they feed read "upstream-errored" by the
    // same rule a chart or a Data Pool already uses.
    expect(mockMarkNodeErrored).toHaveBeenCalledWith('B');
    expect(mockMarkNodeErrored).toHaveBeenCalledWith('C');
  });

  test('only the signal that completes a node decides: a later failure does not stop its children', async () => {
    // A chart emits its rows, which completes it, and may then report that it
    // drew nothing. By then the level has moved on.
    await seed([makeNode('A'), makeNode('B')], [['A', 'B']]);
    await playAll();

    await succeed('A');
    await fail('A');

    expect(triggerExecOf('B')).toBe(1);
  });

  test('the next Run All runs the stopped nodes again', async () => {
    await seed([makeNode('A'), makeNode('B')], [['A', 'B']]);
    await playAll();
    await fail('A');
    expect(triggerExecOf('B')).toBe(0);

    await playAll();
    await succeed('A');

    expect(triggerExecOf('B')).toBe(1);
  });
});

describe("a node's own Play stops below a failed ancestor (#603)", () => {
  test('the played node is not run when the node feeding it fails', async () => {
    await seed([makeNode('A', 'Load parcels'), makeNode('B')], [['A', 'B']]);

    await playUpTo('B');
    expect(triggerExecOf('A')).toBe(1); // A never succeeded, so it runs first
    expect(triggerExecOf('B')).toBe(0);

    await fail('A');

    expect(triggerExecOf('B')).toBe(0);
    expect(String(dataOf('B').skipReason)).toContain('Load parcels');
    expect(api.isRunActive).toBe(false);
  });
});
