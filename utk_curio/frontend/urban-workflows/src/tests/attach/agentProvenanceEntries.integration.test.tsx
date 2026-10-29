/**
 * An agent's change that the user applied is an entry of the node's
 * Provenance drawer, named after the agent, on every node.
 *
 * A Python node has no writer of its own (utils/nodeCodeWriters), so the
 * canvas writes the code and files the change as a Map Editor node files its
 * own: an edit holding the code it left and the code it replaced
 * (`useGraphEdits.applyNodeContent`), with the dataflow left Unsaved, so the
 * next save keeps the entry where an agent reads it. A node an agent adds
 * with code starts its history with such an edit (`useAgentCanvasMutations`);
 * a planned node, added with no code, starts with none, and the code written
 * into it later is its first.
 *
 * Drives the REAL FlowProvider, ProvenanceProvider, useCode and bridge, as
 * agentCanvasBridge.integration.test.tsx does; only IO collaborators are
 * stubbed, so the test holds the wiring between them too.
 */
import React from 'react';
import { render, act } from '@testing-library/react';
import { ReactFlow, ReactFlowProvider } from 'reactflow';

// ── jsdom polyfills ReactFlow needs (same as agentCanvasBridge.integration) ──
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(global as any).ResizeObserver = ResizeObserverStub;
if (!(global as any).DOMMatrixReadOnly) {
  (global as any).DOMMatrixReadOnly = class { m22 = 1; constructor() {} };
}

const mockShowToast = jest.fn();
// What leaves the dataflow Unsaved: the next save writes what changed.
const mockMarkDirty = jest.fn();

jest.mock('../../hook/useWorkflowOperations', () => ({
  useWorkflowOperations: () => ({
    markNodeExecuted: jest.fn(),
    markNodeStale: jest.fn(),
    markDirty: mockMarkDirty,
    recordOutputs: jest.fn().mockResolvedValue(undefined),
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
  useToastContext: () => ({ showToast: mockShowToast }),
}));

jest.mock('../../providers/CollaborationProvider', () => ({
  useCollab: () => ({
    lockedNodes: {},
    lockNode: jest.fn(),
    unlockNode: jest.fn(),
    onRemote: jest.fn(),
  }),
}));

// Interpreters open socket.io pools at module scope: stub the classes only,
// keeping useCode's real logic.
jest.mock('../../PythonInterpreter', () => ({ PythonInterpreter: class {} }));
jest.mock('../../JavaScriptInterpreter', () => ({ JavaScriptInterpreter: class {} }));

// vega is ESM; same stubs as the other FlowProvider integration suites.
jest.mock('../../hook/useVega', () => ({
  useVega: () => ({ handleCompileGrammar: jest.fn().mockResolvedValue(undefined) }),
}));
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });

// Registry refresh does network I/O; the plain node.create path never calls it.
const mockRefreshPackageRegistry = jest.fn(() => Promise.resolve());
jest.mock('../../registry/packageRegistryBootstrap', () => ({
  refreshPackageRegistry: () => mockRefreshPackageRegistry(),
}));

import FlowProvider, { useFlowContext } from '../../providers/FlowProvider';
import ProvenanceProvider, { useProvenanceContext, type NodeExecRecord } from '../../providers/ProvenanceProvider';
import { useAgentCanvasMutations } from '../../components/agents/attach/useAgentCanvasMutations';
import { notifyAgentCanvasMutation } from '../../services/agents';

let flow: ReturnType<typeof useFlowContext>;
let provenance: ReturnType<typeof useProvenanceContext>;

/** Mirrors AgentDockOverlay's placement: a FlowProvider child, beside <ReactFlow>. */
const BridgeHost: React.FC = () => {
  useAgentCanvasMutations();
  return null;
};

const Canvas: React.FC = () => {
  const ctx = useFlowContext();
  flow = ctx;
  return (
    <div style={{ width: 800, height: 600 }}>
      <ReactFlow
        nodes={ctx.nodes}
        edges={ctx.edges}
        onNodesChange={ctx.onNodesChange}
        onEdgesChange={ctx.onEdgesChange}
      />
      <BridgeHost />
    </div>
  );
};

/** What a node's Provenance drawer reads. */
const ProvenanceProbe: React.FC = () => {
  provenance = useProvenanceContext();
  return null;
};

