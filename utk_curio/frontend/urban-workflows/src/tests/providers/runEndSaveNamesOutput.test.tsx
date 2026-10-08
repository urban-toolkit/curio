/**
 * The save that ends a run on the server names the output that ended it.
 *
 * A run ends in the tick its last step lands (`useServerRun.onEvent`): the
 * step's output goes through `applyNewOutput`, then `finish` flushes the
 * install save (`flushInstallSyncRef`), and that save reads what to send from
 * `outputsRef` (`buildOutputRefs`). The run has already recorded the output in
 * the dataflow (`record_node_outputs`), so a save that left it out took it back
 * out, and a reopen restored the node's output only from the run's record.
 *
 * Two Python Computation nodes with no edge between them, both saving their
 * output, each played on its own, as `test_computed_json_output_e2e.py` plays
 * them. The dataflow is opened as `reopenKeepsRestoredOutputs.test.tsx` opens
 * one: `loadProject`, then the load as `ProjectLoader` applies it.
 */
import React from 'react';
import { render, act, waitFor } from '@testing-library/react';
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

const mockShowToast = jest.fn();
const mockGetProject = jest.fn();
const mockUpdateProject = jest.fn();
const mockStartRun = jest.fn();
const mockFollowRun = jest.fn();

jest.mock('../../api/projectsApi', () => {
  const actual = jest.requireActual('../../api/projectsApi');
  return {
    ...actual,
    projectsApi: {
      ...actual.projectsApi,
      get: (...args: any[]) => mockGetProject(...args),
      update: (...args: any[]) => mockUpdateProject(...args),
    },
  };
});

jest.mock('../../services/runs/runsApi', () => {
  const actual = jest.requireActual('../../services/runs/runsApi');
  return {
    ...actual,
    runsApi: {
      ...actual.runsApi,
      start: (...args: any[]) => mockStartRun(...args),
      follow: (...args: any[]) => mockFollowRun(...args),
    },
  };
});

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
    broadcastNodeAdded: jest.fn(),
    broadcastNodeRemoved: jest.fn(),
    broadcastNodeUpdated: jest.fn(),
    broadcastEdgeAdded: jest.fn(),
    broadcastEdgeRemoved: jest.fn(),
    onRemote: jest.fn(),
  }),
}));

jest.mock('../../hook/useVega', () => ({
  useVega: () => ({ handleCompileGrammar: jest.fn().mockResolvedValue(undefined) }),
}));
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });

import FlowProvider, { useFlowContext } from '../../providers/FlowProvider';
import { useCode } from '../../hook/useCode';
import { UserContext } from '../../providers/userContext';
import type { UserData } from '../../utils/authApi';
import type { Run, RunEvent } from '../../services/runs/runsApi';

const PROJECT_ID = 'run-end-save';
const NODE_TYPE = 'curio.builtin/computation-analysis';
const DICT = 'json-output-b-dict';
const SCALAR = 'json-output-a-scalar';
/** Each node's output as its run's reply names it: an artifact id. */
const OUTPUT: Record<string, { path: string; dataType: string }> = {
  [DICT]: { path: '1791400000000_0a1b2c3d', dataType: 'dict' },
  [SCALAR]: { path: '1791400002000_4e5f6a7b', dataType: 'int' },
};

function spec() {
  const node = (id: string, x: number, content: string) => ({
    id, type: `${NODE_TYPE}@1`, x, y: 0, content, saveOutputDataset: true,
  });
  return {
    dataflow: {
      name: 'Run end save',
      task: '',
      nodes: [
        node(DICT, 10, 'return {"city": "Chicago"}\n'),
        node(SCALAR, 620, 'return 42\n'),
      ],
      edges: [],
    },
  };
}

type UserContextValue = React.ContextType<typeof UserContext>;

const OWNER: UserData = {
  id: 2,
  username: 'ada',
  name: 'Ada',
  email: null,
  profile_image: null,
  type: null,
  is_guest: false,
};

/** Signed in, on the dataflow's own canvas: runs go to the server. */
const SIGNED_IN: UserContextValue = {
  user: OWNER,
  loading: false,
  isAuthenticated: true,
  enableUserAuth: true,
  skipProjectPage: false,
  allowGuest: true,
  sharedGuestUsername: 'guest_shared',
  isSharedGuest: false,
  signup: async () => null,
  signin: async () => null,
  signinGuest: async () => null,
  signout: async () => {},
  updateProfile: async () => {},
  updateTokens: async () => {},
  saveUserType: async () => {},
  logout: () => {},
};

type FlowApi = ReturnType<typeof useFlowContext>;
let api: FlowApi;
let code: ReturnType<typeof useCode>;

