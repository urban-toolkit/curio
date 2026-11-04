/**
 * A connection this tab drew to a node someone removed meanwhile is taken out
 * by the server, which names who removed the node (`connection_dropped`,
 * `dataflow_docs._drop_dangling_connections`), and the canvas says so in a
 * toast. Every guest, and every tab of a Curio with no sign-in, signs in to
 * the one shared guest account, so a tab of it is named by its number, as its
 * chip in the dock, its cursor and its Activity lines name it.
 *
 * Drives the REAL FlowProvider, harness as in connectionFanInGuard.test.tsx,
 * with the room's events fired as the socket would, as in
 * collabInteractions.test.tsx.
 */
import React from 'react';
import { render, act } from '@testing-library/react';
import { ReactFlowProvider } from 'reactflow';

// jsdom polyfills ReactFlow needs.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(global as any).ResizeObserver = ResizeObserverStub;
if (!(global as any).DOMMatrixReadOnly) {
  (global as any).DOMMatrixReadOnly = class { m22 = 1; constructor() {} };
}

// Mocks: replace the heavy and IO collaborators, keep reactflow REAL.
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

// The room's events, by name: `onRemote` keeps each handler here, and the test
// fires them as the socket would. One object for every render, since the
// toast's effect depends on `onRemote`.
const mockHandlers: Record<string, (payload: any) => void> = {};
const mockNoop = () => undefined;
const mockCollab = {
  lockedNodes: {},
  lockNode: mockNoop,
  unlockNode: mockNoop,
  onRemote: (event: string, handler: (payload: any) => void) => {
    mockHandlers[event] = handler;
    return () => {
      if (mockHandlers[event] === handler) delete mockHandlers[event];
    };
  },
};
jest.mock('../../providers/CollaborationProvider', () => ({
  useCollab: () => mockCollab,
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

import FlowProvider from '../../providers/FlowProvider';
import { CONNECTION_DROPPED_EVENT } from '../../providers/collab/docContext';

/** The server took out this tab's connection to a node *by* removed: the
 *  toasts the canvas showed for it. */
function droppedBy(by: Record<string, unknown>): unknown[] {
  mockShowToast.mockClear();
  const handler = mockHandlers[CONNECTION_DROPPED_EVENT];
  expect(handler).toBeDefined();
  act(() => handler({ projectId: 'project-1', edgeIds: ['e2'], by }));
  return mockShowToast.mock.calls.map(([text]) => text);
}

afterEach(() => {
  for (const key of Object.keys(mockHandlers)) delete mockHandlers[key];
});

test("a connection not kept names a guest tab that removed the node by its number, and an account by its name", () => {
  render(
    <ReactFlowProvider>
      <FlowProvider>
        <div />
      </FlowProvider>
    </ReactFlowProvider>,
  );

  // The remover as the server names it (`dataflow_docs._user`).
  expect(droppedBy({
    participant_id: 'p-guest-2', user_id: 3, username: 'guest_shared', name: 'Shared Guest', role: 'owner',
    guest_number: 2,
  })).toEqual(["Shared Guest 2 removed that node, so this connection was not kept."]);
  expect(droppedBy({ participant_id: 'p-ana', user_id: 7, username: 'ana', name: 'Ana', role: 'owner' })).toEqual([
    "Ana removed that node, so this connection was not kept.",
  ]);
});
