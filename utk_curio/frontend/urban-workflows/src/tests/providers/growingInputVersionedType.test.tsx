/**
 * The #159 class of bug on a node with several inputs: the `@1` version suffix
 * must not change how a growing node takes its inputs.
 *
 * A node dragged off the tool rail carries the *versioned* canonical id
 * (`curio.builtin/data-pool@1`, minted by `manifest.canonical_for` and
 * persisted verbatim by TrillGenerator), while `NodeType.DATA_POOL` and the
 * Jupyter converter's and legacy trills' ids are unversioned. #159 was a
 * lookup that matched only one form: the versioned node fell through to the
 * single-input branch, each producer overwrote the whole `data.input`, and the
 * node never held both inputs. A node grows its circles when its descriptor
 * says so (`nodeGrowsInputs` -> `tryGetNodeDescriptor`), so both forms must
 * resolve to the same `@1` descriptor and take the same path.
 *
 * Both id forms are parametrized: the bare form is what old specs carry, and
 * the versioned form is what the palette produces.
 *
 * Drives the REAL FlowProvider (applyNewOutput -> propagateDownstreamInputs).
 * The harness mirrors playAllFlakiness.test.tsx.
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

jest.mock('../../hook/useCode', () => ({ pythonInterpreter: {}, jsInterpreter: {} }));
jest.mock('../../hook/useVega', () => ({
  useVega: () => ({ handleCompileGrammar: jest.fn().mockResolvedValue(undefined) }),
}));
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });

import FlowProvider, { useFlowContext } from '../../providers/FlowProvider';
import { NodeType, SupportedType } from '../../constants';
import { normalizeFlowInput } from '../../utils/flowOutputRef';
import { registerNode } from '../../registry/nodeRegistry';
import type { NodeDescriptor } from '../../registry/types';

// The whole point of the bug: `@1` is what the palette actually produces.
const VERSIONED = `${NodeType.DATA_POOL}@1`;

beforeAll(() => {
  // Registered under the versioned id only, as the package registry does; the
  // bare form has to find it through the registry's unversioned lookup.
  const descriptor: NodeDescriptor = {
    id: VERSIONED as NodeType,
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

async function flush() {
  await act(async () => { await Promise.resolve(); });
}

function node(id: string, nodeType: string) {
  return {
    id,
    type: nodeType,
    position: { x: 0, y: 0 },
    data: { nodeId: id, nodeType },
  } as any;
}

async function addNodes(nodes: any[]) {
  await act(async () => { nodes.forEach((n) => api.addNode(n, undefined, false)); });
  await flush();
}

/** Wire source -> circle *slot* the way onConnect does at runtime. */
async function connectToCircle(source: string, target: string, slot: number) {
  await act(async () => {
    api.onEdgesChange([
      {
        type: 'add',
        item: {
          id: `${source}->${target}-${slot}`,
          source,
          target,
          sourceHandle: 'out',
          targetHandle: slot === 0 ? 'in' : `in_${slot}`,
        },
      } as any,
    ]);
  });
  await flush();
}

const dataOf = (id: string) => api.nodes.find((n: any) => n.id === id)?.data as any;

const FORMS: Array<[string, string]> = [
  ['unversioned (converter / legacy trill)', NodeType.DATA_POOL],
  ['versioned (palette drag)', VERSIONED],
];

describe.each(FORMS)('growing node input plumbing: %s', (_label, poolType) => {
  test('a produced output lands in its own circle rather than overwriting data.input', async () => {
    renderFlow();
    await addNodes([
      node('src-a', NodeType.DATA_LOADING),
      node('src-b', NodeType.DATA_LOADING),
      node('pool', poolType),
    ]);
    await connectToCircle('src-a', 'pool', 0);
    await connectToCircle('src-b', 'pool', 1);

    await act(async () => {
      api.applyNewOutput({ nodeId: 'src-a', output: 'artifact-a' } as any);
    });
    await flush();

    const refA = normalizeFlowInput('artifact-a');
    const refB = normalizeFlowInput('artifact-b');

    const afterFirst = dataOf('pool');
    expect(Array.isArray(afterFirst.inputSlots)).toBe(true);
    expect(afterFirst.inputSlots[0]).toEqual(refA);
    expect(afterFirst.sourceSlots[0]).toBe('src-a');
    // Circle 1 is wired and empty, so the node reads nothing yet; the
    // single-input branch would have handed it src-a's output alone.
    expect(afterFirst.input).toBe('');

    // The second producer must fill its OWN circle, not clobber the first. This
    // is the assertion the single-input branch fails: it replaces the whole of
    // data.input, so circle 0 is lost and the node never has both inputs.
    await act(async () => {
      api.applyNewOutput({ nodeId: 'src-b', output: 'artifact-b' } as any);
    });
    await flush();

    const afterSecond = dataOf('pool');
    expect(afterSecond.inputSlots[0]).toEqual(refA);
    expect(afterSecond.inputSlots[1]).toEqual(refB);
    expect(afterSecond.sourceSlots.slice(0, 2)).toEqual(['src-a', 'src-b']);
    expect(afterSecond.input).toEqual({ dataType: 'outputs', data: [refA, refB] });
  });

  test('a node that does not grow circles still receives a scalar input', async () => {
    renderFlow();
    await addNodes([
      node('src-a', NodeType.DATA_LOADING),
      node('plain', NodeType.DATA_TRANSFORMATION),
    ]);
    await act(async () => {
      api.onEdgesChange([
        {
          type: 'add',
          item: {
            id: 'src-a->plain',
            source: 'src-a',
            target: 'plain',
            sourceHandle: 'out',
            targetHandle: 'in',
          },
        } as any,
      ]);
    });
    await flush();

    await act(async () => {
      api.applyNewOutput({ nodeId: 'src-a', output: 'artifact-a' } as any);
    });
    await flush();

    const data = dataOf('plain');
    expect(Array.isArray(data.input)).toBe(false);
    expect(data.input).toEqual(normalizeFlowInput('artifact-a'));
    expect(data.source).toBe('src-a');
  });
});
