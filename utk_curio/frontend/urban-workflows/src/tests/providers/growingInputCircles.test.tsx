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
// The dataflow the canvas loaded, which a canvas bound to its doc binds on
// (`useDataflowDoc`): none unless a test binds the canvas.
const mockLoaded: { current: any } = { current: null };
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
    loadedDataflowRef: mockLoaded,
    workflowGoalRef: { current: '' },
    workflowCategoriesRef: { current: {} },
    scenariosRef: { current: [] },
    autoRunRef: { current: false },
    takeDataflowFields: jest.fn(),
    quietly: (apply: () => unknown) => apply(),
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
import type { DataflowDocProvider } from '../../providers/collab/docProvider';
import { CURIO_UNIVERSAL_NODE_TYPE, NodeType, SupportedType } from '../../constants';
import { registerNode } from '../../registry/nodeRegistry';
import type { NodeDescriptor } from '../../registry/types';
import { resolveReferences } from '../../utils/references/codeReferences';

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

const PROJECT = 'project-fan-in';
/** The dataflow's doc, as every other tab reads it, when a test binds the canvas. */
let held: DataflowDocProvider | null = null;

/** The dataflow's doc and its mapping, required by the tests that bind the
 *  canvas, the others needing neither. */
function docModules() {
  return {
    ...require('../../providers/collab/docContext'),
    ...require('../../providers/collab/docProvider'),
    ...require('../../providers/collab/docMapping'),
  };
}

function renderFlow() {
  const flow = (
    <ReactFlowProvider>
      <FlowProvider>
        <Bridge />
      </FlowProvider>
    </ReactFlowProvider>
  );
  if (!held) return render(flow);
  const { DataflowDocContext } = docModules();
  return render(
    <DataflowDocContext.Provider value={{ provider: held, synced: true }}>{flow}</DataflowDocContext.Provider>,
  );
}

/** Bind the next canvas to a doc the server synced: an empty dataflow,
 *  loaded as such. */
function bindToDoc() {
  const { DataflowDocProvider: Provider, dataflowToDoc } = docModules();
  const dataflow = { name: '', nodes: [], edges: [] };
  held = new Provider(PROJECT, { canWrite: true }) as DataflowDocProvider;
  dataflowToDoc(dataflow, held.doc, 'doc-1');
  held.synced = true;
  mockLoaded.current = { epoch: 1, projectId: PROJECT, dataflow };
}

/** The dataflow as the doc holds it. */
function docDataflow(): any {
  return docModules().docToDataflow(held!.doc);
}

/** *nodeId*'s code in the doc. */
function docCode(nodeId: string): string | undefined {
  return docDataflow().nodes.find((n: any) => n.id === nodeId)?.content;
}

/** Each value *nodeId*'s code takes in the doc from now on, one per change. */
function watchDocCode(nodeId: string): string[] {
  const seen: string[] = [];
  let last = docCode(nodeId);
  held!.doc.on('afterTransaction', () => {
    const now = docCode(nodeId);
    if (now !== last) seen.push(now as string);
    last = now;
  });
  return seen;
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
  held?.destroy();
  held = null;
  mockLoaded.current = null;
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
  const CODE = 'x = [!! input_0 !!]\ny = [!! input_1.area !!]\nz = [!! input_2 !!]';

  test('later edges move up a circle, their values follow, and the chips are renumbered', async () => {
    bindToDoc();
    await fanIn('curio.builtin/computation-analysis@1', CODE);
    await connect('a', 't');
    await connect('b', 't');
    await connect('c', 't');
    await output('a', 'artifact-a');
    await output('b', 'artifact-b');
    await output('c', 'artifact-c');
    expect(docCode('t')).toBe(CODE);
    const codeChanges = watchDocCode('t');

    await deleteEdges([api.edges.find((e: any) => e.source === 'b')!.id]);

    expect(api.edges).toHaveLength(2);
    expect([handleOf('a'), handleOf('c')]).toEqual(['in', 'in_1']);
    expect(dataOf('t').input).toMatchObject({
      dataType: 'outputs',
      data: [{ path: 'artifact-a' }, { path: 'artifact-c' }],
    });
    const rewritten = 'x = [!! input_0 !!]\ny = [!! input_?.area !!]\nz = [!! input_1 !!]';
    expect(dataOf('t').code).toBe(rewritten);
    expect(dataOf('t').defaultCode).toBe(rewritten);
    // The other tabs get the moved edge and the new code from here, through
    // the dataflow's doc, the code in one change.
    const docEdges = docDataflow().edges;
    expect(docEdges.map((e: any) => [e.source, e.targetHandle]).sort()).toEqual([['a', 'in'], ['c', 'in_1']]);
    expect(codeChanges).toEqual([rewritten]);
  });

  test('deleting two edges at once keeps every chip on its input', async () => {
    await fanIn('curio.builtin/computation-analysis@1', CODE);
    await connect('a', 't');
    await connect('b', 't');
    await connect('c', 't');
    await deleteEdges(api.edges.filter((e: any) => e.source !== 'c').map((e: any) => e.id));
    expect(handleOf('c')).toBe('in');
    expect(dataOf('t').code).toBe('x = [!! input_? !!]\ny = [!! input_?.area !!]\nz = [!! input_0 !!]');
  });

  test('the last edge goes without rewriting code that names no later input', async () => {
    bindToDoc();
    await fanIn('curio.builtin/computation-analysis@1', 'x = [!! input_0 !!]');
    await connect('a', 't');
    await connect('b', 't');
    expect(docCode('t')).toBe('x = [!! input_0 !!]');
    const codeChanges = watchDocCode('t');
    await deleteEdges([api.edges.find((e: any) => e.source === 'b')!.id]);
    expect(dataOf('t').code).toBe('x = [!! input_0 !!]');
    // The other tabs get no change of the code.
    expect(codeChanges).toEqual([]);
    expect(docDataflow().edges.map((e: any) => e.source)).toEqual(['a']);
  });
});

