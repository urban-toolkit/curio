/**
 * Where an invited editor's runs go. On the owner's dataflow, an editor's Run
 * All and a node's play start a run on the server (`runsApi.start`) of the
 * dataflow the link opened, as the owner's start a run of the dataflow the
 * owner saves, and the editor's canvas follows the editor's last run of it.
 * The editor's tab makes no dataflow: the dataflow's id is the one its route
 * opened (`agentsDataflowId`). A watcher's run stays in the browser.
 *
 * The canvas opens the dataflow as `ProjectLoader` does: the route's id in the
 * opened store (`setCurrentProject`), then `loadProject` for the owner, or
 * `loadSharedProject` for anyone else, whose role the room names. The REAL
 * FlowProvider, useWorkflowOperations and useServerRun, with the projects and
 * runs APIs stubbed, as runEndSaveNamesOutput.test.tsx drives them.
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
const mockGetShared = jest.fn();
const mockCreateProject = jest.fn();
const mockRecordOutputs = jest.fn();
const mockStartRun = jest.fn();
const mockFollowRun = jest.fn();
const mockListRuns = jest.fn();
/** The role the dataflow's room gives this tab once its join answered. */
let mockRole: 'owner' | 'editor' | 'watcher' | null = null;

jest.mock('../../api/projectsApi', () => {
  const actual = jest.requireActual('../../api/projectsApi');
  return {
    ...actual,
    projectsApi: {
      ...actual.projectsApi,
      get: (...args: any[]) => mockGetProject(...args),
      getShared: (...args: any[]) => mockGetShared(...args),
      create: (...args: any[]) => mockCreateProject(...args),
      recordOutputs: (...args: any[]) => mockRecordOutputs(...args),
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
      listForProject: (...args: any[]) => mockListRuns(...args),
    },
  };
});

