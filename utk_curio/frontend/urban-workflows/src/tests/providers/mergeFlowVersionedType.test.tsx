/**
 * Regression tests for #159 — the `@1` version suffix broke Merge Flow.
 *
 * A node dragged off the tool rail carries the *versioned* canonical id
 * (`curio.builtin/merge-flow@1`, minted by `manifest.canonical_for` and
 * persisted verbatim by TrillGenerator), while `NodeType.MERGE_FLOW` is
 * unversioned. FlowProvider's merge branches compared the two with `===`, so a
 * palette-dragged merge node matched none of them: `propagateDownstreamInputs`
 * fell through to the scalar branch, `data.input` never became a slot array,
 * `buildMergeOutputArray` returned `[]`, the merge node never emitted, and the
 * downstream Python node hit the sandbox's "received no input but references
 * `arg`" guard.
 *
 * Both id forms are parametrized: the bare form worked before this fix and must
 * keep working, and the versioned form is the bug.
 *
 * Drives the REAL FlowProvider (applyNewOutput -> propagateDownstreamInputs and
 * onConnect -> applyOutput). The harness mirrors playAllFlakiness.test.tsx.
 */
import React from 'react';
import { render, act } from '@testing-library/react';
import { ReactFlow, ReactFlowProvider } from 'reactflow';

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
import { NodeType } from '../../constants';
import { normalizeFlowInput } from '../../utils/flowOutputRef';

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

/** Wire source -> merge slot `in_<slot>` the way onConnect does at runtime. */
async function connectToMergeSlot(source: string, target: string, slot: number) {
  await act(async () => {
    api.onEdgesChange([
      {
        type: 'add',
        item: {
          id: `${source}->${target}-${slot}`,
          source,
          target,
          sourceHandle: 'out',
          targetHandle: `in_${slot}`,
        },
      } as any,
    ]);
  });
  await flush();
}

const dataOf = (id: string) => api.nodes.find((n: any) => n.id === id)?.data as any;

// The whole point of the bug: `@1` is what the palette actually produces.
const VERSIONED = `${NodeType.MERGE_FLOW}@1`;
const FORMS: Array<[string, string]> = [
  ['unversioned (converter / legacy trill)', NodeType.MERGE_FLOW],
  ['versioned (palette drag)', VERSIONED],
];

describe.each(FORMS)('merge-flow input plumbing — %s', (_label, mergeType) => {
  test('a produced output lands in the merge slot rather than overwriting data.input', async () => {
    renderFlow();
    await addNodes([
      node('src-a', NodeType.DATA_LOADING),
      node('src-b', NodeType.DATA_LOADING),
      node('merge', mergeType),
    ]);
    await connectToMergeSlot('src-a', 'merge', 0);
    await connectToMergeSlot('src-b', 'merge', 1);

    await act(async () => {
      api.applyNewOutput({ nodeId: 'src-a', output: 'artifact-a' } as any);
    });
    await flush();

    const refA = normalizeFlowInput('artifact-a');
    const refB = normalizeFlowInput('artifact-b');

    const afterFirst = dataOf('merge');
    expect(Array.isArray(afterFirst.input)).toBe(true);
    expect(afterFirst.input[0]).toEqual(refA);
    expect(afterFirst.source[0]).toBe('src-a');

    // The second producer must fill its OWN slot, not clobber the first. This is
    // the assertion that fails with `@1` pre-fix: the scalar branch replaced the
    // whole of data.input, so slot 0 was lost and the merge never had both inputs.
    await act(async () => {
      api.applyNewOutput({ nodeId: 'src-b', output: 'artifact-b' } as any);
    });
    await flush();

    const afterSecond = dataOf('merge');
    expect(Array.isArray(afterSecond.input)).toBe(true);
    expect(afterSecond.input[0]).toEqual(refA);
    expect(afterSecond.input[1]).toEqual(refB);
    expect(afterSecond.source.slice(0, 2)).toEqual(['src-a', 'src-b']);
  });

  test('a non-merge downstream node still receives a scalar input', async () => {
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
