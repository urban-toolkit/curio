/**
 * Where Run All runs: on the server for whoever may save the dataflow, since a
 * run there saves it first; in the browser for a hosted guest
 * (`isHostedGuest`: a guest on a Curio started with --deploy), who cannot save
 * it. Without --deploy the shared guest is the one local user, saves, and so
 * runs on the server like a signed-in account. Drives the REAL FlowProvider the
 * way playAllRelease.test.tsx does, with the server run stubbed.
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

const mockStartRun = jest.fn().mockResolvedValue(undefined);
const mockAttachLatestRun = jest.fn().mockResolvedValue(undefined);
const mockPersistDataflowForInstall = jest.fn().mockResolvedValue(undefined);
const mockRequestProjectSave = jest.fn().mockResolvedValue(undefined);
const mockLoadProject = jest.fn().mockResolvedValue(undefined);
const mockLoadSharedProject = jest.fn().mockResolvedValue(undefined);
const mockCleanCanvas = jest.fn();
const mockDiscardProject = jest.fn();

jest.mock('../../providers/flow/useServerRun', () => ({
  ...jest.requireActual('../../providers/flow/useServerRun'),
  useServerRun: () => ({
    startRun: mockStartRun,
    stopRun: jest.fn(),
    detachRun: jest.fn(),
    attachLatestRun: mockAttachLatestRun,
    serverRunActive: false,
  }),
}));

jest.mock('../../hook/useWorkflowOperations', () => ({
  useWorkflowOperations: () => ({
    markNodeExecuted: jest.fn(),
    markNodeStale: jest.fn(),
    markDirty: jest.fn(),
    persistDataflowForInstall: mockPersistDataflowForInstall,
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
    loadProject: mockLoadProject,
    loadSharedProject: mockLoadSharedProject,
    cleanCanvas: mockCleanCanvas,
    discardProject: mockDiscardProject,
    // The viewer's own dataflow: the condition for a run on the server that
    // is not about who is signed in. Without it every run stays in the browser.
    viewerMode: 'owner',
    requestProjectSave: mockRequestProjectSave,
    surfaceInstallWarnings: jest.fn(),
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
import { UserContext } from '../../providers/userContext';
import type { UserData } from '../../utils/authApi';

type UserContextValue = React.ContextType<typeof UserContext>;

function userContext(user: UserData, enableUserAuth: boolean): UserContextValue {
  return {
    user,
    loading: false,
    isAuthenticated: true,
    enableUserAuth,
    skipProjectPage: false,
    allowGuest: true,
    sharedGuestUsername: 'guest_shared',
    isSharedGuest: user.is_guest && user.username === 'guest_shared',
    signup: async () => null,
    signin: async () => null,
    signinGuest: async () => null,
    signout: async () => {},
    updateProfile: async () => {},
    updateTokens: async () => {},
    saveUserType: async () => {},
    logout: () => {},
  };
}

const GUEST: UserData = {
  id: 1,
  username: 'guest_shared',
  name: 'Guest',
  email: null,
  profile_image: null,
  type: null,
  is_guest: true,
};
const SIGNED_IN: UserData = { ...GUEST, id: 2, username: 'ada', name: 'Ada', is_guest: false };

const HOSTED_GUEST = userContext(GUEST, true);
const LOCAL_GUEST = userContext(GUEST, false);
const SIGNED_IN_USER = userContext(SIGNED_IN, true);

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

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

/** The canvas as *value* sees it, holding one node ready to run. */
async function renderFlowAs(value: UserContextValue) {
  render(
    <UserContext.Provider value={value}>
      <ReactFlowProvider>
        <FlowProvider>
          <Bridge />
        </FlowProvider>
      </ReactFlowProvider>
    </UserContext.Provider>,
  );
  await flush();
  await act(async () => {
    api.addNode(
      {
        id: 'A',
        type: 'curio.builtin/data-loading',
        position: { x: 0, y: 0 },
        data: { nodeId: 'A', nodeType: 'curio.builtin/data-loading' },
      } as any,
      undefined,
      false,
    );
  });
  await flush();
}

async function runAll() {
  await act(async () => {
    api.playAllNodes();
  });
  await flush();
}

function triggerExecOf(id: string): number {
  const n = api.nodes.find((x: any) => x.id === id);
  return (n?.data?.triggerExec as number) ?? 0;
}

afterEach(() => {
  jest.clearAllMocks();
});

describe('a hosted guest', () => {
  it('runs the dataflow in the browser, and never on the server', async () => {
    await renderFlowAs(HOSTED_GUEST);

    await runAll();

    expect(mockStartRun).not.toHaveBeenCalled();
    expect(api.isRunActive).toBe(true);
    expect(triggerExecOf('A')).toBe(1);

    // Stop the run in the browser so its watchdog does not outlive the test.
    await act(async () => {
      api.cancelRun();
    });
    expect(api.isRunActive).toBe(false);
  });

  it('attaches to no run on the server', async () => {
    await renderFlowAs(HOSTED_GUEST);

    await act(async () => {
      await api.attachLatestRun('proj-1', new Set());
    });

    expect(mockAttachLatestRun).not.toHaveBeenCalled();
  });
});

describe.each([
  ['the local shared guest', LOCAL_GUEST],
  ['a signed-in account', SIGNED_IN_USER],
])('%s', (_who, value) => {
  it('runs the dataflow on the server, not in the browser', async () => {
    await renderFlowAs(value);

    await runAll();

    expect(mockStartRun).toHaveBeenCalledTimes(1);
    expect(api.isRunActive).toBe(false);
    expect(triggerExecOf('A')).toBe(0);
  });

  it('attaches to the run going on the server', async () => {
    await renderFlowAs(value);
    const restored = new Set<string>();

    await act(async () => {
      await api.attachLatestRun('proj-1', restored);
    });

    expect(mockAttachLatestRun).toHaveBeenCalledWith('proj-1', restored);
  });
});