jest.mock('../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));

jest.mock('../../providers/CollaborationProvider', () => ({
  useCollab: () => ({
    lockedNodes: {},
    lockNode: jest.fn(),
    unlockNode: jest.fn(),
    onRemote: jest.fn(),
    connected: true,
    role: mockRole,
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
import { clearCurrentProject, setCurrentProject } from '../../registry/projectPackagesStore';
import type { UserData } from '../../utils/authApi';
import type { Run, RunEvent } from '../../services/runs/runsApi';

/** The owner's dataflow, which every canvas here opens by its link. */
const OWNERS_FLOW = 'owners-flow';
const NODE_TYPE = 'curio.builtin/computation-analysis';

function spec() {
  return {
    dataflow: {
      name: "Ada's dataflow",
      task: '',
      nodes: [{ id: 'A', type: `${NODE_TYPE}@1`, x: 10, y: 0, content: 'return 42\n' }],
      edges: [],
    },
  };
}

function loaded() {
  return {
    project: {
      id: OWNERS_FLOW, name: "Ada's dataflow", spec_revision: 3,
      updated_at: '2026-10-29T08:00:00Z', categories: {},
    },
    spec: spec(),
    outputs: [],
  };
}

function aRun(runId: string, target: string | null): Run {
  return {
    id: runId, projectId: OWNERS_FLOW, projectName: "Ada's dataflow", trigger: target ? 'node' : 'all',
    targetNodeId: target, wholeDataflow: !target, rerunOf: null, specRevision: 3,
    status: 'running', createdAt: null, startedAt: null, finishedAt: null,
    counts: { ok: 0, failed: 0, skipped: 0, waiting: 0 }, error: null, live: true,
    steps: [{
      nodeId: 'A', label: 'Python Computation', nodeType: NODE_TYPE, level: 0,
      role: 'run', status: 'pending', startedAt: null, finishedAt: null, durationMs: null,
      outputPath: null, outputType: null, installedDatasetId: null, codeSha256: null,
      stdoutTail: null, stderrTail: null, skipReason: null,
    }],
  };
}

type UserContextValue = React.ContextType<typeof UserContext>;

/** The account signed in on every canvas here: the owner's, or that of an
 * editor or a watcher of the owner's dataflow, as the room names it. */
const SIGNED_IN_USER: UserData = {
  id: 7,
  username: 'bea',
  name: 'Bea',
  email: null,
  profile_image: null,
  type: null,
  is_guest: false,
};

const SIGNED_IN: UserContextValue = {
  user: SIGNED_IN_USER,
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

/** The owner's dataflow opened by its link, on the canvas of *role*. */
async function openAs(role: 'owner' | 'editor' | 'watcher') {
  mockRole = role;
  setCurrentProject(OWNERS_FLOW, []);
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
    const result = role === 'owner'
      ? await api.loadProject(OWNERS_FLOW)
      : await api.loadSharedProject(OWNERS_FLOW);
    code.loadTrill(result.spec, undefined, undefined, {});
  });
  await flush();
  expect(api.viewerMode).toBe(role === 'owner' ? 'owner' : 'shared');
  expect(api.nodes.map((n: any) => n.id)).toEqual(['A']);
}

beforeEach(() => {
  clearCurrentProject();
  mockRole = null;
  mockGetProject.mockResolvedValue(loaded());
  mockGetShared.mockResolvedValue(loaded());
  mockListRuns.mockResolvedValue([]);
  mockFollowRun.mockImplementation((_runId: string, _onEvent: (event: RunEvent) => void, signal?: AbortSignal) =>
    new Promise<void>((resolve) => signal?.addEventListener('abort', () => resolve())));
});

afterEach(() => {
  jest.clearAllMocks();
});

describe("an invited editor's canvas", () => {
  it("runs the owner's dataflow on the server: Run All starts a run of the dataflow its link opened", async () => {
    await openAs('editor');
    mockStartRun.mockResolvedValueOnce(aRun('run-all', null));

    await act(async () => {
      api.playAllNodes();
    });
    await waitFor(() => expect(mockStartRun).toHaveBeenCalledTimes(1));

    expect(mockStartRun).toHaveBeenCalledWith(OWNERS_FLOW, {});
    await waitFor(() => expect(mockFollowRun).toHaveBeenCalledWith('run-all', expect.any(Function), expect.anything()));
    expect(api.serverRunActive).toBe(true);
    // Nothing ran in the browser, and the tab made no dataflow of its own.
    expect(api.isRunActive).toBe(false);
    expect(mockCreateProject).not.toHaveBeenCalled();
    expect(mockRecordOutputs).not.toHaveBeenCalled();
  });

  it('plays a node on the server, on the dataflow its link opened', async () => {
    await openAs('editor');
    mockStartRun.mockResolvedValueOnce(aRun('run-a', 'A'));

    await act(async () => {
      api.playNodesUpTo('A');
    });
    await waitFor(() => expect(mockStartRun).toHaveBeenCalledTimes(1));

    expect(mockStartRun).toHaveBeenCalledWith(OWNERS_FLOW, expect.objectContaining({ target: 'A' }));
    expect(api.isRunActive).toBe(false);
    expect(mockCreateProject).not.toHaveBeenCalled();
  });

  it("follows the editor's last run of the dataflow, and offers automatic runs", async () => {
    await openAs('editor');

    await waitFor(() => expect(mockListRuns).toHaveBeenCalledWith(OWNERS_FLOW, { limit: 1, mine: true }));
    expect(mockListRuns).toHaveBeenCalledTimes(1);
    expect(api.autoRunAvailable).toBe(true);
  });
});

describe("the owner's canvas", () => {
  it('runs on the server as before: Run All starts a run of the dataflow it saves', async () => {
    await openAs('owner');
    mockStartRun.mockResolvedValueOnce(aRun('run-all', null));

    await act(async () => {
      api.playAllNodes();
    });
    await waitFor(() => expect(mockStartRun).toHaveBeenCalledTimes(1));

    expect(mockStartRun).toHaveBeenCalledWith(OWNERS_FLOW, {});
    expect(api.isRunActive).toBe(false);
    expect(api.autoRunAvailable).toBe(true);
    expect(mockCreateProject).not.toHaveBeenCalled();
  });
});

describe("a watcher's canvas", () => {
  it('runs in the browser, and never on the server', async () => {
    await openAs('watcher');

    await act(async () => {
      api.playAllNodes();
    });
    await flush();

    expect(mockStartRun).not.toHaveBeenCalled();
    expect(api.isRunActive).toBe(true);
    expect(api.autoRunAvailable).toBe(false);
    expect(mockListRuns).not.toHaveBeenCalled();
    // Stop the run in the browser so its watchdog does not outlive the test.
    await act(async () => {
      api.cancelRun();
    });
    expect(api.isRunActive).toBe(false);
  });
});
