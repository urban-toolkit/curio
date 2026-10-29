/**
 * The notebook view never changes what a dataflow saves.
 *
 * It shows the canvas's own nodes as a column of cells by moving them, the way
 * the dashboard page does: each node's canvas spot is stamped into
 * `data.workflowPosition`, which a save writes instead of `position`
 * (providers/flow/useNotebookView). These tests drive the REAL FlowProvider
 * and React Flow and read what a save would write, `TrillGenerator.generateTrill`
 * over React Flow's store, which is also what a provenance version records
 * (`addNewVersionProvenance` calls it). Harness as in collabInteractions.test.tsx,
 * inside a BrowserRouter as the app renders it, so the address the view keeps is
 * the router's.
 */
import React from 'react';
import { render, act } from '@testing-library/react';
import { ReactFlow, ReactFlowProvider, useReactFlow } from 'reactflow';
import { BrowserRouter, useLocation, useNavigate } from 'react-router-dom';

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
// The dataflow the canvas loaded, which a canvas bound to its doc binds on:
// none unless a test binds the canvas.
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

jest.mock('../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));

// The room's events, by name: `onRemote` registers a handler here. A
// collaborator's nodes and edges arrive through the dataflow's doc
// (`fromAnotherTab`).
const mockHandlers: Record<string, (payload: any) => void> = {};
const mockNoop = () => undefined;
const mockCollab = {
  lockedNodes: {},
  lockNode: mockNoop,
  unlockNode: mockNoop,
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
import { NOTEBOOK_CELL_GAP } from '../../utils/notebookLayout';

type XY = { x: number; y: number };

let api: ReturnType<typeof useFlowContext>;
let rf: ReturnType<typeof useReactFlow>;
let notebook: ReturnType<typeof useNotebookViewContext>;
let nextFreeSpot: () => XY;
let navigate: ReturnType<typeof useNavigate>;
/** The address's query as the router holds it. */
let routerSearch = '';

const Bridge: React.FC = () => {
  api = useFlowContext();
  rf = useReactFlow();
  notebook = useNotebookViewContext();
  nextFreeSpot = usePosition().getPosition;
  navigate = useNavigate();
  routerSearch = useLocation().search;
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

const PROJECT = 'project-notebook';
/** The dataflow's doc, as the server and every other tab hold it, when a test
 *  binds the canvas. */
let held: any = null;

/** The dataflow's doc and its mapping, required by the tests that bind the
 *  canvas, the others needing neither. */
function docModules() {
  return {
    ...require('../../providers/collab/docContext'),
    ...require('../../providers/collab/docProvider'),
    ...require('../../providers/collab/docMapping'),
  };
}

function renderFlow(dashboardOn = false) {
  const flow = (
    <BrowserRouter>
      <ReactFlowProvider>
        <FlowProvider dashboardOn={dashboardOn}>
          <Bridge />
        </FlowProvider>
      </ReactFlowProvider>
    </BrowserRouter>
  );
  if (!held) return render(flow);
  const { DataflowDocContext } = docModules();
  return render(
    <DataflowDocContext.Provider value={{ provider: held, synced: true }}>{flow}</DataflowDocContext.Provider>,
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

const NODE_TYPE = 'curio.builtin/computation-analysis';

function canvasNode(id: string, position: XY, extra: Record<string, unknown> = {}) {
  return {
    id,
    type: CURIO_UNIVERSAL_NODE_TYPE,
    position,
    data: { nodeId: id, nodeType: NODE_TYPE, input: '', inputTypes: [], ...extra },
  };
}

/** Put nodes on the canvas, as a drop does. */
async function addNodes(entries: Array<[string, XY, Record<string, unknown>?]>) {
  await act(async () => {
    for (const [id, position, extra] of entries) api.addNode(canvasNode(id, position, extra), undefined, false);
  });
  await flush();
}

/** Connect *source* to *target*, as a drag between their circles does. */
async function connect(id: string, source: string, target: string) {
  await act(async () => {
    api.onConnect({ id, source, target, sourceHandle: 'out', targetHandle: 'in' } as any,
      undefined, undefined, undefined, false, true);
  });
  await flush();
}

async function seedChain() {
  await addNodes(Object.entries(CANVAS).map(([id, position]) => [id, position] as [string, XY]));
  await connect('ab', 'a', 'b');
  await connect('bc', 'b', 'c');
}

/** The chain as the dataflow holds it: what a canvas bound to the doc loaded. */
function chainDataflow() {
  return {
    name: '',
    nodes: Object.entries(CANVAS).map(([id, p]) => ({ id, type: NODE_TYPE, x: p.x, y: p.y })),
    edges: [
      { id: 'ab', source: 'a', target: 'b', sourceHandle: 'out', targetHandle: 'in' },
      { id: 'bc', source: 'b', target: 'c', sourceHandle: 'out', targetHandle: 'in' },
    ],
  };
}

/** Bind the next canvas to the chain's doc, as the server synced it. */
function bindToDoc() {
  const { DataflowDocProvider, dataflowToDoc } = docModules();
  const dataflow = chainDataflow();
  held = new DataflowDocProvider(PROJECT, { canWrite: true });
  dataflowToDoc(dataflow, held.doc, 'doc-1');
  held.synced = true;
  mockLoaded.current = { epoch: 1, projectId: PROJECT, dataflow };
}

/** Another tab's change to the dataflow, as the provider applies one the
 *  server relays. */
async function fromAnotherTab(change: (dataflow: any) => void) {
  const { applyDataflow, docToDataflow } = docModules();
  const before = docToDataflow(held.doc);
  const after = JSON.parse(JSON.stringify(before));
  change(after);
  await act(async () => {
    held.doc.transact(() => applyDataflow(held.doc, before, after), held);
  });
  await flush();
}

/** Each node's place as the doc holds it, which every tab and the server read. */
function docSpots(): Record<string, XY> {
  const { docToDataflow } = docModules();
  return Object.fromEntries(docToDataflow(held.doc).nodes.map((n: any) => [n.id, { x: n.x, y: n.y }]));
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
  held?.destroy();
  held = null;
  mockLoaded.current = null;
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

    // As a rename or a widget edit would from a stale copy of data.
    await act(async () => {
      api.onNodesChange(
        rf.getNodes().map((n: any) => {
          const { workflowPosition, ...rest } = n.data;
          return { type: 'reset', item: { ...n, data: { ...rest, packageTemplateLabel: 'Renamed' } } };
        }) as any,
      );
    });
    await flush();

    expect(saved()).toEqual(CANVAS);
    expect(node('a').position.y).toBeLessThan(node('b').position.y);
  });

  test("a collaborator's drag during the notebook view lands on the canvas spot", async () => {
    bindToDoc();
    renderFlow();
    await flush();
    await seedChain();
    await setPane();
    await show('notebook');
    // The cells move the nodes on this canvas alone: the dataflow every tab
    // reads keeps the canvas spots.
    expect(docSpots()).toEqual(CANVAS);
    const cell = { ...node('b').position };

    await fromAnotherTab((df) => {
      const b = df.nodes.find((n: any) => n.id === 'b');
      b.x = 333;
      b.y = 777;
    });

    expect(node('b').position).toEqual(cell);
    expect(saved().b).toEqual({ x: 333, y: 777 });
    expect(docSpots()).toEqual({ ...CANVAS, b: { x: 333, y: 777 } });

    await show('canvas');
    expect(node('b').position).toEqual({ x: 333, y: 777 });
  });

  test('a node added in the notebook view keeps the canvas spot it was given, and a removed one is forgotten', async () => {
    bindToDoc();
    renderFlow();
    await flush();
    await seedChain();
    await setPane();
    await show('notebook');

    await fromAnotherTab((df) => {
      df.nodes.push({ id: 'd', type: NODE_TYPE, x: 2100, y: 300 });
    });
    expect(node('d').position.x).toBe(node('a').position.x);
    expect(saved().d).toEqual({ x: 2100, y: 300 });

    await fromAnotherTab((df) => {
      df.nodes = df.nodes.filter((n: any) => n.id !== 'a');
      df.edges = df.edges.filter((e: any) => e.source !== 'a' && e.target !== 'a');
    });
    await show('canvas');
    expect(node('a')).toBeUndefined();
    expect(node('b').position).toEqual(CANVAS.b);
    expect(node('c').position).toEqual(CANVAS.c);
    expect(node('d').position).toEqual({ x: 2100, y: 300 });
    expect(docSpots()).toEqual({ b: CANVAS.b, c: CANVAS.c, d: { x: 2100, y: 300 } });
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
    expect(top('b') - top('a')).toBe(180 + NOTEBOOK_CELL_GAP);
    expect(top('c') - top('b')).toBe(300 + NOTEBOOK_CELL_GAP);
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
    await addNodes(Object.entries(CANVAS).map(([id, position]) => [id, position, { nodeWidth: 525, nodeHeight: 350 }]));
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

  test("the view is in the router's address, and a navigation that keeps the dataflow open keeps it there", async () => {
    window.history.replaceState(null, '', '/dataflow/new');
    renderFlow();
    await flush();
    await seedChain();
    await setPane();
    await show('notebook');

    // The router holds the address the view wrote, as it holds every other.
    expect(routerSearch).toContain('view=notebook');

    // The first save of a new dataflow moves the page to the dataflow's own
    // address (UpMenu's save, ProjectLoader), a navigation that names no view.
    // The view stays on, and the new address says so.
    await act(async () => {
      navigate('/dataflow/abc', { replace: true });
    });
    await flush();
    expect(window.location.pathname).toBe('/dataflow/abc');
    expect(window.location.search).toContain('view=notebook');
    expect(routerSearch).toContain('view=notebook');
    expect(api.canvasView).toBe('notebook');
  });

  test('a switch made while the router has yet to render a navigation keeps the new address', async () => {
    window.history.replaceState(null, '', '/dataflow/new');
    renderFlow();
    await flush();
    await seedChain();
    await setPane();
    await show('notebook');

    // The router renders a navigation in a transition, so a switch made in
    // between renders first, while the router still holds the old address.
    await act(async () => {
      navigate('/dataflow/abc', { replace: true });
      api.setCanvasView('canvas');
    });
    await flush();
    expect(window.location.pathname).toBe('/dataflow/abc');
    expect(window.location.search).not.toContain('view=');
    expect(api.canvasView).toBe('canvas');
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

/**
 * Leaving the notebook view brings back the canvas view it was entered from,
 * at once (#996). React Flow 11's `setViewport` moves the view through a d3
 * transition, which lands only on a later animation frame, and the canvas
 * view came back that way, so on a page that drew no frame for a while React
 * Flow still read the notebook view's origin, zoom 1, after the switch. A
 * move asked that way and still waiting for its frame must not land over the
 * view brought back either. React Flow and d3 are real here: nothing yields
 * between the switch and the read, so no frame can come in between, and jsdom
 * draws frames once a test waits for them.
 */
describe('leaving the notebook view brings back the canvas view at once', () => {
  type View = { x: number; y: number; zoom: number };
  /** The canvas view the notebook view is entered from. */
  const LEFT_AT: View = { x: 255, y: 193, zoom: 0.75 };
  /** The view MainCanvas holds React Flow at in the notebook view. */
  const ORIGIN: View = { x: 0, y: 0, zoom: 1 };
  /** A view a fit moves React Flow to while the notebook view is on. */
  const MOVED: View = { x: -120, y: 40, zoom: 0.6 };

  /** Let *count* animation frames come, as a page that draws them does. */
  async function frames(count: number) {
    for (let i = 0; i < count; i += 1) {
      await act(async () => {
        await new Promise((resolve) => window.requestAnimationFrame(() => resolve(undefined)));
      });
    }
  }

  /** Set the view through React Flow's setViewport, a d3 transition, and let a frame land it. */
  async function landView(view: View) {
    act(() => {
      rf.setViewport(view);
    });
    await frames(2);
    expect(rf.getViewport()).toEqual(view);
  }

  async function enterFrom(view: View) {
    renderFlow();
    await flush();
    await seedChain();
    await setPane();
    await landView(view);
    await show('notebook');
  }

  test("the view it was left at is back before any frame, not the notebook view's origin", async () => {
    await enterFrom(LEFT_AT);
    // The notebook view's origin, where MainCanvas (not drawn here) holds React Flow.
    await landView(ORIGIN);

    act(() => {
      api.setCanvasView('canvas');
    });
    expect(rf.getViewport()).toEqual(LEFT_AT);

    await frames(2);
    expect(rf.getViewport()).toEqual(LEFT_AT);
  });

  test('a put-back of the origin still waiting for a frame does not undo the view brought back', async () => {
    await enterFrom(LEFT_AT);
    // A fit moved the view, and a put-back of the origin was asked through
    // React Flow's setViewport, as the hold made them before #996: it waits
    // for a frame that has not come.
    await landView(MOVED);
    act(() => {
      rf.setViewport(ORIGIN);
    });

    act(() => {
      api.setCanvasView('canvas');
    });
    expect(rf.getViewport()).toEqual(LEFT_AT);

    await frames(2);
    expect(rf.getViewport()).toEqual(LEFT_AT);
  });
});
