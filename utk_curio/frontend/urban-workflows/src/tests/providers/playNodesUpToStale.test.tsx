/**
 * `playNodesUpTo` must re-run an ancestor whose code changed since it ran.
 *
 * The bug this pins: the ancestor filter asked only whether a node's *last run*
 * succeeded. Edit an upstream node's code, press play on a downstream one, and
 * the upstream was skipped — so the downstream node consumed the artifact the
 * pre-edit code had produced and reported success. For a tool built around
 * provenance, that attributes a result to source which can no longer produce it.
 *
 * `executedCode` (mirrored onto node data by useNodeState whenever a run
 * succeeds) is the source that produced the current output, so comparing it
 * against `data.code` distinguishes a valid cache from a stale one.
 *
 * Drives the real FlowProvider, mirroring src/tests/providers/playAllFlakiness.test.tsx.
 */
import React from 'react';
import { render, act } from '@testing-library/react';
import { Position, ReactFlow, ReactFlowProvider } from 'reactflow';
import { faCircle } from '@fortawesome/free-solid-svg-icons';

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

// FlowProvider -> ConnectionValidator -> registry -> vegaBehavior -> useVega
// pulls in vega (ESM). Stub it so the registry loads under jest.
jest.mock('../../hook/useVega', () => ({
  useVega: () => ({ handleCompileGrammar: jest.fn().mockResolvedValue(undefined) }),
}));
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });

import FlowProvider, { useFlowContext } from '../../providers/FlowProvider';
import { NodeType, SupportedType } from '../../constants';
import { registerNode } from '../../registry/nodeRegistry';
import type { NodeDescriptor } from '../../registry/types';

// The Data Pool as the shipped manifest declares its input (`[1,n]`), so it
// holds a value per circle and reads several as one bundle.
beforeAll(() => {
  const pool: NodeDescriptor = {
    id: 'curio.builtin/data-pool@1' as NodeType,
    category: 'data',
    label: 'Data Pool',
    icon: faCircle,
    inputPorts: [{ types: [SupportedType.DATAFRAME], cardinality: '[1,n]' }],
    outputPorts: [{ types: [SupportedType.DATAFRAME] }],
    editor: 'none',
    inPalette: true,
    description: '',
    hasCode: false,
    hasWidgets: false,
    hasGrammar: false,
    adapter: {
      handles: [
        { id: 'in', type: 'target', position: Position.Left },
        { id: 'out', type: 'source', position: Position.Right },
      ],
      editor: null,
      container: {},
      useNodeBehavior: () => ({}),
    },
  };
  registerNode(pool);
});

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

