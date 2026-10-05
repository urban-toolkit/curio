/**
 * `playNodesUpTo` runs a node again when one of its widget values changed
 * since it ran (#662).
 *
 * Before, the cache compared the code text only, and the code still held the
 * reference, so a new value left the node "already run" and Run used the old
 * output. The run key (`nodeRunKey`) now covers the values; `useNodeState`
 * records it on success. Harness copied from playNodesUpToStale.test.tsx.
 */
import React from 'react';
import { render, act } from '@testing-library/react';
import { ReactFlow, ReactFlowProvider } from 'reactflow';
import { nodeRunKey, type WidgetDef } from '../../utils/widgets/widgetModel';

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

const factor = (value?: number): WidgetDef[] => [
  { name: 'factor', type: 'number', default: 1, ...(value !== undefined ? { value } : {}) },
];

/** A node that ran successfully with *ranWith*, and now holds *now*. */
function ranNode(id: string, ranWith: WidgetDef[], now: WidgetDef[]) {
  const code = 'return [!! factor !!]';
  return {
    id,
    type: 'curio.builtin/data-loading',
    position: { x: 0, y: 0 },
    data: {
      nodeId: id,
      nodeType: 'curio.builtin/data-loading',
      code,
      widgets: now,
      executedCode: nodeRunKey(code, ranWith),
      output: { code: 'success', content: '' },
    },
  } as any;
}

const plainNode = (id: string) =>
  ({
    id,
    type: 'curio.builtin/data-loading',
    position: { x: 0, y: 0 },
    data: {
      nodeId: id,
      nodeType: 'curio.builtin/data-loading',
      code: 'return arg',
      executedCode: 'return arg',
      output: { code: 'success', content: '' },
    },
  }) as any;

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

async function seed(nodes: any[], edges: Array<[string, string]>) {
  await act(async () => {
    nodes.forEach((n) => api.addNode(n, undefined, false));
  });
  await flush();
  for (const [source, target] of edges) {
    await act(async () => {
      api.onEdgesChange([
        { type: 'add', item: { id: `${source}->${target}`, source, target, sourceHandle: 'out', targetHandle: 'in' } } as any,
      ]);
    });
    await flush();
  }
}

const triggerExecOf = (id: string) => ((api.nodes.find((x: any) => x.id === id)?.data?.triggerExec as number) ?? 0);

function renderFlow() {
  return render(
    <ReactFlowProvider>
      <FlowProvider>
        <Bridge />
      </FlowProvider>
    </ReactFlowProvider>,
  );
}

describe('playNodesUpTo and widget values (#662)', () => {
  test('an ancestor whose widget value is what it ran with is not run again', async () => {
    renderFlow();
    await flush();
    await seed([ranNode('A', factor(2), factor(2)), plainNode('B')], [['A', 'B']]);

    await act(async () => {
      api.playNodesUpTo('B');
    });
    await flush();

    expect(triggerExecOf('A')).toBe(0);
    expect(triggerExecOf('B')).toBe(1);
  });

  test('an ancestor whose widget value changed since it ran runs again', async () => {
    renderFlow();
    await flush();
    await seed([ranNode('A', factor(2), factor(5)), plainNode('B')], [['A', 'B']]);

    await act(async () => {
      api.playNodesUpTo('B');
    });
    await flush();

    // Same code, new value: A leads the run and B waits for it.
    expect(triggerExecOf('A')).toBe(1);
    expect(triggerExecOf('B')).toBe(0);
  });
});
