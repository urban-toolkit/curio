/**
 * Where a selection made in a view goes, through the REAL FlowProvider
 * routing (providers/flow/useInteractions.ts).
 *
 * Every view's selection is recorded, whatever its edges, and
 * applyNewInteractions, the one writer of a node's `data.interactions`, sends
 * it along each edge whose both handles are `in/out`: to a Data Pool, or to
 * the view at the other end, one hop. Two other paths reach views with no
 * interaction edge, by design: a Data Pool echoes the rows a selection flags
 * to every node it feeds on data edges, and a selection tag reads any view.
 *
 * A selection follows its edges as they change: removing an interaction edge,
 * or the node at one end, takes back what it delivered, a Data Pool's echo
 * included, and a new edge delivers the selection already made. An edge that
 * carries nothing, between two views that show no selection they receive, is
 * refused, and a data edge from a pool back into a chart linked to it is no
 * cycle, drawn or loaded: an interaction edge carries selections, never data.
 *
 * Harness as in growingInputPropagation.test.tsx. <ReactFlow> is wired as
 * MainCanvas wires it, so a delete takes the Delete key's path
 * (deleteElements). The templates are registered with the ports the shipped
 * manifest declares, so onConnect checks an edge as it does on the canvas.
 */
import fs from 'fs';
import path from 'path';
import React, { useCallback } from 'react';
import { render, act, waitFor } from '@testing-library/react';
import { Position, ReactFlow, ReactFlowProvider, useReactFlow } from 'reactflow';
import type { Connection, Node, NodeChange, ReactFlowInstance } from 'reactflow';
import { faCircle } from '@fortawesome/free-solid-svg-icons';

// jsdom polyfills ReactFlow needs.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(global as any).ResizeObserver = ResizeObserverStub;
if (!(global as any).DOMMatrixReadOnly) {
  (global as any).DOMMatrixReadOnly = class { m22 = 1; constructor() {} };
}

