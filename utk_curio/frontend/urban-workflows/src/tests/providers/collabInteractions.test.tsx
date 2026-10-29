/**
 * #629: a selection made on a node that arrived from a collaborator reaches
 * the nodes linked to it, as it does on a node made in this tab.
 *
 * Drives the REAL FlowProvider bound to the dataflow's doc. Another tab adds a
 * chart, a Data Pool and the interaction edge between them through the doc;
 * the chart's `interactionsCallback` (the canvas's own, as the doc carries no
 * functions) then records a selection, which must land on the pool.
 * Harness as in connectionFanInGuard.test.tsx.
 */
import React from 'react';
import { render, act } from '@testing-library/react';
import { ReactFlow, ReactFlowProvider } from 'reactflow';

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
// The dataflow the canvas loaded, which the canvas binds to its doc on.
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

// The peer's events, by name. `onRemote` registers a handler here; the test
// fires them as the socket would.
const mockHandlers: Record<string, (payload: any) => void> = {};
const mockNoop = () => undefined;
// One object for every render: the receive effect depends on `onRemote`.
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
import { VisInteractionType } from '../../constants';

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

const PROJECT = 'project-interactions';
/** The dataflow's doc, as the server and every other tab hold it. */
let held: any = null;

/** The dataflow's doc and its mapping, required where a test binds the canvas. */
function docModules() {
  return {
    ...require('../../providers/collab/docContext'),
    ...require('../../providers/collab/docProvider'),
    ...require('../../providers/collab/docMapping'),
  };
}

/** A canvas bound to a doc the server synced, of an empty dataflow loaded as such. */
function renderBound() {
  const { DataflowDocContext, DataflowDocProvider, dataflowToDoc } = docModules();
  const dataflow = { name: '', nodes: [], edges: [] };
  held = new DataflowDocProvider(PROJECT, { canWrite: true });
  dataflowToDoc(dataflow, held.doc, 'doc-1');
  held.synced = true;
  mockLoaded.current = { epoch: 1, projectId: PROJECT, dataflow };
  return render(
    <DataflowDocContext.Provider value={{ provider: held, synced: true }}>
      <ReactFlowProvider>
        <FlowProvider>
          <Bridge />
        </FlowProvider>
      </ReactFlowProvider>
    </DataflowDocContext.Provider>,
  );
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
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

const nodeById = (id: string) => api.nodes.find((n: any) => n.id === id) as any;

afterEach(() => {
  for (const key of Object.keys(mockHandlers)) delete mockHandlers[key];
  held?.destroy();
  held = null;
  mockLoaded.current = null;
});

describe('collaboration: a selection on a received node reaches linked nodes (#629)', () => {
  test("a chart received from a peer sends its selection to the pool it is linked to", async () => {
    renderBound();
    await flush();

    await fromAnotherTab((df) => {
      df.nodes.push({ id: 'chart', type: 'curio.builtin/vis-vega@1', x: 0, y: 0 });
      df.nodes.push({ id: 'pool', type: 'curio.builtin/data-pool@1', x: 400, y: 0 });
      df.edges.push({ id: 'chart-pool', source: 'chart', target: 'pool', type: 'Interaction' });
    });

    expect(nodeById('chart')).toBeDefined();
    expect(nodeById('pool')).toBeDefined();
    expect(api.edges.map((e: any) => e.id)).toEqual(['chart-pool']);
    expect(typeof nodeById('chart').data.interactionsCallback).toBe('function');

    const details = { highlight: { type: VisInteractionType.POINT, data: [2], priority: 1 } };
    await act(async () => {
      nodeById('chart').data.interactionsCallback(details, 'chart');
    });
    await flush();

    expect(nodeById('pool').data.interactions).toEqual([
      expect.objectContaining({ nodeId: 'chart', details, priority: 1 }),
    ]);
  });
});
