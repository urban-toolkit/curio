/**
 * A reopened dataflow keeps the outputs its load restored, so a play below a
 * restored node runs that node only: in the browser, and on the server too
 * (#407, and the memory pressure it adds to #408).
 *
 * A play on the server (`useServerRun.startRun`) sends `reuse`: the outputs of
 * the ancestors `nodesToRunUpTo` says need no new run, read from the
 * provider's `outputs` (`serverRunSteps.reuseFor`). The server runs the target
 * and every ancestor not in `reuse` (`run_engine.plan_run`). The save before
 * it sends the same `outputs` (`buildOutputRefs`), which the manifest records.
 *
 * The dataflow is reopened here as `ProjectLoader` opens it: `loadProject`,
 * then `applyResult`, which loads the spec (`useCode().loadTrill`, then
 * `useWorkflowOperations.loadParsedTrill`) and, in the same tick, puts the
 * restored outputs in `outputs` and passes them down the edges the load built.
 * `reopenReusesRestoredOutputs.test.tsx` covers the browser's walk with the
 * load mocked; this one runs the real load.
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
      // What the run then does is the server's: the test reads what it was asked.
      follow: () => new Promise<void>(() => {}),
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
import { restoredByNode, restoredOutputs, withOutputs, type SavedOutputRef } from '../../utils/restoredOutputs';

const PROJECT_ID = 'tuple-reopen';
const NODE_TYPE = 'curio.builtin/computation-analysis';
// Example 09's UTCI node returns a tuple, and its zonal node indexes it.
const PRODUCER = 'tuple-utci';
const CONSUMER = 'tuple-zonal';
/** The file the manifest names for the producer's saved output. */
const PRODUCER_FILE = '1791362265273_8db053ca';

function spec() {
  const node = (id: string, x: number, content: string) => ({
    id, type: NODE_TYPE, x, y: 0, content, saveOutputDataset: true,
  });
  return {
    dataflow: {
      name: 'Tuple reopen',
      task: '',
      nodes: [
        node(PRODUCER, 0, "utci_list = [[31.5, float('nan')], [33.0, 34.5]]\nutci_shape = [2, 2]\nreturn (utci_list, utci_shape)\n"),
        node(CONSUMER, 645, "utci_list = [!! input 0 !!][0]\nutci_shape = [!! input 0 !!][1]\nreturn f'{utci_shape[0]} by {utci_shape[1]}'\n"),
      ],
      edges: [{
        id: `${PRODUCER}->${CONSUMER}`, source: PRODUCER, target: CONSUMER,
        sourceHandle: 'out', targetHandle: 'in',
      }],
    },
  };
}

/** The producer ran and was saved; the node below it never ran. */
const SAVED: SavedOutputRef[] = [{ node_id: PRODUCER, filename: PRODUCER_FILE, data_type: 'outputs' }];
/** The producer's output as the canvas holds it after the restore. */
const RESTORED = { path: PRODUCER_FILE, dataType: 'outputs' };

/** What `GET /api/projects/<id>` answers. */
function loadResponse() {
  return {
    project: {
      id: PROJECT_ID, name: 'Tuple reopen', spec_revision: 3,
      updated_at: '2026-10-07T08:37:45Z', categories: {},
    },
    spec: spec(),
    outputs: SAVED.map((ref) => ({ ...ref })),
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
    await Promise.resolve();
  });
}

/** `ProjectLoader`'s `applyResult` for a loaded project, as it runs it. */
function applyResult(result: { spec: any; outputs: SavedOutputRef[] }) {
  const loaded = code.loadTrill(result.spec, undefined, undefined, restoredByNode(result.outputs));
  const outputs = restoredOutputs(result.outputs);
  api.setOutputs((prev) => withOutputs(prev, outputs));
  api.hydrateRestoredOutputs(outputs, loaded.edges);
}

