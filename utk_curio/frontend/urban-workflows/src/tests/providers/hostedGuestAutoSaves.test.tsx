/**
 * A hosted guest (`isHostedGuest`: a guest on a Curio started with --deploy,
 * where every visitor shares the one guest account) cannot save the dataflow.
 * Only a save the guest asks for says so: File > Save and Save a copy
 * (useWorkflowOperations.hostedGuest.test.ts). The saves Curio makes on its
 * own are skipped without a word: the install save after a node's output
 * lands, and the save after a pin changes. On dev, a guest who opened a
 * shipped example and pressed a node's play or Run All was told "Guest users
 * cannot save projects" by the first of them.
 *
 * Without --deploy the shared guest is the one local user, and it saves like a
 * signed-in account. Drives the REAL FlowProvider the way
 * dashboardPresentation.test.tsx does, in the user context
 * hostedGuestRuns.test.tsx sets up.
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

/** How the save queue answers a hosted guest (`saveCurrentProject`). */
const GUEST_REFUSAL = 'Guest users cannot save projects';

const mockBeginPendingInstall = jest.fn();
const mockPersistDataflowForInstall = jest.fn();
const mockRequestProjectSave = jest.fn();
const mockShowToast = jest.fn();

jest.mock('../../hook/useWorkflowOperations', () => ({
  useWorkflowOperations: () => ({
    markNodeExecuted: jest.fn(),
    markNodeStale: jest.fn(),
    markNodeErrored: jest.fn(),
    markDirty: jest.fn(),
    persistDataflowForInstall: mockPersistDataflowForInstall,
    beginPendingInstall: mockBeginPendingInstall,
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
    loadProject: jest.fn(),
    loadSharedProject: jest.fn(),
    cleanCanvas: jest.fn(),
    discardProject: jest.fn(),
    requestProjectSave: mockRequestProjectSave,
    surfaceInstallWarnings: jest.fn(),
    // A saved dataflow of the viewer's own, as a shipped example is once it
    // has been seeded into the guest account: the pin's save needs both.
    projectId: 'project-1',
    viewerMode: 'owner',
  }),
}));

// Runs on the server are not what this is about, and a signed-in account
// would otherwise reach them.
jest.mock('../../providers/flow/useServerRun', () => ({
  ...jest.requireActual('../../providers/flow/useServerRun'),
  useServerRun: () => ({
    startRun: jest.fn(),
    stopRun: jest.fn(),
    detachRun: jest.fn(),
    attachLatestRun: jest.fn(),
    serverRunActive: false,
  }),
}));

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
    broadcastEdgeAdded: jest.fn(),
    broadcastEdgeRemoved: jest.fn(),
    broadcastNodeUpdated: jest.fn(),
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
import { UserContext } from '../../providers/userContext';
import { CURIO_UNIVERSAL_NODE_TYPE, NodeType } from '../../constants';
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
  await act(async () => { await Promise.resolve(); });
}

/** The canvas as *value* sees it. */
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
}

function makeNode(id: string, nodeType: string, data: Record<string, unknown> = {}) {
  return {
    id,
    type: CURIO_UNIVERSAL_NODE_TYPE,
    position: { x: 0, y: 0 },
    data: { nodeId: id, nodeType, input: '', inputTypes: [], ...data },
  } as any;
}

/** Connect two nodes the way a load does, with validation skipped (see dashboardPresentation.test.tsx). */
async function connect(source: string, target: string) {
  await act(async () => {
    api.onConnect(
      { source, target, sourceHandle: 'out', targetHandle: 'in' } as any,
      undefined, undefined, undefined, false, true,
    );
  });
  await flush();
}

/** A node whose own Save toggle is on, so its run's output is saved. */
async function addSavedProducer() {
  await act(async () => {
    api.addNode(makeNode('py', NodeType.COMPUTATION_ANALYSIS, { saveOutputDataset: true }), undefined, false);
  });
  await flush();
}

/** Its run's output landing, as a play or Run All in the browser hands it over. */
async function outputLands() {
  await act(async () => {
    api.applyNewOutput({ nodeId: 'py', output: { path: 'art_py', dataType: 'dataframe' } });
  });
  // Past the install save's debounce.
  await act(async () => { jest.advanceTimersByTime(600); });
  await flush();
}

