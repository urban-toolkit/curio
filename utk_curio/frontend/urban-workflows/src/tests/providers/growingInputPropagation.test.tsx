/**
 * Several inputs reaching one node through its circles (#662), with the
 * versioned dispatcher ids a palette drag stores (dev/64:
 * `curio.builtin/computation-analysis@1`).
 *
 * A node whose one input port takes several edges holds a value per circle in
 * `data.inputSlots`, and reads them as one value in `data.input`: the value
 * itself for one circle, an `outputs` bundle in circle order for several, and
 * nothing while a wired circle is still empty. An upstream completion must
 * fill its own circle, never overwrite the whole input, or the node runs with
 * one input missing.
 *
 * Drives the REAL FlowProvider (applyNewOutput -> propagateDownstreamInputs,
 * onConnect, hydrateRestoredOutputs) with the same minimal <ReactFlow> bridge
 * as playAllFlakiness.test.tsx, over a descriptor registered here with the
 * cardinality the shipped manifest declares.
 */
import React from 'react';
import { render, act } from '@testing-library/react';
import { Position, ReactFlow, ReactFlowProvider } from 'reactflow';
import { faCircle } from '@fortawesome/free-solid-svg-icons';

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

import FlowProvider, { useFlowContext } from '../../providers/FlowProvider';
import { CURIO_UNIVERSAL_NODE_TYPE, NodeType, SupportedType } from '../../constants';
import { registerNode } from '../../registry/nodeRegistry';
import type { NodeDescriptor } from '../../registry/types';

/** Python Computation as the shipped manifest declares its input: `[1,n]`. */
const GROWING = 'curio.builtin/computation-analysis@1';