/** Open the saved dataflow on a fresh canvas, signed in as *user* or as nobody. */
async function reopen(user: UserContextValue | null) {
  const canvas = (
    <ReactFlowProvider>
      <FlowProvider>
        <Bridge />
      </FlowProvider>
    </ReactFlowProvider>
  );
  render(user ? <UserContext.Provider value={user}>{canvas}</UserContext.Provider> : canvas);
  await flush();
  await act(async () => {
    const result = await api.loadProject(PROJECT_ID);
    applyResult(result);
  });
  // The restored outputs go downstream a tick later (hydrateRestoredOutputs).
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  await flush();

  // The load built the canvas, and the producer counts as having run.
  expect(api.nodes.map((n: any) => n.id).sort()).toEqual([CONSUMER, PRODUCER].sort());
  expect(api.edges.map((e: any) => [e.source, e.target])).toEqual([[PRODUCER, CONSUMER]]);
  expect(api.nodes.find((n: any) => n.id === PRODUCER)?.data?.output?.code).toBe('success');
}

function triggerExecOf(id: string): number {
  const n = api.nodes.find((x: any) => x.id === id);
  return (n?.data?.triggerExec as number) ?? 0;
}

/** Play *target* on the server; resolves with what the run was asked to do. */
async function playOnServer(target: string): Promise<{ projectId: string; body: any }> {
  await act(async () => {
    api.playNodesUpTo(target);
  });
  await waitFor(() => {
    if (mockStartRun.mock.calls.length === 0) {
      throw new Error(`no run was started; toasts: ${JSON.stringify(mockShowToast.mock.calls)}`);
    }
  });
  expect(mockStartRun).toHaveBeenCalledTimes(1);
  const [projectId, body] = mockStartRun.mock.calls[0];
  return { projectId, body };
}

beforeEach(() => {
  mockGetProject.mockResolvedValue(loadResponse());
  mockUpdateProject.mockImplementation(async (id: string) => ({
    id, name: 'Tuple reopen', spec_revision: 4, spec: spec(), categories: {}, outputs: [],
  }));
  mockStartRun.mockImplementation(async (projectId: string, body: any) => ({
    id: 'run-1', projectId, projectName: null, trigger: 'node', targetNodeId: body?.target ?? null,
    wholeDataflow: false, rerunOf: null, specRevision: body?.specRevision ?? null, status: 'running',
    createdAt: null, startedAt: null, finishedAt: null,
    counts: { ok: 0, failed: 0, skipped: 0, waiting: 0 }, error: null, live: true, steps: [],
  }));
});

afterEach(() => {
  jest.clearAllMocks();
});

describe('reopening a saved dataflow', () => {
  test('keeps the outputs its load restored', async () => {
    await reopen(SIGNED_IN);

    expect(api.outputs).toEqual([{ nodeId: PRODUCER, output: RESTORED }]);
  });

  test('a play below a restored node runs that node only, in the browser', async () => {
    // Nobody signed in: the canvas runs its plays itself.
    await reopen(null);

    await act(async () => {
      api.playNodesUpTo(CONSUMER);
    });
    await flush();

    expect(mockStartRun).not.toHaveBeenCalled();
    expect(triggerExecOf(PRODUCER)).toBe(0);
    expect(triggerExecOf(CONSUMER)).toBe(1);

    // Stop the walk so its watchdog does not outlive the test.
    await act(async () => {
      api.cancelRun();
    });
  });

  test('a play below a restored node runs that node only, on the server', async () => {
    await reopen(SIGNED_IN);

    const { projectId, body } = await playOnServer(CONSUMER);

    expect(projectId).toBe(PROJECT_ID);
    expect(body.target).toBe(CONSUMER);
    // The server runs every ancestor of the target not handed over here, so
    // without the producer's saved output it runs the producer again.
    expect(body.reuse).toEqual({ [PRODUCER]: RESTORED });
  });

  test('the save before that play keeps the restored output in the manifest', async () => {
    await reopen(SIGNED_IN);

    await playOnServer(CONSUMER);

    // A save names the outputs its canvas holds, the restored one among them.
    expect(mockUpdateProject).toHaveBeenCalled();
    const [savedId, saved] = mockUpdateProject.mock.calls[mockUpdateProject.mock.calls.length - 1];
    expect(savedId).toBe(PROJECT_ID);
    expect(saved.outputs).toEqual([
      expect.objectContaining({ node_id: PRODUCER, filename: PRODUCER_FILE, data_type: 'outputs' }),
    ]);
  });
});