// Mocks: replace the heavy and IO collaborators, keep reactflow REAL.
jest.mock('../../hook/useWorkflowOperations', () => ({
  useWorkflowOperations: () => ({
    markNodeExecuted: jest.fn(),
    markNodeStale: jest.fn(),
    markDirty: jest.fn(),
    persistDataflowForInstall: jest.fn().mockResolvedValue(undefined),
    beginPendingInstall: jest.fn(),
    endPendingInstall: jest.fn(),
    applyRemoveChanges: jest.fn(),
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

// onConnect says why it refuses an edge in a toast: each test checks for none.
const mockShowToast = jest.fn();
jest.mock('../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));

jest.mock('../../providers/CollaborationProvider', () => ({
  useCollab: () => ({
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
import type { IPropagation } from '../../providers/flow/flowTypes';
import { CURIO_UNIVERSAL_NODE_TYPE, NodeType, VisInteractionType } from '../../constants';
import { registerNode } from '../../registry/nodeRegistry';
import type {
  NodeBehaviorData,
  NodeBehaviorResult,
  NodeDescriptor,
  UseNodeStateReturn,
} from '../../registry/types';
import { useDataPoolBehavior } from '../../adapters/node/dataPoolBehavior';
import { selectionViewsOf } from '../../hook/useSelectionViews';
import { isSelectionEcho, selectionEchoSource, type SelectionEchoOptions } from '../../utils/selectionEcho';
import { isActiveSelect, objectRows, type SelectDetail } from '../../utils/selectionMatch';
import {
  latestViewSelection,
  provideViewRows,
  resetViewSelections,
} from '../../utils/references/viewSelections';

const LOADER = 'curio.builtin/data-loading@1';
const POOL = 'curio.builtin/data-pool@1';
const VEGA = 'curio.builtin/vis-vega@1';
const SIMPLE = 'curio.builtin/vis-simple@1';
const PYTHON = 'curio.builtin/computation-analysis@1';

/** The built-in templates as packages/curio.builtin@1/manifest.json declares them. */
const SHIPPED_TEMPLATES: any[] = JSON.parse(
  fs.readFileSync(
    path.resolve(__dirname, '../../../../../../packages/curio.builtin@1/manifest.json'),
    'utf8',
  ),
).templates;

/** A built-in template with its shipped ports: onConnect checks an edge by
 * them, and a `[1,n]` input grows a circle per edge, as on the canvas. */
function shippedDescriptor(templateId: string): NodeDescriptor {
  const template = SHIPPED_TEMPLATES.find((t) => t.id === templateId);
  return {
    id: `curio.builtin/${templateId}@1`,
    category: template.category,
    label: template.label,
    icon: faCircle,
    inputPorts: template.inputPorts,
    outputPorts: template.outputPorts,
    editor: template.editor,
    behavior: template.behavior,
    inPalette: true,
    description: '',
    hasCode: template.hasCode,
    hasWidgets: template.hasWidgets,
    hasGrammar: template.hasGrammar,
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
}

beforeAll(() => {
  for (const templateId of ['data-loading', 'data-pool', 'vis-vega', 'vis-simple']) {
    registerNode(shippedDescriptor(templateId));
  }
});

type FlowApi = ReturnType<typeof useFlowContext>;
let api: FlowApi;
let canvas: ReactFlowInstance;

/** What each Data Pool's behavior returned last, by node id. */
const poolBehaviors: Record<string, NodeBehaviorResult> = {};

/** A Data Pool's real behavior, run on its node's data as UniversalNode runs
 * it (components/UniversalNode.tsx:130). It reads no node state. */
const PoolBehavior: React.FC<{ nodeId: string }> = ({ nodeId }) => {
  const { nodes } = useFlowContext();
  const pool = nodes.find((n) => n.id === nodeId) as Node;
  poolBehaviors[nodeId] = useDataPoolBehavior(pool.data as NodeBehaviorData, {} as UseNodeStateReturn);
  return null;
};

/** The canvas, wired as MainCanvas wires it (MainCanvas.tsx:584-606,
 * 620-623, 719-724): a node change goes to onNodesDelete and then to
 * onNodesChange, and the edges a delete takes go to onEdgesDelete. */
const Bridge: React.FC = () => {
  const ctx = useFlowContext();
  api = ctx;
  canvas = useReactFlow();
  const { onNodesDelete, onNodesChange } = ctx;
  const handleNodesChange = useCallback((changes: NodeChange[]) => {
    onNodesDelete(changes);
    onNodesChange(changes);
  }, [onNodesDelete, onNodesChange]);
  return (
    <div style={{ width: 800, height: 600 }}>
      <ReactFlow
        nodes={ctx.nodes}
        edges={ctx.edges}
        onNodesChange={handleNodesChange}
        onEdgesChange={ctx.onEdgesChange}
        onEdgesDelete={ctx.onEdgesDelete}
      />
      {ctx.nodes
        .filter((n) => n.data?.nodeType === POOL)
        .map((n) => <PoolBehavior key={n.id} nodeId={n.id} />)}
    </div>
  );
};

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

async function renderFlow() {
  render(
    <ReactFlowProvider>
      <FlowProvider>
        <Bridge />
      </FlowProvider>
    </ReactFlowProvider>,
  );
  await flush();
}

const dataOf = (id: string): any => api.nodes.find((n) => n.id === id)?.data;

/** A node as a palette drop builds one (hook/useCode.ts:496-498): the
 * universal React Flow type, the versioned template id, and the provider's
 * callbacks. */
function makeNode(id: string, nodeType: string, data: Record<string, unknown> = {}): Node {
  return {
    id,
    type: CURIO_UNIVERSAL_NODE_TYPE,
    position: { x: 0, y: 0 },
    data: {
      nodeId: id,
      nodeType,
      input: '',
      inputTypes: [],
      outputCallback: (nodeId: string, output: unknown, options?: SelectionEchoOptions) =>
        api.applyNewOutput({ nodeId, output, ...options }),
      interactionsCallback: (details: unknown, nodeId: string) => api.interactionsCallback(details, nodeId),
      propagationCallback: (propagation: IPropagation) => api.applyNewPropagation(propagation),
      ...data,
    },
  };
}

async function addNodes(...nodes: Node[]) {
  await act(async () => {
    nodes.forEach((n) => api.addNode(n, undefined, false));
  });
  await flush();
}

/** Draw an edge as on the canvas, where MainCanvas hands the connection to
 * onConnect (MainCanvas.tsx:610-613). A data edge goes from `out` to `in`; an
 * interaction edge joins the two `in/out` handles. */
async function draw(source: string, target: string, kind: 'data' | 'interaction') {
  const handles = kind === 'data'
    ? { sourceHandle: 'out', targetHandle: 'in' }
    : { sourceHandle: 'in/out', targetHandle: 'in/out' };
  await act(async () => {
    api.onConnect({ source, target, ...handles } as Connection);
  });
  await flush();
}

/** The edges on the canvas, as [source, target, kind]. */
const drawn = () =>
  api.edges.map((e) => [
    e.source,
    e.target,
    e.sourceHandle === 'in/out' && e.targetHandle === 'in/out' ? 'interaction' : 'data',
  ]);

/** The canvas holds exactly *edges*, and onConnect refused none. */
function expectDrawn(edges: string[][]) {
  expect(drawn()).toEqual(edges);
  expect(mockShowToast).not.toHaveBeenCalled();
}

/** A view reports a selection as a chart does (hook/useVega.ts:419), through
 * the callback its node data carries. */
async function select(viewId: string, details: Record<string, unknown>) {
  await act(async () => {
    dataOf(viewId).interactionsCallback(details, viewId);
  });
  await flush();
}

/** A Vega-Lite chart's click on *rows* (hook/useVega.ts:763-770). */
const pick = (rows: number[]) => ({
  pick: { type: VisInteractionType.POINT, data: rows, priority: 1, source: NodeType.VIS_VEGA },
});

/** A Simple View's click on a card (adapters/node/simpleVisBehavior.tsx:158-167). */
const cardClick = (row: number) => ({
  images_click: { type: VisInteractionType.POINT, data: [row], priority: 1, source: NodeType.VIS_SIMPLE },
});

/** The rows the selections *nodeId* holds from the view *viewId* pick: what
 * *nodeId* shows of that view's selection. None when it holds no selection
 * from that view, or only an empty one. */
function picksFrom(nodeId: string, viewId: string): number[] {
  const held: any[] = dataOf(nodeId)?.interactions ?? [];
  return held
    .filter((entry) => entry?.nodeId === viewId)
    .flatMap((entry) => Object.values(entry.details ?? {}) as SelectDetail[])
    .filter((detail) => isActiveSelect(detail))
    .flatMap((detail) => detail.data as number[]);
}

/** Every selection *nodeId* holds, from any view. */
const heldBy = (nodeId: string): unknown[] => dataOf(nodeId)?.interactions ?? [];

/** Three rows, as a node hands a dataframe on inline. */
const frame = () => ({
  dataType: 'dataframe',
  data: { osm_id: [101, 102, 103], height: [10, 30, 50] },
});

/** The `interacted` flag of each row of a node's input, as a Data Pool sets them. */
const flags = (nodeId: string) => Object.values(dataOf(nodeId)?.input?.data?.interacted ?? {});

/** What onConnect says when it refuses an interaction edge between two nodes
 * that show no selection they receive, such as two Simple Views. */
const CARRIES_NOTHING =
  'Neither node shows the selections it receives, so this interaction edge would carry nothing. ' +
  'Link one to a Data Pool and feed the other from the pool.';

/** An edge as a saved dataflow holds it. */
const saved = (id: string, source: string, target: string, kind: 'data' | 'interaction') =>
  kind === 'data'
    ? { id, source, target, sourceHandle: 'out', targetHandle: 'in' }
    : { id, source, target, sourceHandle: 'in/out', targetHandle: 'in/out', type: 'Interaction' };

/** Open a dataflow's edges as loadParsedTrill does (hook/useWorkflowOperations.ts:524-545):
 * each saved edge goes through onConnect, handed the edges replayed before it
 * and skipValidation, and then the selections the flow held are reset. */
async function load(edges: ReturnType<typeof saved>[]) {
  await act(async () => {
    const soFar: unknown[] = [];
    for (const edge of edges) {
      api.onConnect(edge as unknown as Connection, api.nodes, soFar, 'flow', false, true, true);
      soFar.push(edge);
    }
    api.setInteractions(() => []);
  });
  await flush();
}

/** Rows arrive at *loader*, and the Data Pool *pool* hands them on unflagged
 * before anyone selects: it takes a selection in only once it holds its rows
 * (dataPoolBehavior.tsx:153). */
async function rowsReachThePool(loader: string, pool: string, fedByPool: string) {
  await act(async () => {
    api.applyNewOutput({ nodeId: loader, output: frame() });
  });
  await waitFor(() => expect(poolBehaviors[pool]?.outputOverride?.content).toBeTruthy());
  await waitFor(() => expect(flags(fedByPool)).toEqual(['0', '0', '0']));
}

afterEach(() => {
  resetViewSelections();
  for (const id of Object.keys(poolBehaviors)) delete poolBehaviors[id];
  jest.clearAllMocks();
});

describe('a selection goes along interaction edges, one hop', () => {
  test('a selection in view A reaches view B, linked to A by an interaction edge', async () => {
    await renderFlow();
    await addNodes(makeNode('A', VEGA), makeNode('B', VEGA));
    await draw('A', 'B', 'interaction');
    expectDrawn([['A', 'B', 'interaction']]);

    await select('A', pick([1]));

    expect(picksFrom('B', 'A')).toEqual([1]);
  });

  test('a view with no interaction edge to A gets nothing', async () => {
    await renderFlow();
    await addNodes(makeNode('A', VEGA), makeNode('B', VEGA), makeNode('C', VEGA));
    await draw('A', 'B', 'interaction');
    expectDrawn([['A', 'B', 'interaction']]);

    await select('A', pick([1]));

    expect(picksFrom('B', 'A')).toEqual([1]);
    expect(heldBy('C')).toEqual([]);
  });

  test('a view fed by A on a data edge alone gets nothing', async () => {
    await renderFlow();
    await addNodes(makeNode('A', VEGA), makeNode('B', VEGA), makeNode('D', VEGA));
    await draw('A', 'D', 'data');
    await draw('A', 'B', 'interaction');
    expectDrawn([['A', 'D', 'data'], ['A', 'B', 'interaction']]);

    await select('A', pick([1]));

    expect(picksFrom('B', 'A')).toEqual([1]);
    expect(heldBy('D')).toEqual([]);
    // Nor rows: a chart hands its input on when it draws (hook/useVega.ts:847), not when it selects.
    expect(dataOf('D').input).toBe('');
  });

  test("with A linked to B and B linked to C, A's selection reaches B but not C", async () => {
    await renderFlow();
    await addNodes(makeNode('A', VEGA), makeNode('B', VEGA), makeNode('C', VEGA));
    await draw('A', 'B', 'interaction');
    await draw('B', 'C', 'interaction');
    expectDrawn([['A', 'B', 'interaction'], ['B', 'C', 'interaction']]);

    await select('A', pick([1]));

    expect(picksFrom('B', 'A')).toEqual([1]);
    expect(heldBy('C')).toEqual([]);
  });
});

describe('by design, a selection also reaches views with no interaction edge', () => {
  test("a view fed by a Data Pool on a data edge, with no interaction edge of its own, gets the pool's rows with A's picks flagged", async () => {
    await renderFlow();
    await addNodes(makeNode('rows', LOADER), makeNode('pool', POOL), makeNode('A', VEGA), makeNode('C', VEGA));
    await draw('rows', 'pool', 'data');
    await draw('pool', 'A', 'data');
    await draw('pool', 'C', 'data');
    await draw('A', 'pool', 'interaction');
    expectDrawn([
      ['rows', 'pool', 'data'],
      ['pool', 'A', 'data'],
      ['pool', 'C', 'data'],
      ['A', 'pool', 'interaction'],
    ]);

    // The rows arrive, and the pool hands them on unflagged before anyone selects:
    // it takes a selection in only once it holds its rows (dataPoolBehavior.tsx:153).
    await act(async () => {
      api.applyNewOutput({ nodeId: 'rows', output: frame() });
    });
    await waitFor(() => expect(poolBehaviors.pool?.outputOverride?.content).toBeTruthy());
    await waitFor(() => expect(flags('C')).toEqual(['0', '0', '0']));

    await select('A', pick([1]));

    // The pool echoes the rows A picked to every node it feeds on a data edge
    // (adapters/node/dataPoolBehavior.tsx:346, providers/flow/useGraphEdits.ts:122).
    await waitFor(() => expect(flags('C')).toEqual(['0', '1', '0']));
    expect(isSelectionEcho(dataOf('C').input)).toBe(true);
    expect(selectionEchoSource(dataOf('C').input)).toBe('A');
    // Routing gave C nothing: the flags are all it has.
    expect(heldBy('C')).toEqual([]);
  });

  test("a selection tag reads A's selection with no edge between them", async () => {
    await renderFlow();
    provideViewRows('A', () => ({
      rows: objectRows([{ osm_id: 101 }, { osm_id: 102 }, { osm_id: 103 }]),
      columns: ['osm_id'],
    }));
    await addNodes(
      makeNode('A', VEGA),
      makeNode('T', PYTHON, { selections: [{ name: 'picked', node: 'A', column: 'osm_id', ids: [] }] }),
    );
    expectDrawn([]);
    // The tag's picker offers every view, linked or not (hook/useSelectionViews.ts:30-33).
    expect(selectionViewsOf(api.nodes, 'T').map((view) => view.id)).toEqual(['A']);

    await select('A', pick([1]));

    // providers/flow/useSelectionTags.ts:91-122 writes the ids into every tag on A.
    await waitFor(() => expect(dataOf('T').selections[0].ids).toEqual([102]));
    expect(heldBy('T')).toEqual([]);
  });
});

// Removing an edge or a node takes back what the edge delivered, and a new
// edge delivers the selection its ends already hold. On main, a delete left
// the other node's data.interactions as they were
// (providers/flow/useGraphEdits.ts:291-373), and routing ran only when a
// selection changed (providers/flow/useInteractions.ts:205-207).
describe('a selection follows its edges as they change', () => {
  test("removing the interaction edge between A and B clears B's selection", async () => {
    await renderFlow();
    await addNodes(makeNode('A', VEGA), makeNode('B', VEGA));
    await draw('A', 'B', 'interaction');
    expectDrawn([['A', 'B', 'interaction']]);
    await select('A', pick([1]));
    expect(picksFrom('B', 'A')).toEqual([1]);

    const edgeId = api.edges[0].id;
    await act(async () => {
      canvas.deleteElements({ edges: [{ id: edgeId }] });
    });
    await flush();
    expect(drawn()).toEqual([]);

    expect(picksFrom('B', 'A')).toEqual([]);
  });

  test("deleting A clears B's selection", async () => {
    await renderFlow();
    await addNodes(makeNode('A', VEGA), makeNode('B', VEGA));
    await draw('A', 'B', 'interaction');
    expectDrawn([['A', 'B', 'interaction']]);
    await select('A', pick([1]));
    expect(picksFrom('B', 'A')).toEqual([1]);

    await act(async () => {
      canvas.deleteElements({ nodes: [{ id: 'A' }] });
    });
    await flush();
    expect(api.nodes.map((n) => n.id)).toEqual(['B']);
    expect(drawn()).toEqual([]);

    expect(picksFrom('B', 'A')).toEqual([]);
  });

  test('drawing an interaction edge from A to B after A selected gives B the current selection', async () => {
    await renderFlow();
    await addNodes(makeNode('A', VEGA), makeNode('B', VEGA));
    await select('A', pick([1]));
    // The flow holds A's selection when the edge is drawn.
    expect(latestViewSelection('A')).toEqual(pick([1]));
    expect(picksFrom('B', 'A')).toEqual([]);

    await draw('A', 'B', 'interaction');
    expectDrawn([['A', 'B', 'interaction']]);

    expect(picksFrom('B', 'A')).toEqual([1]);
  });

  test("drawing an interaction edge from A to B after B selected gives A B's selection", async () => {
    await renderFlow();
    await addNodes(makeNode('A', VEGA), makeNode('B', VEGA));
    await select('B', pick([2]));
    expect(picksFrom('A', 'B')).toEqual([]);

    await draw('A', 'B', 'interaction');
    expectDrawn([['A', 'B', 'interaction']]);

    expect(picksFrom('A', 'B')).toEqual([2]);
  });

  test("an edge drawn from A after A, then C, selected gives B A's selection", async () => {
    await renderFlow();
    await addNodes(makeNode('A', VEGA), makeNode('B', VEGA), makeNode('C', VEGA));
    await select('A', pick([1]));
    // C selected last, so A's is no longer the newest selection the flow holds.
    await select('C', pick([2]));

    await draw('A', 'B', 'interaction');
    expectDrawn([['A', 'B', 'interaction']]);

    expect(picksFrom('B', 'A')).toEqual([1]);
    expect(picksFrom('B', 'C')).toEqual([]);
  });

  test('guard: a dataflow opened after a selection was made gets nothing from it', async () => {
    await renderFlow();
    await addNodes(makeNode('A', VEGA), makeNode('B', VEGA));
    await select('A', pick([1]));

    await load([saved('link', 'A', 'B', 'interaction')]);
    expectDrawn([['A', 'B', 'interaction']]);

    expect(picksFrom('B', 'A')).toEqual([]);
  });

  test("removing the interaction edge between a chart and a Data Pool takes the chart's picks out of the rows the pool feeds", async () => {
    await renderFlow();
    await addNodes(makeNode('rows', LOADER), makeNode('pool', POOL), makeNode('A', VEGA), makeNode('C', VEGA));
    await draw('rows', 'pool', 'data');
    await draw('pool', 'A', 'data');
    await draw('pool', 'C', 'data');
    await draw('A', 'pool', 'interaction');
    await rowsReachThePool('rows', 'pool', 'C');
    await select('A', pick([1]));
    await waitFor(() => expect(flags('C')).toEqual(['0', '1', '0']));

    const link = api.edges.find((e) => e.sourceHandle === 'in/out')!.id;
    await act(async () => {
      canvas.deleteElements({ edges: [{ id: link }] });
    });
    await flush();
    expect(drawn()).toEqual([['rows', 'pool', 'data'], ['pool', 'A', 'data'], ['pool', 'C', 'data']]);

    await waitFor(() => expect(flags('C')).toEqual(['0', '0', '0']));
  });
});

describe('Simple Views', () => {
  // A Simple View marks only the rows whose `interacted` flag a Data Pool set
  // (adapters/node/simpleVisBehavior.tsx:169-174); it never reads data.interactions.
  test("a Simple View linked to a chart sends its clicks to the chart, and none of the Simple View's rows is flagged", async () => {
    await renderFlow();
    await addNodes(makeNode('rows', LOADER), makeNode('S', SIMPLE), makeNode('A', VEGA));
    await draw('rows', 'S', 'data');
    await draw('rows', 'A', 'data');
    await draw('S', 'A', 'interaction');
    expectDrawn([['rows', 'S', 'data'], ['rows', 'A', 'data'], ['S', 'A', 'interaction']]);
    await act(async () => {
      api.applyNewOutput({ nodeId: 'rows', output: frame() });
    });
    await flush();
    expect(dataOf('S').input).toEqual(frame());

    await select('S', cardClick(1));
    expect(picksFrom('A', 'S')).toEqual([1]);

    await select('A', pick([2]));
    expect(dataOf('S').input).toEqual(frame());
  });

  test('an interaction edge between two Simple Views is refused, saying why', async () => {
    await renderFlow();
    await addNodes(makeNode('S1', SIMPLE), makeNode('S2', SIMPLE));

    await draw('S1', 'S2', 'interaction');

    expect(drawn()).toEqual([]);
    expect(mockShowToast).toHaveBeenCalledWith(CARRIES_NOTHING, 'warning');
  });

  test('guard: a saved interaction edge between two Simple Views still opens, with no message', async () => {
    await renderFlow();
    await addNodes(makeNode('S1', SIMPLE), makeNode('S2', SIMPLE));

    await load([saved('link', 'S1', 'S2', 'interaction')]);

    expectDrawn([['S1', 'S2', 'interaction']]);
  });
});

// A data edge from a Data Pool into a chart linked to it is no cycle: an
// interaction edge carries selections, never data. On main the cycle check
// followed interaction edges too (providers/flow/useConnect.ts:86-88).
describe('a data edge from a pool into a chart linked to it', () => {
  test('a chart linked to a pool, then fed by it, keeps both edges', async () => {
    await renderFlow();
    await addNodes(makeNode('rows', LOADER), makeNode('pool', POOL), makeNode('A', VEGA));
    await draw('rows', 'pool', 'data');
    await draw('A', 'pool', 'interaction');

    await draw('pool', 'A', 'data');

    expectDrawn([['rows', 'pool', 'data'], ['A', 'pool', 'interaction'], ['pool', 'A', 'data']]);
  });

  test('guard: so does a chart whose interaction edge was drawn from the pool', async () => {
    await renderFlow();
    await addNodes(makeNode('rows', LOADER), makeNode('pool', POOL), makeNode('A', VEGA));
    await draw('rows', 'pool', 'data');
    await draw('pool', 'A', 'interaction');

    await draw('pool', 'A', 'data');

    expectDrawn([['rows', 'pool', 'data'], ['pool', 'A', 'interaction'], ['pool', 'A', 'data']]);
  });

  test('a saved dataflow that lists the interaction edge first keeps its data edge when it is opened', async () => {
    await renderFlow();
    await addNodes(makeNode('rows', LOADER), makeNode('pool', POOL), makeNode('A', VEGA));

    await load([
      saved('link', 'A', 'pool', 'interaction'),
      saved('feed', 'rows', 'pool', 'data'),
      saved('back', 'pool', 'A', 'data'),
    ]);

    expectDrawn([['A', 'pool', 'interaction'], ['rows', 'pool', 'data'], ['pool', 'A', 'data']]);
  });

  test('guard: a data edge that closes a loop of data edges is still refused', async () => {
    await renderFlow();
    await addNodes(makeNode('A', VEGA), makeNode('B', VEGA));
    await draw('A', 'B', 'data');

    await draw('B', 'A', 'data');

    expect(drawn()).toEqual([['A', 'B', 'data']]);
    expect(mockShowToast).toHaveBeenCalledWith('Cycles are not allowed in the dataflow', 'warning');
  });
});
