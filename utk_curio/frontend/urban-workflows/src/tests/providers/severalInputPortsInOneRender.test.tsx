/**
 * A node with several input ports reads each input on its port's circle,
 * whatever order and render the inputs land in.
 *
 * The Spatial Join's two ports are input_0 (`in`) and input_1 (`in_1`). Its
 * body used to resolve each port's input itself; it is a code node now, and
 * its code reads `data.input` as any code node does. Example 10's Run All
 * e2e once lost one of a join's inputs when both landed in one render (the
 * Data Transformation's polygons 46 to 57 ms after the Image Segmentation's
 * points): `input` names only the latest arrival. So a node with several
 * ports keeps each port's input (`data.portInputs`) and reads them, port k on
 * circle k, as a growing node reads its circles (`nodeInputFromPorts`).
 *
 * Drives the REAL FlowProvider (applyNewOutput -> propagateDownstreamInputs,
 * hydrateRestoredOutputs, onEdgesDelete) and the real React Flow store. Two
 * outputs in one `act` are one render, as two outputs landing before React
 * renders are in the browser.
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
    recordOutputs: jest.fn().mockResolvedValue(undefined),
    beginPendingInstall: jest.fn(),
    endPendingInstall: jest.fn(),
    failPendingInstall: jest.fn(),
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
    lockedNodes: {},
    lockNode: jest.fn(),
    unlockNode: jest.fn(),
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
import { normalizeFlowInput } from '../../utils/flowOutputRef';

/** The Spatial Join's type: a code node with two input ports. */
const JOIN_TYPE = 'curio.builtin/spatial-join';

/** What a Simple View hands on: the Image Segmentation's artifact, as it received it. */
const POINTS_OUT = { path: 'photos-artifact', dataType: 'geodataframe' };
/** What the Python Computation's finished step hands on. */
const POLYGONS_OUT = { path: 'neighborhoods-artifact', dataType: 'geodataframe' };

beforeAll(() => {
  const descriptor: NodeDescriptor = {
    id: JOIN_TYPE as NodeType,
    category: 'data',
    label: 'Spatial Join',
    icon: faCircle,
    // As the shipped manifest declares them: input_0 and input_1, one edge each.
    inputPorts: [
      { types: [SupportedType.GEODATAFRAME], cardinality: '1' },
      { types: [SupportedType.GEODATAFRAME], cardinality: '1' },
    ],
    outputPorts: [{ types: [SupportedType.GEODATAFRAME] }],
    editor: 'code',
    inPalette: true,
    description: '',
    hasCode: true,
    hasWidgets: true,
    hasGrammar: false,
    adapter: {
      handles: [
        { id: 'in', type: 'target', position: Position.Left },
        { id: 'in_1', type: 'target', position: Position.Left },
        { id: 'out', type: 'source', position: Position.Right },
      ],
      editor: { code: true, grammar: false, widgets: true },
      container: {},
      useNodeBehavior: () => ({}),
    },
  };
  registerNode(descriptor);
});

type FlowApi = ReturnType<typeof useFlowContext>;
let api: FlowApi;

/** The data each rendered node last held, by node id. */
const seen = new Map<string, any>();

const ProbeNode: React.FC<{ data: any }> = ({ data }) => {
  seen.set(data.nodeId, data);
  return <div data-testid={`node-${data.nodeId}`} />;
};

const NODE_TYPES = { probe: ProbeNode };

const Bridge: React.FC = () => {
  const ctx = useFlowContext();
  api = ctx;
  return (
    <div style={{ width: 800, height: 600 }}>
      <ReactFlow
        nodes={ctx.nodes}
        edges={ctx.edges}
        nodeTypes={NODE_TYPES}
        onNodesChange={ctx.onNodesChange}
        onEdgesChange={ctx.onEdgesChange}
      />
    </div>
  );
};

function makeNode(id: string, nodeType: string, type: string = CURIO_UNIVERSAL_NODE_TYPE) {
  return {
    id,
    type,
    position: { x: 0, y: 0 },
    data: {
      nodeId: id,
      nodeType,
      input: '',
      inputTypes: [],
      outputCallback: (nodeId: string, output: unknown, options?: object) =>
        api.applyNewOutput({ nodeId, output, ...options } as any),
    },
  } as any;
}

async function flush() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
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

/** A join with *points* wired to input_0 and *polygons* to input_1. */
async function openJoin(points: { id: string; type: string }, polygons: { id: string; type: string }) {
  render(
    <ReactFlowProvider>
      <FlowProvider>
        <Bridge />
      </FlowProvider>
    </ReactFlowProvider>,
  );
  await flush();
  await act(async () => {
    [makeNode(points.id, points.type), makeNode(polygons.id, polygons.type), makeNode('join', JOIN_TYPE, 'probe')]
      .forEach((n) => api.addNode(n, undefined, false));
  });
  await flush();
  await addEdge(points.id, 'join', 'in');
  await addEdge(polygons.id, 'join', 'in_1');
  expect(seen.has('join')).toBe(true);
}

