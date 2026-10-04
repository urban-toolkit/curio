/**
 * Run scenario (#662): `playNodesUpTo` with a list runs every node in it, a
 * scenario's levers, and of the nodes feeding them only those whose output
 * cannot be reused: a context node that ran runs no more, one that never ran
 * runs first, once. Harness copied from playNodesUpToWidgets.test.tsx.
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
    broadcastNodeAdded: jest.fn(),
    broadcastNodeRemoved: jest.fn(),
    broadcastNodeUpdated: jest.fn(),
    broadcastEdgeAdded: jest.fn(),
    broadcastEdgeRemoved: jest.fn(),
    signalExecDisplay: jest.fn(),
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
      <ReactFlow nodes={ctx.nodes} edges={ctx.edges} onNodesChange={ctx.onNodesChange} onEdgesChange={ctx.onEdgesChange} />
    </div>
  );
};

/** A node; one that *ran* holds a success from its current code. */
function flowNode(id: string, ran: boolean) {
  const code = `return '${id}'`;
  return {
    id,
    type: 'curio.builtin/computation-analysis',
    position: { x: 0, y: 0 },
    data: {
      nodeId: id,
      nodeType: 'curio.builtin/computation-analysis',
      code,
      ...(ran ? { executedCode: code, output: { code: 'success', content: '' } } : {}),
    },
  } as any;
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

/** context -> lever1 -> lever2, and context -> elsewhere. Every lever has run. */
async function seed(contextRan: boolean) {
  render(
    <ReactFlowProvider>
      <FlowProvider>
        <Bridge />
      </FlowProvider>
    </ReactFlowProvider>,
  );
  await flush();
  await act(async () => {
    [flowNode('context', contextRan), flowNode('lever1', true), flowNode('lever2', true), flowNode('elsewhere', true)]
      .forEach((n) => api.addNode(n, undefined, false));
  });
  await flush();
  for (const [source, target] of [['context', 'lever1'], ['lever1', 'lever2'], ['context', 'elsewhere']]) {
    await act(async () => {
      api.onEdgesChange([
        { type: 'add', item: { id: `${source}->${target}`, source, target, sourceHandle: 'out', targetHandle: 'in' } } as any,
      ]);
    });
    await flush();
  }
}

const triggerExecOf = (id: string) => ((api.nodes.find((x: any) => x.id === id)?.data?.triggerExec as number) ?? 0);
const triggered = () => ['context', 'lever1', 'lever2', 'elsewhere'].filter((id) => triggerExecOf(id) > 0);

describe('Run scenario: playNodesUpTo with a list (#662)', () => {
  test('every lever runs, though each has run, and a context node that ran does not', async () => {
    await seed(true);
    await act(async () => {
      api.playNodesUpTo(['lever1', 'lever2']);
    });
    await flush();
    // lever1 leads; lever2 waits for it, in the next level.
    expect(triggered()).toEqual(['lever1']);
    expect(api.isRunActive).toBe(true);
  });

  test('a context node that never ran runs first, and nothing outside the scenario', async () => {
    await seed(false);
    await act(async () => {
      api.playNodesUpTo(['lever1', 'lever2']);
    });
    await flush();
    expect(triggered()).toEqual(['context']);
  });

  test('one id still runs that node alone after what it needs', async () => {
    await seed(true);
    await act(async () => {
      api.playNodesUpTo('lever2');
    });
    await flush();
    expect(triggered()).toEqual(['lever2']);
  });
});
