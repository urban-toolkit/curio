/**
 * After a saved dataflow is reopened, playing a downstream node must not re-run
 * the upstream nodes whose outputs the load restored (#407, and the memory
 * pressure it adds to #408).
 *
 * `playNodesUpTo` already skips an ancestor that succeeded and whose code is
 * unchanged (playNodesUpToStale.test.tsx). What it could not see was a restored
 * output: the load put each saved output back into `outputs` and into the
 * downstream inputs, but built every node with no `data.output` and no
 * `data.executedCode`, so each ancestor counted as never having run and the
 * whole chain ran again, loaders included.
 *
 * Drives the real `useCode().loadTrill`, so the nodes under test are the ones a
 * reopen actually builds, then hands them to the real FlowProvider the way
 * playNodesUpToStale.test.tsx seeds its nodes. `loadParsedTrill` (which lives
 * in the mocked useWorkflowOperations) only captures what loadTrill built.
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

const mockLoaded: { nodes: any[]; edges: any[] } = { nodes: [], edges: [] };

jest.mock('../../hook/useWorkflowOperations', () => ({
  useWorkflowOperations: () => ({
    loadParsedTrill: (_name: string, _task: string, nodes: any[], edges: any[]) => {
      mockLoaded.nodes = nodes;
      mockLoaded.edges = edges;
    },
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

jest.mock('../../hook/useVega', () => ({
  useVega: () => ({ handleCompileGrammar: jest.fn().mockResolvedValue(undefined) }),
}));
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });

import FlowProvider, { useFlowContext } from '../../providers/FlowProvider';
import { useCode } from '../../hook/useCode';

let api: ReturnType<typeof useFlowContext>;
let code: ReturnType<typeof useCode>;

const Bridge: React.FC = () => {
  api = useFlowContext();
  code = useCode();
  return (
    <div style={{ width: 800, height: 600 }}>
      <ReactFlow
        nodes={api.nodes}
        edges={api.edges}
        onNodesChange={api.onNodesChange}
        onEdgesChange={api.onEdgesChange}
      />
    </div>
  );
};

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

/** A saved dataflow: a loader feeding a transform feeding a chart. */
const SPEC = {
  dataflow: {
    name: 'ChicagoTest',
    task: '',
    nodes: [
      { id: 'load', type: 'curio.builtin/data-loading', content: 'return gpd.read_file(p)', x: 0, y: 0 },
      { id: 'shape', type: 'curio.builtin/data-transformation', content: 'return arg', x: 900, y: 0 },
      { id: 'chart', type: 'curio.builtin/data-transformation', content: 'return arg', x: 1800, y: 0 },
    ],
    edges: [
      { id: 'load->shape', source: 'load', target: 'shape' },
      { id: 'shape->chart', source: 'shape', target: 'chart' },
    ],
  },
};

/** What the project manifest restored for the two upstream nodes. */
const RESTORED = {
  load: '1700000000000_aaaa0001',
  shape: '1700000000000_aaaa0002',
};

function triggerExecOf(id: string): number {
  const n = api.nodes.find((x: any) => x.id === id);
  return (n?.data?.triggerExec as number) ?? 0;
}

async function reopen(restored: Record<string, string>) {
  render(
    <ReactFlowProvider>
      <FlowProvider>
        <Bridge />
      </FlowProvider>
    </ReactFlowProvider>,
  );
  await flush();
  await act(async () => {
    // The fourth argument is the restored outputs, by node id.
    (code.loadTrill as any)(SPEC, undefined, undefined, restored);
  });
  await flush();
  await act(async () => {
    mockLoaded.nodes.forEach((n) => api.addNode(n, undefined, false));
  });
  await flush();
  for (const edge of mockLoaded.edges) {
    await act(async () => {
      api.onEdgesChange([{ type: 'add', item: edge } as any]);
    });
    await flush();
  }
}

describe('reopening a saved dataflow', () => {
  test.failing('a downstream play reuses the outputs the load restored', async () => {
    await reopen(RESTORED);

    await act(async () => {
      api.playNodesUpTo('chart');
    });
    await flush();

    expect(triggerExecOf('load')).toBe(0);
    expect(triggerExecOf('shape')).toBe(0);
    expect(triggerExecOf('chart')).toBe(1);
  });

  test.failing('a restored node shows the output it was saved with', async () => {
    await reopen(RESTORED);

    const load = api.nodes.find((n: any) => n.id === 'load');
    expect(load?.data?.output).toEqual({
      code: 'success',
      content: `Saved to file: ${RESTORED.load}`,
    });
    expect(load?.data?.executedCode).toBe(SPEC.dataflow.nodes[0].content);
  });

  test.failing('a node the load restored nothing for still runs', async () => {
    await reopen({ load: RESTORED.load });

    await act(async () => {
      api.playNodesUpTo('chart');
    });
    await flush();

    // `shape` has no saved output, so it leads the run; `load` is reused.
    expect(triggerExecOf('load')).toBe(0);
    expect(triggerExecOf('shape')).toBe(1);
    expect(triggerExecOf('chart')).toBe(0);
  });

  test('with nothing restored the whole chain runs, loader first', async () => {
    await reopen({});

    await act(async () => {
      api.playNodesUpTo('chart');
    });
    await flush();

    expect(triggerExecOf('load')).toBe(1);
    expect(triggerExecOf('shape')).toBe(0);
    expect(triggerExecOf('chart')).toBe(0);
  });
});