beforeAll(() => {
  const descriptor: NodeDescriptor = {
    id: GROWING as NodeType,
    category: 'computation',
    label: 'Python Computation',
    icon: faCircle,
    inputPorts: [{ types: [SupportedType.DATAFRAME], cardinality: '[1,n]' }],
    outputPorts: [{ types: [SupportedType.DATAFRAME] }],
    editor: 'code',
    inPalette: true,
    description: '',
    hasCode: true,
    hasWidgets: false,
    hasGrammar: false,
    adapter: {
      handles: [
        { id: 'in', type: 'target', position: Position.Left },
        { id: 'out', type: 'source', position: Position.Right },
      ],
      editor: { code: true, grammar: false, widgets: false },
      container: {},
      useNodeBehavior: () => ({}),
    },
  };
  registerNode(descriptor);
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

/** A node exactly as the palette/loadTrill create them post-`curio.builtin@1`:
 *  universal RF type + VERSIONED dispatcher id in data.nodeType. */
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

async function addEdge(source: string, target: string, targetHandle: string) {
  await act(async () => {
    api.onEdgesChange([
      {
        type: 'add',
        item: {
          id: `reactflow__edge-${source}out-${target}${targetHandle}`,
          source,
          target,
          sourceHandle: 'out',
          targetHandle,
        },
      } as any,
    ]);
  });
  await flush();
}

function dataOf(id: string): any {
  return api.nodes.find((x: any) => x.id === id)?.data;
}

afterEach(() => {
  jest.clearAllMocks();
});

describe('growing node input propagation with versioned dispatcher ids (dev/64)', () => {
  test('upstream outputs fill their own circles instead of overwriting data.input', async () => {
    renderFlow();
    await flush();
    await addNodes([
      makeNode('heat', 'curio.builtin/data-loading@1'),
      makeNode('social', 'curio.builtin/data-loading@1'),
      makeNode('t', GROWING),
    ]);
    await addEdge('heat', 't', 'in');
    await addEdge('social', 't', 'in_1');

    await act(async () => {
      api.applyNewOutput({
        nodeId: 'heat',
        output: { path: 'artifact-heat', dataType: 'geodataframe' },
      } as any);
    });
    await flush();

    let data = dataOf('t');
    expect(Array.isArray(data.inputSlots)).toBe(true);
    expect(data.inputSlots[0]).toMatchObject({ path: 'artifact-heat' });
    expect(data.inputSlots[1]).toBeUndefined();
    // Circle 1 is wired but empty: the node reads nothing yet. A scalar
    // overwrite (the dev/64 bug) would hand it heat alone as its whole input.
    expect(data.input).toBe('');

    await act(async () => {
      api.applyNewOutput({
        nodeId: 'social',
        output: { path: 'artifact-social', dataType: 'geodataframe' },
      } as any);
    });
    await flush();

    data = dataOf('t');
    expect(data.inputSlots[0]).toMatchObject({ path: 'artifact-heat' }); // circle 0 untouched
    expect(data.inputSlots[1]).toMatchObject({ path: 'artifact-social' });
    expect(data.input).toMatchObject({
      dataType: 'outputs',
      data: [{ path: 'artifact-heat' }, { path: 'artifact-social' }],
    });
  });

  test('a source wired to two circles fills both', async () => {
    renderFlow();
    await flush();
    await addNodes([
      makeNode('solo', 'curio.builtin/data-loading@1'),
      makeNode('t', GROWING),
    ]);
    await addEdge('solo', 't', 'in');
    await addEdge('solo', 't', 'in_1');

    await act(async () => {
      api.applyNewOutput({
        nodeId: 'solo',
        output: { path: 'artifact-solo', dataType: 'dataframe' },
      } as any);
    });
    await flush();

    const data = dataOf('t');
    expect(data.inputSlots[0]).toMatchObject({ path: 'artifact-solo' });
    expect(data.inputSlots[1]).toMatchObject({ path: 'artifact-solo' });
    expect(data.sourceSlots.slice(0, 2)).toEqual(['solo', 'solo']);
    expect(data.input).toMatchObject({
      dataType: 'outputs',
      data: [{ path: 'artifact-solo' }, { path: 'artifact-solo' }],
    });
  });

  test('a saved edge keeps the circle it names on load, even listed before a lower one (loadParsedTrill contract)', async () => {
    renderFlow();
    await flush();
    await addNodes([
      makeNode('loader1', 'curio.builtin/data-loading@1'),
      makeNode('loader2', 'curio.builtin/data-loading@1'),
      makeNode('t', GROWING),
    ]);

    // Mirror the loadParsedTrill loop: sequential onConnect calls sharing an
    // accumulating custom_edges array (skipValidation=true, like a spec load).
    // The spec lists circle 1 first; re-resolving it as a fresh drag would
    // move it onto the free `in` and swap the two inputs' order.
    const second = {
      id: 'reactflow__edge-loader1out-tin_1',
      source: 'loader1',
      sourceHandle: 'out',
      target: 't',
      targetHandle: 'in_1',
    };
    // An agent-built edge: UUID id, handle named explicitly.
    const first = {
      id: 'b1433343-ee39-4d94-b927-d55e5bb6579d',
      source: 'loader2',
      sourceHandle: 'out',
      target: 't',
      targetHandle: 'in',
    };

    const connectedSoFar: any[] = [];
    await act(async () => {
      api.onConnect(second as any, api.nodes, connectedSoFar, undefined, false, true);
      connectedSoFar.push(second);
    });
    await flush();
    await act(async () => {
      api.onConnect(first as any, api.nodes, connectedSoFar, undefined, false, true);
      connectedSoFar.push(first);
    });
    await flush();

    const handleOf = (source: string) =>
      api.edges.find((e: any) => e.source === source && e.target === 't')?.targetHandle;
    expect(api.edges.filter((e: any) => e.target === 't')).toHaveLength(2);
    expect([handleOf('loader2'), handleOf('loader1')]).toEqual(['in', 'in_1']);
  });

  test('an empty custom_edges array means "no edges yet", not "read the live store"', async () => {
    renderFlow();
    await flush();
    await addNodes([
      makeNode('a', 'curio.builtin/data-loading@1'),
      makeNode('t', GROWING),
    ]);
    // Right after a load the React Flow store is a render behind and can still
    // hold the replaced graph. Here it holds t -> a, which would make the saved
    // a -> t below look like a cycle if onConnect read the store.
    await addEdge('t', 'a', 'in');

    const saved = {
      id: '25063d34-45da-41cb-a97c-1e4f15a0f96c',
      source: 'a',
      sourceHandle: 'out',
      target: 't',
      targetHandle: 'in_1',
    };
    await act(async () => {
      api.onConnect(saved as any, api.nodes, [], undefined, false, true);
    });
    await flush();

    const edge = api.edges.find((e: any) => e.source === 'a' && e.target === 't');
    expect(edge?.targetHandle).toBe('in_1');
    expect(mockShowToast).not.toHaveBeenCalledWith('Cycles are not allowed in the dataflow', 'warning');
  });

  test('hydrateRestoredOutputs refills every circle from project-load outputs', async () => {
    renderFlow();
    await flush();
    await addNodes([
      makeNode('heat', 'curio.builtin/data-loading@1'),
      makeNode('social', 'curio.builtin/data-loading@1'),
      makeNode('t', GROWING),
    ]);
    await addEdge('heat', 't', 'in');
    await addEdge('social', 't', 'in_1');

    // What ProjectLoader passes after a reload: filename refs, nothing executed.
    await act(async () => {
      api.hydrateRestoredOutputs([
        { nodeId: 'heat', output: '111_aaa_output.parquet' },
        { nodeId: 'social', output: '222_bbb_output.parquet' },
      ] as any);
      await new Promise((r) => setTimeout(r, 5)); // hydration defers one tick
    });
    await flush();

    const data = dataOf('t');
    expect(Array.isArray(data.inputSlots)).toBe(true);
    expect(data.inputSlots[0]).toMatchObject({ path: '111_aaa_output.parquet' });
    expect(data.inputSlots[1]).toMatchObject({ path: '222_bbb_output.parquet' });
    expect(data.input).toMatchObject({
      dataType: 'outputs',
      data: [{ path: '111_aaa_output.parquet' }, { path: '222_bbb_output.parquet' }],
    });
  });

  test('an outputs bundle reaching one circle is that circle\'s whole value', async () => {
    renderFlow();
    await flush();
    await addNodes([
      makeNode('pool', 'curio.builtin/data-pool@1'),
      makeNode('t', GROWING),
    ]);
    await addEdge('pool', 't', 'in');

    // What a Data Pool fed through two circles emits: its inputs as one bundle.
    await act(async () => {
      api.applyNewOutput({
        nodeId: 'pool',
        output: {
          data: [
            { path: 'artifact-heat', dataType: 'geodataframe' },
            { path: 'artifact-social', dataType: 'geodataframe' },
          ],
          dataType: 'outputs',
        },
      } as any);
    });
    await flush();

    const data = dataOf('t');
    // The whole bundle sits in circle 0; it is not spread over the circles.
    expect(data.inputSlots[0]).toMatchObject({ dataType: 'outputs' });
    expect(data.inputSlots[0].data).toHaveLength(2);
    expect(data.inputSlots[1]).toBeUndefined();
    expect(data.input).toMatchObject({ dataType: 'outputs' });
    expect(data.input.data).toHaveLength(2);
    expect(data.input.data[0]).toMatchObject({ path: 'artifact-heat' });
  });
});