function renderCanvas() {
  return render(
    <ReactFlowProvider>
      <ProvenanceProvider>
        <ProvenanceProbe />
        <FlowProvider>
          <Canvas />
        </FlowProvider>
      </ProvenanceProvider>
    </ReactFlowProvider>,
  );
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

async function dispatch(mutation: Parameters<typeof notifyAgentCanvasMutation>[0]) {
  await act(async () => {
    notifyAgentCanvasMutation(mutation);
  });
  await flush();
}

/** The entries of *nodeId*'s Provenance drawer. */
const entries = (nodeId: string): NodeExecRecord[] => provenance.getAllNodeProvenance()[nodeId] ?? [];
/** The code *nodeId* holds on the canvas, which a save writes. */
const code = (nodeId: string) => flow.nodes.find((n: any) => n.id === nodeId)?.data?.code;

const AGENT = 'Node Builder';
/** A Python node's code: the years from 2020 on. */
const BEFORE = "return input_0[input_0['year'] >= 2020]";
/** What the agent writes into it: every year. */
const AFTER = 'return input_0';
/** A later change of the agent's: the years before 2020. */
const AGAIN = "return input_0[input_0['year'] < 2020]";

/** A Python node on the canvas, added with no agent named. */
const PYTHON = {
  id: 'python-node',
  type: 'curio.builtin/computation-analysis',
  content: BEFORE,
  goal: 'years',
  x: 500,
  y: 60,
};
// A node the apply names its agent on. Held in a variable rather than written
// into the event, so the file compiles against a payload type that does not
// name the agent yet and fails on what the canvas does.
const ADDED_BY_AGENT = { ...PYTHON, id: 'agent-node', content: AFTER, agent: AGENT };
/** A planned node: added with no code. */
const PLANNED = { ...PYTHON, id: 'planned-node', content: '', agent: AGENT };

beforeEach(() => {
  mockMarkDirty.mockClear();
});

describe("an agent's applied change is an entry of the node's history", () => {
  it('on a Python node, an edit named after the agent that holds the code it left and the code it replaced', async () => {
    renderCanvas();
    await flush();
    await dispatch({ kind: 'node-created', node: PYTHON });
    // Added with no agent named: no entry yet.
    expect(entries(PYTHON.id)).toEqual([]);

    mockMarkDirty.mockClear();
    await dispatch({ kind: 'node-content-applied', nodeId: PYTHON.id, content: AFTER, agent: AGENT });
    expect(code(PYTHON.id)).toBe(AFTER);
    // The dataflow reads Unsaved, as after an edit made in a Map Editor node,
    // so the next save keeps the entry.
    expect(mockMarkDirty).toHaveBeenCalled();
    expect(entries(PYTHON.id)).toHaveLength(1);
    expect(entries(PYTHON.id)[0]).toMatchObject({
      kind: 'edit', label: AGENT, code: AFTER, before: BEFORE, inputs: [], outputs: [], parentId: null,
    });

    // The next change descends from it, which holds the code that one replaced.
    await dispatch({ kind: 'node-content-applied', nodeId: PYTHON.id, content: AGAIN, agent: AGENT });
    expect(code(PYTHON.id)).toBe(AGAIN);
    const [first, second] = entries(PYTHON.id);
    expect(second).toMatchObject({ kind: 'edit', label: AGENT, code: AGAIN, parentId: first.id });
    expect(second.before).toBeUndefined();
  });

  it('a change that leaves the code as it was is no entry', async () => {
    renderCanvas();
    await flush();
    await dispatch({ kind: 'node-created', node: PYTHON });
    mockMarkDirty.mockClear();
    await dispatch({ kind: 'node-content-applied', nodeId: PYTHON.id, content: BEFORE, agent: AGENT });
    expect(code(PYTHON.id)).toBe(BEFORE);
    expect(entries(PYTHON.id)).toEqual([]);
    // Nothing changed, so nothing waits to be saved.
    expect(mockMarkDirty).not.toHaveBeenCalled();
  });

  it("a change applied without the agent's name is named Agent, as a Map Editor node names it", async () => {
    renderCanvas();
    await flush();
    await dispatch({ kind: 'node-created', node: PYTHON });
    await dispatch({ kind: 'node-content-applied', nodeId: PYTHON.id, content: AFTER });
    expect(entries(PYTHON.id)).toHaveLength(1);
    expect(entries(PYTHON.id)[0]).toMatchObject({ kind: 'edit', label: 'Agent', code: AFTER, before: BEFORE });
  });
});

describe('a node an agent adds', () => {
  it('with code starts its history with one entry named after the agent', async () => {
    renderCanvas();
    await flush();
    await dispatch({ kind: 'node-created', node: ADDED_BY_AGENT });
    expect(code(ADDED_BY_AGENT.id)).toBe(AFTER);
    expect(entries(ADDED_BY_AGENT.id)).toHaveLength(1);
    expect(entries(ADDED_BY_AGENT.id)[0]).toMatchObject({
      kind: 'edit', label: AGENT, code: AFTER, inputs: [], outputs: [], parentId: null,
    });
    // It replaced no code.
    expect(entries(ADDED_BY_AGENT.id)[0].before).toBeUndefined();
  });

  it('with no code, as a planned node, starts with none, and the code then written into it is its first', async () => {
    renderCanvas();
    await flush();
    await dispatch({ kind: 'node-created', node: PLANNED });
    expect(entries(PLANNED.id)).toEqual([]);
    await dispatch({ kind: 'node-content-applied', nodeId: PLANNED.id, content: AFTER, agent: AGENT });
    expect(entries(PLANNED.id)).toHaveLength(1);
    expect(entries(PLANNED.id)[0]).toMatchObject({ kind: 'edit', label: AGENT, code: AFTER, parentId: null });
  });
});
