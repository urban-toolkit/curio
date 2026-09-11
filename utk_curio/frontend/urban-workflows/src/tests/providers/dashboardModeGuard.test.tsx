/**
 * Dashboard Mode with nothing pinned used to blank the app (#192).
 *
 * Two defects compounded. `MainCanvas` passed the SAME handler to two props and
 * `UpMenu` called both, so every click ran the toggle twice. And on entry
 * `applyDashboardLayout` returns the nodes untouched when no node is pinned,
 * after which every node is given `display: none`, every edge is hidden, and
 * `{!dashboardOn && <UpMenu>}` removes the top bar — so the screen went empty
 * with only DashboardPanel's ✕ left to escape by.
 *
 * Drives the REAL FlowProvider inside a real ReactFlowProvider, the harness
 * `mergeFlowPropagation.test.tsx` established, because the guard lives in
 * `setDashBoardMode` and reads state the provider owns.
 */
import React from 'react';
import fs from 'fs';
import path from 'path';
import { render, act } from '@testing-library/react';
import { ReactFlow, ReactFlowProvider } from 'reactflow';

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

jest.mock('../../hook/useWorkflowOperations', () => ({
  useWorkflowOperations: () => ({
    markNodeExecuted: jest.fn(),
    markNodeStale: jest.fn(),
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
  }),
}));

const mockShowToast = jest.fn();
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
import { CURIO_UNIVERSAL_NODE_TYPE } from '../../constants';

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

function makeNode(id: string) {
  return {
    id,
    type: CURIO_UNIVERSAL_NODE_TYPE,
    position: { x: 0, y: 0 },
    data: { nodeId: id, nodeType: 'curio.builtin/data-pool@1', input: '', inputTypes: [] },
  } as any;
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

async function addNodes(ids: string[]) {
  await act(async () => {
    ids.forEach((id) => api.addNode(makeNode(id), undefined, false));
  });
  await flush();
}

/** Every node currently hidden by the dashboard's `display: none`. */
function hiddenNodeIds(): string[] {
  return api.nodes
    .filter((n: any) => n.style?.display === 'none')
    .map((n: any) => n.id);
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe('entering Dashboard Mode with nothing pinned', () => {
  test('is refused, and the canvas is left exactly as it was', async () => {
    renderFlow();
    await addNodes(['a', 'b']);

    await act(async () => {
      api.setDashBoardMode(true);
    });
    await flush();

    expect(api.dashboardOn).toBe(false);
    // The reported symptom: every node hidden behind a menu-less screen.
    expect(hiddenNodeIds()).toEqual([]);
  });

  test('says what to do about it', async () => {
    renderFlow();
    await addNodes(['a']);

    await act(async () => {
      api.setDashBoardMode(true);
    });
    await flush();

    expect(mockShowToast).toHaveBeenCalledWith(
      'Pin at least one node to the dashboard first.',
      'warning',
    );
  });

  test('leaves the edges visible, so exiting is not required to see the flow', async () => {
    renderFlow();
    await addNodes(['a', 'b']);

    await act(async () => {
      api.setDashBoardMode(true);
    });
    await flush();

    expect(api.edges.every((e: any) => !e.hidden)).toBe(true);
  });
});

describe('entering Dashboard Mode with a node pinned', () => {
  test('succeeds, and hides only the unpinned nodes', async () => {
    renderFlow();
    await addNodes(['a', 'b']);

    await act(async () => {
      api.setPinForDashboard('a', true);
    });
    await flush();

    await act(async () => {
      api.setDashBoardMode(true);
    });
    await flush();

    expect(api.dashboardOn).toBe(true);
    expect(hiddenNodeIds()).toEqual(['b']);
    // No refusal toast on the path that should work.
    expect(mockShowToast).not.toHaveBeenCalledWith(
      expect.stringContaining('Pin at least one node'),
      expect.anything(),
    );
  });

  test('leaving restores every node', async () => {
    renderFlow();
    await addNodes(['a', 'b']);

    await act(async () => {
      api.setPinForDashboard('a', true);
    });
    await flush();
    await act(async () => {
      api.setDashBoardMode(true);
    });
    await flush();
    await act(async () => {
      api.setDashBoardMode(false);
    });
    await flush();

    expect(api.dashboardOn).toBe(false);
    expect(hiddenNodeIds()).toEqual([]);
  });
});

describe('the toggle is wired once, not twice', () => {
  // Source-level, because the double call is a wiring shape rather than an
  // observable state difference: both props held the SAME handler, so running
  // it twice per click left `dashboardOn` looking correct while every side
  // effect (layout, pin positions, edge hiding) ran twice.
  const read = (rel: string) =>
    fs.readFileSync(path.resolve(__dirname, '../..', rel), 'utf8');

  test('MainCanvas passes one dashboard setter to UpMenu', () => {
    const src = read('components/MainCanvas.tsx');
    expect(src).toContain('setDashBoardMode={handleDashboardToggle}');
    expect(src).not.toContain('setDashboardOn={handleDashboardToggle}');
  });

  test('UpMenu neither declares nor calls a second setter', () => {
    const src = read('components/menus/top/UpMenu.tsx');
    expect(src).not.toContain('setDashboardOn');
  });
});