const Bridge: React.FC = () => {
  api = useFlowContext();
  code = useCode();
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

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

/** Each run the canvas follows, with the stream's event handler. */
let followed: Array<{ runId: string; onEvent: (event: RunEvent) => void }> = [];

function oneNodeRun(runId: string, nodeId: string): Run {
  return {
    id: runId, projectId: PROJECT_ID, projectName: 'Run end save', trigger: 'node',
    targetNodeId: nodeId, wholeDataflow: false, rerunOf: null, specRevision: 4,
    status: 'running', createdAt: null, startedAt: null, finishedAt: null,
    counts: { ok: 0, failed: 0, skipped: 0, waiting: 0 }, error: null, live: true,
    steps: [{
      nodeId, label: 'Python Computation', nodeType: NODE_TYPE, level: 0,
      role: 'run', status: 'pending', startedAt: null, finishedAt: null, durationMs: null,
      outputPath: null, outputType: null, installedDatasetId: null, codeSha256: null,
      stdoutTail: null, stderrTail: null, skipReason: null,
    }],
  };
}

/** Open the saved dataflow, never run, on a fresh canvas. */
async function open() {
  render(
    <UserContext.Provider value={SIGNED_IN}>
      <ReactFlowProvider>
        <FlowProvider>
          <Bridge />
        </FlowProvider>
      </ReactFlowProvider>
    </UserContext.Provider>,
  );
  await flush();
  await act(async () => {
    const result = await api.loadProject(PROJECT_ID);
    code.loadTrill(result.spec, undefined, undefined, {});
  });
  await flush();
  expect(api.nodes.map((n: any) => n.id).sort()).toEqual([DICT, SCALAR].sort());
}

/** The node ids a save named in its outputs. */
function named(save: any[]): string[] {
  return (save[1]?.outputs ?? []).map((ref: any) => ref.node_id).sort();
}

/**
 * Play *nodeId* on the server and land its one step, as the run's stream
 * delivers it; returns the saves the canvas made from then on, the one the
 * run's end flushes first.
 */
async function playAndLand(nodeId: string): Promise<any[][]> {
  const runId = `run-${nodeId}`;
  mockStartRun.mockImplementationOnce(async () => oneNodeRun(runId, nodeId));
  await act(async () => {
    api.playNodesUpTo(nodeId);
  });
  await waitFor(() => {
    if (!followed.some((f) => f.runId === runId)) {
      throw new Error(`the canvas never followed ${runId}; toasts: ${JSON.stringify(mockShowToast.mock.calls)}`);
    }
  });
  // The save before the run has answered and its chain is idle, as it is
  // long before a node's run ends.
  await flush();
  await flush();
  const before = mockUpdateProject.mock.calls.length;
  const stream = followed.find((f) => f.runId === runId)!;
  act(() => {
    stream.onEvent({
      kind: 'step_finished', nodeId, status: 'ok', startedAt: 1791400000, finishedAt: 1791400001,
      reply: { stdout: [], stderr: '', input: '', output: OUTPUT[nodeId] },
    });
  });
  await flush();
  return mockUpdateProject.mock.calls.slice(before);
}

beforeEach(() => {
  followed = [];
  mockGetProject.mockResolvedValue({
    project: {
      id: PROJECT_ID, name: 'Run end save', spec_revision: 3,
      updated_at: '2026-10-07T08:37:45Z', categories: {},
    },
    spec: spec(),
    outputs: [],
  });
  mockUpdateProject.mockImplementation(async (id: string) => ({
    id, name: 'Run end save', spec_revision: 4, spec: spec(), categories: {}, outputs: [],
    dataset_install_warnings: [],
  }));
  mockFollowRun.mockImplementation((runId: string, onEvent: (event: RunEvent) => void, signal?: AbortSignal) => {
    followed.push({ runId, onEvent });
    return new Promise<void>((resolve) => signal?.addEventListener('abort', () => resolve()));
  });
});

afterEach(() => {
  jest.clearAllMocks();
});

describe('the save that ends a run on the server', () => {
  test('names the output of the node the run ended on, and every output before it', async () => {
    await open();

    const afterDict = await playAndLand(DICT);
    const afterScalar = await playAndLand(SCALAR);

    // The first save after each step is the one the run's end flushes. The
    // run recorded the node's output before its step reached the canvas, and
    // a save's outputs replace the dataflow's: one that leaves the node out
    // takes its output back out.
    expect(afterDict.length).toBeGreaterThan(0);
    expect(named(afterDict[0])).toEqual([DICT]);
    expect(afterScalar.length).toBeGreaterThan(0);
    expect(named(afterScalar[0])).toEqual([DICT, SCALAR].sort());
    const scalarRef = afterScalar[0][1].outputs.find((ref: any) => ref.node_id === SCALAR);
    expect(scalarRef).toEqual(expect.objectContaining({
      filename: OUTPUT[SCALAR].path, data_type: OUTPUT[SCALAR].dataType,
    }));
  });
});
