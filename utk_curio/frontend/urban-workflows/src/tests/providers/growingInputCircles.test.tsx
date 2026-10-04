/**
 * Several inputs on one node (#662): a template whose one input port takes
 * more than one edge grows a circle per edge. Each edge lands on the free
 * circle, the node reads its inputs as one value in circle order, and deleting
 * an edge closes the gap, renumbering the input chips in the node's code.
 *
 * Drives the REAL FlowProvider (`api.onConnect`, `api.applyNewOutput`,
 * `api.onEdgesDelete`) with the same minimal <ReactFlow> bridge as
 * connectionFanInGuard.test.tsx, over descriptors registered here with the
 * cardinalities the shipped manifest declares.
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

const mockBroadcastNodeUpdated = jest.fn();
const mockBroadcastEdgeAdded = jest.fn();
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
    broadcastNodeUpdated: mockBroadcastNodeUpdated,
    broadcastNodeRemoved: jest.fn(),
    broadcastEdgeAdded: mockBroadcastEdgeAdded,
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

jest.mock('../../ConnectionValidator', () => ({
  ConnectionValidator: { checkBoxCompatibility: () => true },
}));

import FlowProvider, { useFlowContext } from '../../providers/FlowProvider';
import { CURIO_UNIVERSAL_NODE_TYPE, NodeType, SupportedType } from '../../constants';
import { registerNode } from '../../registry/nodeRegistry';
import type { NodeDescriptor } from '../../registry/types';

function descriptor(id: string, inputCardinality: string | null): NodeDescriptor {
  return {
    id: id as NodeType,
    category: 'computation',
    label: id,
    icon: faCircle,
    inputPorts: inputCardinality === null ? [] : [{ types: [SupportedType.DATAFRAME], cardinality: inputCardinality }],
    outputPorts: [{ types: [SupportedType.DATAFRAME] }],
    editor: 'code',
    inPalette: true,
    description: '',
    hasCode: true,
    hasWidgets: false,
    hasGrammar: false,
    adapter: {
      handles: [
        ...(inputCardinality === null ? [] : [{ id: 'in', type: 'target' as const, position: Position.Left }]),
        { id: 'out', type: 'source', position: Position.Right },
      ],
      editor: { code: true, grammar: false, widgets: false },
      container: {},
      useNodeBehavior: () => ({}),
    },
  };
}

beforeAll(() => {
  registerNode(descriptor('curio.builtin/data-loading@1', null));
  registerNode(descriptor('curio.builtin/computation-analysis@1', '[1,n]'));
  registerNode(descriptor('curio.builtin/data-transformation@1', '[1,2]'));
  registerNode(descriptor('curio.builtin/data-summary@1', '1'));
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

function makeNode(id: string, nodeType: string, code = '') {
  return {
    id,
    type: CURIO_UNIVERSAL_NODE_TYPE,
    position: { x: 0, y: 0 },
    data: { nodeId: id, nodeType, input: '', inputTypes: [], code, defaultCode: code },
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

async function connect(source: string, target: string, targetHandle = 'in') {
  await act(async () => {
    api.onConnect(
      { source, target, sourceHandle: 'out', targetHandle } as any,
      undefined, undefined, undefined, false, false,
    );
  });
  await flush();
}

async function output(nodeId: string, path: string) {
  await act(async () => {
    api.applyNewOutput({ nodeId, output: { path, dataType: 'dataframe' } } as any);
  });
  await flush();
}

async function deleteEdges(ids: string[]) {
  const doomed = api.edges.filter((e: any) => ids.includes(e.id));
  await act(async () => {
    api.onEdgesDelete(doomed);
    api.onEdgesChange(doomed.map((e: any) => ({ type: 'remove', id: e.id })) as any);
  });
  await flush();
}

const handleOf = (source: string) => api.edges.find((e: any) => e.source === source)?.targetHandle;
const dataOf = (id: string): any => api.nodes.find((n: any) => n.id === id)?.data;

afterEach(() => {
  jest.clearAllMocks();
});

async function fanIn(target = 'curio.builtin/computation-analysis@1', code = '') {
  renderFlow();
  await flush();
  await addNodes([
    makeNode('a', 'curio.builtin/data-loading@1'),
    makeNode('b', 'curio.builtin/data-loading@1'),
    makeNode('c', 'curio.builtin/data-loading@1'),
    makeNode('t', target, code),
  ]);
}

describe('edges into a growing node', () => {
  test('each edge takes the next circle, even when dropped on a taken one', async () => {
    await fanIn();
    await connect('a', 't');
    await connect('b', 't', 'in');
    await connect('c', 't', 'in_1');
    expect([handleOf('a'), handleOf('b'), handleOf('c')]).toEqual(['in', 'in_1', 'in_2']);
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  test('past the maximum an edge is refused, naming it', async () => {
    await fanIn('curio.builtin/data-transformation@1');
    await connect('a', 't');
    await connect('b', 't');
    await connect('c', 't');
    expect(api.edges).toHaveLength(2);
    expect(mockShowToast).toHaveBeenCalledWith('This node takes at most 2 inputs.', 'warning');
  });

  test('a node with one input still refuses a second edge', async () => {
    await fanIn('curio.builtin/data-summary@1');
    await connect('a', 't');
    await connect('b', 't');
    expect(api.edges).toHaveLength(1);
  });

  test('two edges never share an id, even after circles closed up', async () => {
    await fanIn();
    await connect('a', 't');
    await connect('b', 't');
    await connect('c', 't');
    await deleteEdges([api.edges.find((e: any) => e.source === 'a')!.id]);
    // b now sits on `in` and c on `in_1`, but c's edge keeps the id it was
    // made with, which ends in in_2. A second edge from c lands on the free
    // circle `in_2` and would build that same id.
    await connect('c', 't');
    expect(api.edges).toHaveLength(3);
    const ids = api.edges.map((e: any) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe('what a growing node reads', () => {
  test('one input is the value itself; several are a bundle in circle order', async () => {
    await fanIn();
    await connect('b', 't');
    await output('b', 'artifact-b');
    expect(dataOf('t').input).toMatchObject({ path: 'artifact-b' });

    await connect('a', 't');
    expect(dataOf('t').input).toBe(''); // a has produced nothing yet
    await output('a', 'artifact-a');
    expect(dataOf('t').input).toMatchObject({
      dataType: 'outputs',
      data: [{ path: 'artifact-b' }, { path: 'artifact-a' }],
    });
  });
});

describe('deleting an edge closes the gap', () => {
  const CODE = 'x = [!! input 0 !!]\ny = [!! input 1.area !!]\nz = [!! input 2 !!]';

  test('later edges move up a circle, their values follow, and the chips are renumbered', async () => {
    await fanIn('curio.builtin/computation-analysis@1', CODE);
    await connect('a', 't');
    await connect('b', 't');
    await connect('c', 't');
    await output('a', 'artifact-a');
    await output('b', 'artifact-b');
    await output('c', 'artifact-c');

    await deleteEdges([api.edges.find((e: any) => e.source === 'b')!.id]);

    expect(api.edges).toHaveLength(2);
    expect([handleOf('a'), handleOf('c')]).toEqual(['in', 'in_1']);
    expect(dataOf('t').input).toMatchObject({
      dataType: 'outputs',
      data: [{ path: 'artifact-a' }, { path: 'artifact-c' }],
    });
    const rewritten = 'x = [!! input 0 !!]\ny = [!! input ?.area !!]\nz = [!! input 1 !!]';
    expect(dataOf('t').code).toBe(rewritten);
    expect(dataOf('t').defaultCode).toBe(rewritten);
    // Peers get the moved edge and the new code from here, once.
    expect(mockBroadcastEdgeAdded).toHaveBeenCalledWith(
      expect.objectContaining({ edge: expect.objectContaining({ source: 'c', targetHandle: 'in_1' }) }),
    );
    expect(mockBroadcastNodeUpdated).toHaveBeenCalledTimes(1);
  });

  test('deleting two edges at once keeps every chip on its input', async () => {
    await fanIn('curio.builtin/computation-analysis@1', CODE);
    await connect('a', 't');
    await connect('b', 't');
    await connect('c', 't');
    await deleteEdges(api.edges.filter((e: any) => e.source !== 'c').map((e: any) => e.id));
    expect(handleOf('c')).toBe('in');
    expect(dataOf('t').code).toBe('x = [!! input ? !!]\ny = [!! input ?.area !!]\nz = [!! input 0 !!]');
  });

  test('the last edge goes without rewriting code that names no later input', async () => {
    await fanIn('curio.builtin/computation-analysis@1', 'x = [!! input 0 !!]');
    await connect('a', 't');
    await connect('b', 't');
    await deleteEdges([api.edges.find((e: any) => e.source === 'b')!.id]);
    expect(dataOf('t').code).toBe('x = [!! input 0 !!]');
    expect(mockBroadcastNodeUpdated).not.toHaveBeenCalled();
  });
});
