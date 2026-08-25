/**
 * Regression tests for dev/64: versioned dispatcher ids
 * (`curio.builtin/merge-flow@1`) broke every `NodeType` enum comparison in
 * FlowProvider, so `propagateDownstreamInputs` treated merge nodes as ordinary
 * nodes — each upstream completion OVERWROTE the merge's whole `data.input`
 * with a scalar payload instead of filling its positional `in_N` slot, the
 * behavior hook never saw an array, and the merge never emitted. Downstream
 * nodes then ran with `arg = None` (the sandbox tripwire error) forever.
 *
 * Drives the REAL FlowProvider (applyNewOutput → propagateDownstreamInputs)
 * with the same minimal <ReactFlow> bridge as playAllFlakiness.test.tsx.
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

describe('merge-flow input propagation with versioned dispatcher ids (dev/64)', () => {
  test('upstream outputs fill positional slots instead of overwriting data.input', async () => {
    renderFlow();
    await flush();
    await addNodes([
      makeNode('heat', 'curio.builtin/data-loading@1'),
      makeNode('social', 'curio.builtin/data-loading@1'),
      makeNode('merge', 'curio.builtin/merge-flow@1'),
    ]);
    await addEdge('heat', 'merge', 'in_0');
    await addEdge('social', 'merge', 'in_1');

    await act(async () => {
      api.applyNewOutput({
        nodeId: 'heat',
        output: { path: 'artifact-heat', dataType: 'geodataframe' },
      } as any);
    });
    await flush();

    let input = dataOf('merge').input;
    expect(Array.isArray(input)).toBe(true); // scalar overwrite = the dev/64 bug
    expect(input[0]).toMatchObject({ path: 'artifact-heat' });
    expect(input[1]).toBeUndefined();

    await act(async () => {
      api.applyNewOutput({
        nodeId: 'social',
        output: { path: 'artifact-social', dataType: 'geodataframe' },
      } as any);
    });
    await flush();

    input = dataOf('merge').input;
    expect(input[0]).toMatchObject({ path: 'artifact-heat' }); // slot 0 untouched
    expect(input[1]).toMatchObject({ path: 'artifact-social' });
  });

  test('a source wired to two slots fills both', async () => {
    renderFlow();
    await flush();
    await addNodes([
      makeNode('solo', 'curio.builtin/data-loading@1'),
      makeNode('merge', 'curio.builtin/merge-flow@1'),
    ]);
    await addEdge('solo', 'merge', 'in_0');
    await addEdge('solo', 'merge', 'in_2');

    await act(async () => {
      api.applyNewOutput({
        nodeId: 'solo',
        output: { path: 'artifact-solo', dataType: 'dataframe' },
      } as any);
    });
    await flush();

    const input = dataOf('merge').input;
    expect(input[0]).toMatchObject({ path: 'artifact-solo' });
    expect(input[1]).toBeUndefined();
    expect(input[2]).toMatchObject({ path: 'artifact-solo' });
  });

  test('load-time handle resolution sees the accumulating edge list (loadParsedTrill contract)', async () => {
    renderFlow();
    await flush();
    await addNodes([
      makeNode('loader1', 'curio.builtin/data-loading@1'),
      makeNode('loader2', 'curio.builtin/data-loading@1'),
      makeNode('merge', 'curio.builtin/merge-flow@1'),
    ]);

    // Mirror the loadParsedTrill loop: sequential onConnect calls sharing an
    // accumulating custom_edges array (skipValidation=true, like a spec load).
    const explicit = {
      id: 'reactflow__edge-loader1out-mergein_0',
      source: 'loader1',
      sourceHandle: 'out',
      target: 'merge',
      targetHandle: 'in_0',
    };
    // A legacy agent-built edge: UUID id, no persisted handle → loadTrill
    // falls back to targetHandle "in", which the merge must re-resolve.
    const legacy = {
      id: 'b1433343-ee39-4d94-b927-d55e5bb6579d',
      source: 'loader2',
      sourceHandle: 'out',
      target: 'merge',
      targetHandle: 'in',
    };

    const connectedSoFar: any[] = [];
    await act(async () => {
      api.onConnect(explicit as any, api.nodes, connectedSoFar, undefined, false, true);
      connectedSoFar.push(explicit);
    });
    await flush();
    await act(async () => {
      api.onConnect(legacy as any, api.nodes, connectedSoFar, undefined, false, true);
      connectedSoFar.push(legacy);
    });
    await flush();

    const handles = api.edges
      .filter((e: any) => e.target === 'merge')
      .map((e: any) => e.targetHandle)
      .sort();
    // With the old `custom_edges ? …` truthiness guard, loadParsedTrill's
    // empty-per-call list made the legacy edge land on the occupied in_0.
    expect(handles).toEqual(['in_0', 'in_1']);
  });

  test('an empty custom_edges array means "no edges yet", not "read the live store"', async () => {
    renderFlow();
    await flush();
    await addNodes([
      makeNode('loader1', 'curio.builtin/data-loading@1'),
      makeNode('merge', 'curio.builtin/merge-flow@1'),
    ]);

    const legacy = {
      id: '25063d34-45da-41cb-a97c-1e4f15a0f96c',
      source: 'loader1',
      sourceHandle: 'out',
      target: 'merge',
      targetHandle: 'in',
    };
    await act(async () => {
      api.onConnect(legacy as any, api.nodes, [], undefined, false, true);
    });
    await flush();

    const edge = api.edges.find((e: any) => e.target === 'merge');
    expect(edge?.targetHandle).toBe('in_0');
  });

  test('hydrateRestoredOutputs refills merge slots from project-load outputs', async () => {
    renderFlow();
    await flush();
    await addNodes([
      makeNode('heat', 'curio.builtin/data-loading@1'),
      makeNode('social', 'curio.builtin/data-loading@1'),
      makeNode('merge', 'curio.builtin/merge-flow@1'),
    ]);
    await addEdge('heat', 'merge', 'in_0');
    await addEdge('social', 'merge', 'in_1');

    // What ProjectLoader passes after a reload: filename refs, nothing executed.
    await act(async () => {
      api.hydrateRestoredOutputs([
        { nodeId: 'heat', output: '111_aaa_output.parquet' },
        { nodeId: 'social', output: '222_bbb_output.parquet' },
      ] as any);
      await new Promise((r) => setTimeout(r, 5)); // hydration defers one tick
    });
    await flush();

    const input = dataOf('merge').input;
    expect(Array.isArray(input)).toBe(true);
    expect(input[0]).toMatchObject({ path: '111_aaa_output.parquet' });
    expect(input[1]).toMatchObject({ path: '222_bbb_output.parquet' });
  });

  test('the emitted merge bundle reaches the downstream node as an outputs payload', async () => {
    renderFlow();
    await flush();
    await addNodes([
      makeNode('merge', 'curio.builtin/merge-flow@1'),
      makeNode('compute', 'curio.builtin/computation-analysis@1'),
    ]);
    await addEdge('merge', 'compute', 'in');

    // What useMergeFlowBehavior emits once every wired slot is filled.
    await act(async () => {
      api.applyNewOutput({
        nodeId: 'merge',
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

    const input = dataOf('compute').input;
    expect(input).toMatchObject({ dataType: 'outputs' });
    expect(input.data).toHaveLength(2);
    expect(input.data[0]).toMatchObject({ path: 'artifact-heat' });
  });
});