/** A node that has already run successfully, from the given source. */
function ranNode(id: string, code: string, executedCode: string = code) {
  return {
    id,
    type: 'curio.builtin/data-loading',
    position: { x: 0, y: 0 },
    data: {
      nodeId: id,
      nodeType: 'curio.builtin/data-loading',
      code,
      executedCode,
      output: { code: 'success', content: '' },
    },
  } as any;
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

/** Each edge is [source, target], into `in`, or [source, target, targetHandle]. */
async function seed(nodes: any[], edges: Array<[string, string, string?]>) {
  await act(async () => {
    nodes.forEach((n) => api.addNode(n, undefined, false));
  });
  await flush();
  for (const [source, target, targetHandle = 'in'] of edges) {
    await act(async () => {
      api.onEdgesChange([
        {
          type: 'add',
          item: { id: `${source}->${target}`, source, target, sourceHandle: 'out', targetHandle },
        } as any,
      ]);
    });
    await flush();
  }
}

function triggerExecOf(id: string): number {
  const n = api.nodes.find((x: any) => x.id === id);
  return (n?.data?.triggerExec as number) ?? 0;
}

afterEach(() => {
  jest.clearAllMocks();
});

describe('playNodesUpTo — stale ancestors', () => {
  test('skips an ancestor whose code still matches what it ran', async () => {
    renderFlow();
    await flush();
    await seed([ranNode('A', 'return 1'), ranNode('B', 'return arg')], [['A', 'B']]);

    await act(async () => {
      api.playNodesUpTo('B');
    });
    await flush();

    // A is a valid cache: only the target runs, in level 0.
    expect(triggerExecOf('A')).toBe(0);
    expect(triggerExecOf('B')).toBe(1);
  });

  test('re-runs an ancestor whose code changed since it ran', async () => {
    renderFlow();
    await flush();
    await seed(
      [ranNode('A', 'return 2', 'return 1'), ranNode('B', 'return arg')],
      [['A', 'B']],
    );

    await act(async () => {
      api.playNodesUpTo('B');
    });
    await flush();

    // A is stale, so it leads the run and B waits for it.
    expect(triggerExecOf('A')).toBe(1);
    expect(triggerExecOf('B')).toBe(0);
  });

  test('invalidation is transitive through a clean intermediate node', async () => {
    renderFlow();
    await flush();
    await seed(
      [
        ranNode('A', 'return 2', 'return 1'), // edited
        ranNode('B', 'return arg'), // clean, but fed by A
        ranNode('C', 'return arg'), // the target
      ],
      [
        ['A', 'B'],
        ['B', 'C'],
      ],
    );

    await act(async () => {
      api.playNodesUpTo('C');
    });
    await flush();

    // B must not be skipped: it would hand C the artifact it produced from A's
    // old output while A recomputes a new one.
    expect(triggerExecOf('A')).toBe(1);
    expect(triggerExecOf('B')).toBe(0);
    expect(triggerExecOf('C')).toBe(0);

    await act(async () => {
      api.signalNodeExecDone('A');
    });
    await flush();
    expect(triggerExecOf('B')).toBe(1);
  });

  test('a second play while one is running is ignored', async () => {
    renderFlow();
    await flush();
    await seed([ranNode('A', 'return 2', 'return 1'), ranNode('B', 'return arg')], [['A', 'B']]);

    await act(async () => {
      api.playNodesUpTo('B');
      api.playNodesUpTo('B');
    });
    await flush();

    // Without the re-entrancy guard the second call reset the run state and
    // orphaned the level already in flight.
    expect(triggerExecOf('A')).toBe(1);
  });
});

/**
 * A node that emits through applyNewOutput and never writes a success of its
 * own on node.data.output, as the Data Pool does. Fed through two circles, it
 * holds A's and A2's values and reads them as one bundle, as a delivery leaves
 * it.
 */
function emitterNode(id: string, type: string, circles: number) {
  const a1 = { path: 'a-1', dataType: 'dataframe' };
  const fanIn = circles > 1
    ? {
        inputSlots: [a1, { path: 'a2-1', dataType: 'dataframe' }],
        sourceSlots: ['A', 'A2'],
        input: { dataType: 'outputs', data: [a1, { path: 'a2-1', dataType: 'dataframe' }] },
      }
    : { input: a1 };
  return {
    id,
    type,
    position: { x: 0, y: 0 },
    data: { nodeId: id, nodeType: type, ...fanIn, output: { code: '', content: '' } },
  } as any;
}

describe('playNodesUpTo: Data Pool, alone and fed through several circles (#479)', () => {
  const kinds: Array<[string, string, number]> = [
    ['a Data Pool fed through two circles', 'curio.builtin/data-pool@1', 2],
    ['a Data Pool', 'curio.builtin/data-pool', 1],
  ];

  async function seedChain(type: string, circles: number) {
    renderFlow();
    await flush();
    const fanIn = circles > 1;
    await seed(
      [
        ranNode('A', 'return 1'),
        ...(fanIn ? [ranNode('A2', 'return 2')] : []),
        emitterNode('M', type, circles),
        ranNode('B', 'return arg'),
      ],
      [
        ['A', 'M', 'in'],
        ...(fanIn ? [['A2', 'M', 'in_1'] as [string, string, string]] : []),
        ['M', 'B'],
      ],
    );
  }

  async function emit(nodeId: string, path: string) {
    await act(async () => {
      api.applyNewOutput({ nodeId, output: { path, dataType: 'dataframe' } } as any);
    });
    await flush();
  }

  async function play(target: string) {
    await act(async () => {
      api.playNodesUpTo(target);
    });
    await flush();
  }

  test.each(kinds)('%s that emitted for the input it still has is not run again', async (_label, type, circles) => {
    await seedChain(type, circles);
    await emit('M', 'm-1');

    await play('B');

    // It used to count as never having succeeded, so every Play below it re-ran
    // it and handed the nodes after it a new input.
    expect(triggerExecOf('M')).toBe(0);
    expect(triggerExecOf('B')).toBe(1);
  });

  test.each(kinds)('%s runs again once a new input has reached it', async (_label, type, circles) => {
    await seedChain(type, circles);
    await emit('M', 'm-1');
    await emit('A', 'a-2'); // A ran again since, and delivered to M

    // A new value, not an emptied one: with two circles M now reads a new
    // bundle holding a-2 and A2's value.
    const input = api.nodes.find((x: any) => x.id === 'M')?.data?.input;
    expect(circles > 1 ? input?.data?.[0] : input).toMatchObject({ path: 'a-2' });
    if (circles > 1) expect(input?.data?.[1]).toMatchObject({ path: 'a2-1' });

    await play('B');

    expect(triggerExecOf('M')).toBe(1);
    expect(triggerExecOf('B')).toBe(0);
  });

  test.each(kinds)('%s that never emitted runs', async (_label, type, circles) => {
    await seedChain(type, circles);

    await play('B');

    expect(triggerExecOf('M')).toBe(1);
  });
});
