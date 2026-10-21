/**
 * Auto-run through the real FlowProvider (#845). Where Run All runs on the
 * server (a signed-in owner's dataflow), a widget or Parameter change runs the
 * touched nodes through that same start. Where it does not (a hosted guest, a
 * dashboard), auto-run is not offered and runs nothing. A brush that rewrites
 * a selection tag marks its node stale, as before, and runs nothing: brushing
 * never re-runs a Python node. Built like hostedGuestRuns.test.tsx.
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

const mockStartRun = jest.fn().mockResolvedValue(undefined);
const mockMarkNodeStale = jest.fn();

jest.mock('../../providers/flow/useServerRun', () => ({
  ...jest.requireActual('../../providers/flow/useServerRun'),
  useServerRun: () => ({
    startRun: mockStartRun,
    stopRun: jest.fn(),
    detachRun: jest.fn(),
    attachLatestRun: jest.fn().mockResolvedValue(undefined),
    serverRunActive: false,
  }),
}));

jest.mock('../../hook/useWorkflowOperations', () => ({
  useWorkflowOperations: () => ({
    markNodeExecuted: jest.fn(),
    markNodeStale: mockMarkNodeStale,
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
    loadProject: jest.fn().mockResolvedValue(undefined),
    loadSharedProject: jest.fn().mockResolvedValue(undefined),
    cleanCanvas: jest.fn(),
    discardProject: jest.fn(),
    viewerMode: 'owner',
    requestProjectSave: jest.fn().mockResolvedValue(undefined),
    surfaceInstallWarnings: jest.fn(),
    // The dataflow has "Run stale nodes automatically" on.
    autoRun: true,
    setAutoRun: jest.fn(),
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
import { AUTO_RUN_SETTLE_MS } from '../../providers/flow/useAutoRun';
import { VisInteractionType } from '../../constants';
import { objectRows } from '../../utils/selectionMatch';
import { provideViewRows, resetViewSelections } from '../../utils/references/viewSelections';
import { runKeyWithShared } from '../../utils/references/sharedParameters';

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

/** Longer than a change takes to settle. */
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, AUTO_RUN_SETTLE_MS + 200));
  });
}

const CODE = 'return input_0[input_0.osm_id.isin([!! selection picked !!])]';
const TAG = { name: 'picked', node: 'chart', column: 'osm_id', ids: [101] };

async function renderFlow(value: UserContextValue, { dashboardOn = false } = {}) {
  render(
    <UserContext.Provider value={value}>
      <ReactFlowProvider>
        <FlowProvider dashboardOn={dashboardOn}>
          <Bridge />
        </FlowProvider>
      </ReactFlowProvider>
    </UserContext.Provider>,
  );
  await flush();
  await act(async () => {
    api.addNode(
      {
        id: 'chart',
        type: 'curio.builtin/vis-vega',
        position: { x: 0, y: 0 },
        data: { nodeId: 'chart', nodeType: 'curio.builtin/vis-vega' },
      } as any,
      undefined,
      false,
    );
    api.addNode(
      {
        id: 'counter',
        type: 'curio.builtin/computation-analysis',
        position: { x: 0, y: 300 },
        data: {
          nodeId: 'counter',
          nodeType: 'curio.builtin/computation-analysis',
          code: CODE,
          selections: [TAG],
          output: { code: 'success' },
          executedCode: runKeyWithShared(CODE, undefined, [], [TAG]),
        },
      } as any,
      undefined,
      false,
    );
  });
  await flush();
}

const brush = (low: number, high: number) => ({
  brush: { type: VisInteractionType.INTERVAL, data: { height: [low, high] }, priority: 1 },
});

beforeEach(() => {
  provideViewRows('chart', () => ({
    rows: objectRows([
      { osm_id: 101, height: 10 },
      { osm_id: 102, height: 30 },
      { osm_id: 103, height: 50 },
    ]),
    columns: ['osm_id', 'height'],
  }));
});

afterEach(() => {
  resetViewSelections();
  jest.clearAllMocks();
});

describe("a signed-in owner's dataflow", () => {
  it('offers auto-run, and a change runs its nodes once, through the start Run All uses (#845)', async () => {
    await renderFlow(userContext(SIGNED_IN, true));
    expect(api.autoRunAvailable).toBe(true);
    expect(api.autoRun).toBe(true);

    await act(async () => {
      api.requestAutoRun(['counter']);
      api.requestAutoRun(['counter']);
    });
    expect(mockStartRun).not.toHaveBeenCalled();
    await settle();

    expect(mockStartRun).toHaveBeenCalledTimes(1);
    expect(mockStartRun).toHaveBeenCalledWith(['counter']);
  });

  it('a brush that rewrites a selection tag marks its node stale and runs nothing (#845)', async () => {
    await renderFlow(userContext(SIGNED_IN, true));

    await act(async () => {
      api.interactionsCallback(brush(20, 60), 'chart');
    });
    await waitFor(() => {
      const counter: any = api.nodes.find((n: any) => n.id === 'counter');
      expect(counter.data.selections[0].ids).toEqual([102, 103]);
    });
    expect(mockMarkNodeStale).toHaveBeenCalledWith('counter');
    await settle();

    expect(mockStartRun).not.toHaveBeenCalled();
  });
});

describe.each([
  ['a hosted guest', userContext(GUEST, true), false],
  ['a dashboard', userContext(SIGNED_IN, true), true],
])('%s', (_where, value, dashboardOn) => {
  it('is not offered auto-run, and a change runs nothing (#845)', async () => {
    await renderFlow(value, { dashboardOn });
    expect(api.autoRunAvailable).toBe(false);

    await act(async () => {
      api.requestAutoRun(['counter']);
    });
    await settle();

    expect(mockStartRun).not.toHaveBeenCalled();
    const counter: any = api.nodes.find((n: any) => n.id === 'counter');
    expect(counter?.data?.triggerExec ?? 0).toBe(0);
  });
});
