/**
 * The notebook view never changes what a dataflow saves.
 *
 * It shows the canvas's own nodes as a column of cells by moving them, the way
 * the dashboard page does: each node's canvas spot is stamped into
 * `data.workflowPosition`, which a save writes instead of `position`
 * (providers/flow/useNotebookView). These tests drive the REAL FlowProvider
 * and React Flow and read what a save would write, `TrillGenerator.generateTrill`
 * over React Flow's store, which is also what a provenance version records
 * (`addNewVersionProvenance` calls it). Harness as in collabInteractions.test.tsx.
 */
import React from 'react';
import { render, act } from '@testing-library/react';
import { ReactFlow, ReactFlowProvider, useReactFlow } from 'reactflow';

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

// A collaborator's events, by name: `onRemote` registers a handler here and the
// test fires it as the socket would. Nodes and edges arrive this way too.
const mockHandlers: Record<string, (payload: any) => void> = {};
const mockNoop = () => undefined;
const mockCollab = {
  enabled: true,
  lockedNodes: {},
  currentUserId: null,
  lockNode: mockNoop,
  unlockNode: mockNoop,
  signalExecDisplay: mockNoop,
  broadcastOutputProduced: mockNoop,
  broadcastNodeAdded: mockNoop,
  broadcastNodeRemoved: mockNoop,
  broadcastNodeUpdated: mockNoop,
  broadcastEdgeAdded: mockNoop,
  broadcastEdgeRemoved: mockNoop,
  onRemote: (event: string, handler: (payload: any) => void) => {
    mockHandlers[event] = handler;
    return () => {
      if (mockHandlers[event] === handler) delete mockHandlers[event];
    };
  },
};
jest.mock('../../providers/CollaborationProvider', () => ({
  useCollab: () => mockCollab,
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
import { useNotebookViewContext } from '../../providers/flow/notebookViewContext';
import { usePosition } from '../../hook/usePosition';
import { TrillGenerator } from '../../TrillGenerator';
import { CURIO_UNIVERSAL_NODE_TYPE } from '../../constants';

type XY = { x: number; y: number };

let api: ReturnType<typeof useFlowContext>;
let rf: ReturnType<typeof useReactFlow>;
let notebook: ReturnType<typeof useNotebookViewContext>;
let nextFreeSpot: () => XY;

const Bridge: React.FC = () => {
  api = useFlowContext();
  rf = useReactFlow();
  notebook = useNotebookViewContext();
  nextFreeSpot = usePosition().getPosition;
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

function renderFlow(dashboardOn = false) {
  return render(
    <ReactFlowProvider>
      <FlowProvider dashboardOn={dashboardOn}>
        <Bridge />
      </FlowProvider>
    </ReactFlowProvider>,
  );
}

async function flush() {
  for (let i = 0; i < 3; i += 1) {
    await act(async () => {
      await Promise.resolve();
    });
  }
}

/** Where each node sits on the canvas: a chain a -> b -> c, laid out across. */
const CANVAS: Record<string, XY> = {
  a: { x: 0, y: 0 },
  b: { x: 700, y: 0 },
  c: { x: 1400, y: 300 },
};

function remoteNode(id: string, position: XY, extra: Record<string, unknown> = {}) {
  return {
    id,
    type: CURIO_UNIVERSAL_NODE_TYPE,
    position,
    data: { nodeId: id, nodeType: 'curio.builtin/computation-analysis', input: '', inputTypes: [], ...extra },
  };
}

async function fromPeer(event: string, payload: any) {
  expect(typeof mockHandlers[event]).toBe('function');
  await act(async () => {
    mockHandlers[event](payload);
  });
  await flush();
}

async function seedChain() {
  for (const [id, position] of Object.entries(CANVAS)) {
    await fromPeer('node_added', { node: remoteNode(id, position) });
  }
  await fromPeer('edge_added', { edge: { id: 'ab', source: 'a', target: 'b', sourceHandle: 'out', targetHandle: 'in' } });
  await fromPeer('edge_added', { edge: { id: 'bc', source: 'b', target: 'c', sourceHandle: 'out', targetHandle: 'in' } });
}

async function setPane() {
  await act(async () => {
    api.setNotebookPane({ width: 1600, top: 110, left: 56 });
  });
  await flush();
}

async function show(view: 'canvas' | 'notebook') {
  await act(async () => {
    api.setCanvasView(view);
  });
  await flush();
}

/** The x/y a save writes, read the way a save reads them: from React Flow's store. */
function saved(): Record<string, XY> {
  const spec: any = TrillGenerator.generateTrill(rf.getNodes(), rf.getEdges(), 'notebook view');
  return Object.fromEntries(spec.dataflow.nodes.map((n: any) => [n.id, { x: n.x, y: n.y }]));
}

/** The width and height a save writes for each node. */
function savedSizes(): Record<string, [number, number]> {
  const spec: any = TrillGenerator.generateTrill(rf.getNodes(), rf.getEdges(), 'notebook view');
  return Object.fromEntries(spec.dataflow.nodes.map((n: any) => [n.id, [n.width, n.height]]));
}

const node = (id: string) => api.nodes.find((n: any) => n.id === id) as any;

/** Cells as React Flow reports them once measured: 880 wide, these heights. */
async function measure(heights: Record<string, number>) {
  await act(async () => {
    api.onNodesChange(
      Object.entries(heights).map(([id, height]) => ({
        type: 'dimensions', id, dimensions: { width: 880, height },
      })) as any,
    );
  });
  await flush();
}

afterEach(() => {
  for (const key of Object.keys(mockHandlers)) delete mockHandlers[key];
  window.history.replaceState(null, '', '/');
});

describe('the notebook view shows the nodes as cells', () => {
  test('cells sit in one column in dataflow order, and a save writes the canvas spots', async () => {
    renderFlow();
    await flush();
    await seedChain();
    await setPane();
    await show('notebook');

    expect(api.canvasView).toBe('notebook');
    expect(api.notebookOn).toBe(true);
    expect(window.location.search).toContain('view=notebook');

    const [a, b, c] = ['a', 'b', 'c'].map((id) => node(id).position);
    expect(new Set([a.x, b.x, c.x]).size).toBe(1);
    expect(a.y).toBeLessThan(b.y);
    expect(b.y).toBeLessThan(c.y);

    for (const [id, spot] of Object.entries(CANVAS)) {
      expect(node(id).data.workflowPosition).toEqual(spot);
    }
    expect(saved()).toEqual(CANVAS);

    // Each connection has a lane in the bar, right of the cells.
    expect(notebook.on).toBe(true);
    expect(notebook.laneX.get('ab')).toBeGreaterThan(a.x);
    expect(notebook.laneX.get('bc')).toBeGreaterThan(a.x);
  });

  test('leaving puts every node back on its canvas spot and leaves no stamp', async () => {
    renderFlow();
    await flush();
    await seedChain();
    await setPane();
    await show('notebook');
    await show('canvas');

    expect(api.canvasView).toBe('canvas');
    expect(window.location.search).not.toContain('view=');
    for (const [id, spot] of Object.entries(CANVAS)) {
      expect(node(id).position).toEqual(spot);
      expect('workflowPosition' in node(id).data).toBe(false);
    }
    expect(saved()).toEqual(CANVAS);
  });

  test('a drag on the canvas after a round trip is what a save writes', async () => {
    renderFlow();
    await flush();
    await seedChain();
    await setPane();
    await show('notebook');
    await show('canvas');

    await act(async () => {
      api.onNodesChange([{ type: 'position', id: 'b', position: { x: 900, y: 450 } }]);
    });
    await flush();

    expect(saved().b).toEqual({ x: 900, y: 450 });
  });

  test("an update that rebuilt a node's data without its stamp is repaired before a save", async () => {
    renderFlow();
    await flush();
    await seedChain();
    await setPane();
    await show('notebook');

    // As a comment, a rename or a widget edit would from a stale copy of data.
    await act(async () => {
      api.onNodesChange(
        rf.getNodes().map((n: any) => {
          const { workflowPosition, ...rest } = n.data;
          return { type: 'reset', item: { ...n, data: { ...rest, comments: [] } } };
        }) as any,
      );
    });
    await flush();

    expect(saved()).toEqual(CANVAS);
    expect(node('a').position.y).toBeLessThan(node('b').position.y);
  });

  test("a collaborator's drag during the notebook view lands on the canvas spot", async () => {
    renderFlow();
    await flush();
    await seedChain();
    await setPane();
    await show('notebook');
    const cell = { ...node('b').position };

    await fromPeer('node_updated', { nodeId: 'b', patch: { position: { x: 333, y: 777 } } });

    expect(node('b').position).toEqual(cell);
    expect(saved().b).toEqual({ x: 333, y: 777 });

    await show('canvas');
    expect(node('b').position).toEqual({ x: 333, y: 777 });
  });

  test('a node added in the notebook view keeps the canvas spot it was given, and a removed one is forgotten', async () => {
    renderFlow();
    await flush();
    await seedChain();
    await setPane();
    await show('notebook');

    await fromPeer('node_added', { node: remoteNode('d', { x: 2100, y: 300 }) });
    expect(node('d').position.x).toBe(node('a').position.x);
    expect(saved().d).toEqual({ x: 2100, y: 300 });

    await fromPeer('node_removed', { nodeId: 'a' });
    await show('canvas');
    expect(node('a')).toBeUndefined();
    expect(node('b').position).toEqual(CANVAS.b);
    expect(node('c').position).toEqual(CANVAS.c);
    expect(node('d').position).toEqual({ x: 2100, y: 300 });
  });

  test('a cell that grows moves the cells below it by the same amount, and only those', async () => {
    renderFlow();
    await flush();
    await seedChain();
    await setPane();
    await show('notebook');

    // React Flow measures each cell and reports its size through onNodesChange.
    await measure({ a: 180, b: 300, c: 240 });
    const top = (id: string) => node(id).position.y;
    expect(top('b') - top('a')).toBe(180 + 16);
    expect(top('c') - top('b')).toBe(300 + 16);
    const before = { a: top('a'), b: top('b'), c: top('c') };
    const context = notebook;

    // A run fills b's output: b grows by 155px.
    await measure({ b: 455 });
    expect(top('a')).toBe(before.a);
    expect(top('b')).toBe(before.b);
    expect(top('c') - before.c).toBe(155);
    // The lanes depend on the rows, not on the heights: a cell that grows does
    // not hand every node and edge a new context, which would re-render them all.
    expect(notebook).toBe(context);
    expect(saved()).toEqual(CANVAS);
  });

  test("the round trip leaves the canvas positions and sizes, whatever the cells' heights", async () => {
    renderFlow();
    await flush();
    for (const [id, position] of Object.entries(CANVAS)) {
      await fromPeer('node_added', { node: remoteNode(id, position, { nodeWidth: 525, nodeHeight: 350 }) });
    }
    await setPane();
    await show('notebook');
    await measure({ a: 612, b: 95, c: 404 });
    await show('canvas');

    for (const [id, spot] of Object.entries(CANVAS)) {
      expect(node(id).position).toEqual(spot);
      expect([node(id).data.nodeWidth, node(id).data.nodeHeight]).toEqual([525, 350]);
    }
    expect(savedSizes()).toEqual({ a: [525, 350], b: [525, 350], c: [525, 350] });
  });

  test('the next free spot for a new node comes from canvas spots, not cells', async () => {
    renderFlow();
    await flush();
    await seedChain();
    const onCanvas = nextFreeSpot();
    await setPane();
    await show('notebook');

    expect(nextFreeSpot()).toEqual(onCanvas);
    expect(onCanvas).toEqual({ x: 1400 + 800, y: 300 });
  });

  test('an address with ?view=notebook opens the notebook view', async () => {
    window.history.replaceState(null, '', '/dataflow/x?view=notebook');
    renderFlow();
    await flush();
    await setPane();
    await seedChain();

    expect(api.canvasView).toBe('notebook');
    expect(node('a').position.y).toBeLessThan(node('b').position.y);
    expect(saved()).toEqual(CANVAS);
  });

  test('the dashboard page never shows the notebook view', async () => {
    window.history.replaceState(null, '', '/dashboard/x?view=notebook');
    renderFlow(true);
    await flush();
    await seedChain();
    await show('notebook');

    expect(api.canvasView).toBe('canvas');
    expect(api.notebookOn).toBe(false);
    expect(node('b').position).toEqual(CANVAS.b);
  });
});