describe('deleting an edge, with inputs read as input_k', () => {
  const scope = (slots: number[]) => ({ widgets: [], inputs: slots.map((slot) => ({ slot })) });

  test('later circles move up, and their chips and typed names follow', async () => {
    await fanIn(
      'curio.builtin/computation-analysis@1',
      'x = input_0\ny = [!! input_1.area !!] + input_1\nz = [!! input_2 !!]  # input_2',
    );
    await connect('a', 't');
    await connect('b', 't');
    await connect('c', 't');
    await deleteEdges([api.edges.find((e: any) => e.source === 'b')!.id]);
    expect([handleOf('a'), handleOf('c')]).toEqual(['in', 'in_1']);
    expect(dataOf('t').code).toBe('x = input_0\ny = [!! input_?.area !!] + [!! input_? !!]\nz = [!! input_1 !!]  # input_2');
  });

  test("a typed name inside an f-string's braces follows its circle, and the f-string's text stays", async () => {
    await fanIn('curio.builtin/computation-analysis@1', 'x = input_0\nmsg = f"input_2 has {len(input_2)} rows"');
    await connect('a', 't');
    await connect('b', 't');
    await connect('c', 't');
    await deleteEdges([api.edges.find((e: any) => e.source === 'b')!.id]);
    expect(dataOf('t').code).toBe('x = input_0\nmsg = f"input_2 has {len(input_1)} rows"');
  });

  test("a node's only edge goes without rewriting the input it names, so the next edge is read by it", async () => {
    const code = 'gdf = input_0.copy()\nx = [!! input_0 !!]';
    await fanIn('curio.builtin/computation-analysis@1', code);
    await connect('a', 't');
    await deleteEdges([api.edges.find((e: any) => e.source === 'a')!.id]);
    expect(dataOf('t').code).toBe(code);
    await connect('b', 't');
    expect(handleOf('b')).toBe('in');
    expect(dataOf('t').code).toBe(code);
    expect(resolveReferences(dataOf('t').code, scope([0]), 'python')).toEqual({
      code: 'gdf = input_0.copy()\nx = input_0',
      problems: [],
    });
  });

  test('the last of several edges goes without rewriting, so the next edge on its circle is read by it', async () => {
    const code = 'a = input_0\nb = [!! input_1 !!]';
    await fanIn('curio.builtin/computation-analysis@1', code);
    await connect('a', 't');
    await connect('b', 't');
    await deleteEdges([api.edges.find((e: any) => e.source === 'b')!.id]);
    expect(dataOf('t').code).toBe(code);
    await connect('c', 't');
    expect(handleOf('c')).toBe('in_1');
    expect(resolveReferences(dataOf('t').code, scope([0, 1]), 'python').code).toBe('a = input_0\nb = input_1');
  });
});