/** Example 10's route: a Simple View's points and the Python Computation's polygons. */
const ROUTE = {
  points: { id: 'view', type: 'curio.builtin/vis-simple' },
  polygons: { id: 'transform', type: 'curio.builtin/python-computation' },
};

/** What the join's code reads: the points on circle 0, the polygons on circle 1. */
function bothOnTheirCircles(points: unknown, polygons: unknown) {
  return { dataType: 'outputs', data: [normalizeFlowInput(points), normalizeFlowInput(polygons)] };
}

beforeEach(() => {
  seen.clear();
});

describe('a node with several ports whose inputs land in one render', () => {
  test('the polygons, then the points: the code reads both, each on its circle', async () => {
    // Run 37238862475 (#717), twice: the polygons were lost.
    await openJoin(ROUTE.points, ROUTE.polygons);

    await act(async () => {
      api.applyNewOutput({ nodeId: 'transform', output: POLYGONS_OUT } as any);
      api.applyNewOutput({ nodeId: 'view', output: POINTS_OUT } as any);
    });
    await flush();

    expect(seen.get('join').input).toEqual(bothOnTheirCircles(POINTS_OUT, POLYGONS_OUT));
  });

  test('the points, then the polygons: the code reads both, each on its circle', async () => {
    // Runs 37196358465 (#703), 37224332761 and 37480444036 (#760): the points were lost.
    await openJoin(ROUTE.points, ROUTE.polygons);

    await act(async () => {
      api.applyNewOutput({ nodeId: 'view', output: POINTS_OUT } as any);
      api.applyNewOutput({ nodeId: 'transform', output: POLYGONS_OUT } as any);
    });
    await flush();

    expect(seen.get('join').input).toEqual(bothOnTheirCircles(POINTS_OUT, POLYGONS_OUT));
  });

  test('the two inputs in two renders: one on its circle, then both', async () => {
    await openJoin(ROUTE.points, ROUTE.polygons);

    await act(async () => {
      api.applyNewOutput({ nodeId: 'transform', output: POLYGONS_OUT } as any);
    });
    await flush();
    // Until every wired circle holds a value the node reads nothing, as a
    // growing node does: it never runs on part of its inputs.
    expect(seen.get('join').input).toBe('');
    expect(seen.get('join').portInputs).toEqual({ in_1: normalizeFlowInput(POLYGONS_OUT) });

    await act(async () => {
      api.applyNewOutput({ nodeId: 'view', output: POINTS_OUT } as any);
    });
    await flush();

    expect(seen.get('join').input).toEqual(bothOnTheirCircles(POINTS_OUT, POLYGONS_OUT));
  });

  test('a reopened dataflow: both restored inputs reach the join, each on its circle', async () => {
    // Example 15's shape: two Data Loading nodes feed the join. A load
    // restores every saved output in one tick (hydrateRestoredOutputs).
    await openJoin(
      { id: 'photos', type: 'curio.builtin/data-loading' },
      { id: 'neighborhoods', type: 'curio.builtin/data-loading' },
    );

    await act(async () => {
      api.hydrateRestoredOutputs([
        { nodeId: 'neighborhoods', output: 'neighborhoods-artifact' },
        { nodeId: 'photos', output: 'photos-artifact' },
      ] as any);
      await new Promise((r) => setTimeout(r, 5)); // hydration defers one tick
    });
    await flush();

    expect(seen.get('join').input).toEqual(bothOnTheirCircles('photos-artifact', 'neighborhoods-artifact'));
  });
});

describe("a node's several ports keep their inputs (#576)", () => {
  test('deleting input_0 leaves input_1 on its own circle, and the code reads it there alone', async () => {
    // A growing node closes its circles up when an edge goes; a node with
    // several ports must not, or input_1 would become the join's left side.
    await openJoin(ROUTE.points, ROUTE.polygons);
    await act(async () => {
      api.applyNewOutput({ nodeId: 'view', output: POINTS_OUT } as any);
      api.applyNewOutput({ nodeId: 'transform', output: POLYGONS_OUT } as any);
    });
    await flush();
    const doomed = api.edges.filter((e: any) => e.targetHandle === 'in');
    await act(async () => {
      api.onEdgesDelete(doomed);
      api.onEdgesChange(doomed.map((e: any) => ({ type: 'remove', id: e.id })) as any);
    });
    await flush();

    expect(api.edges.map((e: any) => [e.source, e.targetHandle])).toEqual([['transform', 'in_1']]);
    expect(seen.get('join').portInputs).toEqual({ in_1: normalizeFlowInput(POLYGONS_OUT) });
    // One wired circle, circle 1: its value alone, which the run names input_1.
    expect(seen.get('join').input).toEqual(normalizeFlowInput(POLYGONS_OUT));
  });
});