/** A producer feeding a chart: pinning the chart has the producer's output saved. */
async function addChartFedByAProducer(pinned = false) {
  await act(async () => {
    api.addNode(makeNode('py', NodeType.COMPUTATION_ANALYSIS, { templateName: 'Load trips' }), undefined, false);
    api.addNode(makeNode('chart', NodeType.VIS_VEGA, pinned ? { dashboardPinned: true } : {}), undefined, false);
  });
  await flush();
  await connect('py', 'chart');
}

async function pinChart(value: boolean) {
  await act(async () => { api.setPinForDashboard('chart', value); });
  // Past the pin's debounce.
  await act(async () => { jest.advanceTimersByTime(500); });
  await flush();
}

function toastsShown(): string[] {
  return mockShowToast.mock.calls.map((call: any[]) => String(call[0]));
}

beforeEach(() => {
  jest.clearAllMocks();
  jest.useFakeTimers();
  mockPersistDataflowForInstall.mockResolvedValue({ saved: true, failedNodeIds: [] });
  mockRequestProjectSave.mockResolvedValue({ id: 'project-1' });
});

afterEach(() => {
  jest.useRealTimers();
});

describe('a hosted guest', () => {
  beforeEach(() => {
    // What the save queue does for a hosted guest.
    mockRequestProjectSave.mockRejectedValue(new Error(GUEST_REFUSAL));
  });

  it("asks for no save when a node's output lands, and says nothing", async () => {
    await renderFlowAs(HOSTED_GUEST);
    await addSavedProducer();

    await outputLands();

    // No "Adding..." placeholder for a dataset that will never be added, and
    // no install save, whose refusal was the toast on dev.
    expect(mockBeginPendingInstall).not.toHaveBeenCalled();
    expect(mockPersistDataflowForInstall).not.toHaveBeenCalled();
    expect(toastsShown()).toEqual([]);
  });

  it('asks for no save when a node is pinned, and says nothing', async () => {
    await renderFlowAs(HOSTED_GUEST);
    await addChartFedByAProducer();

    await pinChart(true);

    // Neither the pin's save, whose refusal read "Could not save the pin", nor
    // the note that the producer's output will be saved: for a guest it is not.
    expect(mockRequestProjectSave).not.toHaveBeenCalled();
    expect(toastsShown()).toEqual([]);
  });

  it('asks for no save when a node is unpinned either', async () => {
    await renderFlowAs(HOSTED_GUEST);
    await addChartFedByAProducer(true);

    await pinChart(false);

    expect(mockRequestProjectSave).not.toHaveBeenCalled();
    expect(toastsShown()).toEqual([]);
  });

  it('still shows the pin on the canvas', async () => {
    await renderFlowAs(HOSTED_GUEST);
    await addChartFedByAProducer();

    await pinChart(true);

    expect(api.dashboardPins.chart).toBe(true);
  });
});

describe.each([
  ['the local shared guest', LOCAL_GUEST],
  ['a signed-in account', SIGNED_IN_USER],
])('%s', (_who, value) => {
  it("saves a node's output when it lands", async () => {
    await renderFlowAs(value);
    await addSavedProducer();

    await outputLands();

    expect(mockBeginPendingInstall).toHaveBeenCalledWith(
      expect.objectContaining({ producerNodeId: 'py' }),
    );
    expect(mockPersistDataflowForInstall).toHaveBeenCalledWith(['py']);
  });

  it('saves a pin, and says which outputs will be saved', async () => {
    await renderFlowAs(value);
    await addChartFedByAProducer();

    await pinChart(true);

    expect(mockRequestProjectSave).toHaveBeenCalledTimes(1);
    expect(toastsShown().join(' ')).toContain('Data Catalog');
    expect(toastsShown().join(' ')).not.toContain('Could not save the pin');
  });

  it('saves an unpin', async () => {
    await renderFlowAs(value);
    await addChartFedByAProducer(true);

    await pinChart(false);

    expect(mockRequestProjectSave).toHaveBeenCalledTimes(1);
  });
});
