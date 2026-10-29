/**
 * A saved dataflow whose node still carries comments (`metadata.comments`)
 * opens without them, and what the canvas sends of it writes none. The load
 * neither refuses the dataflow nor migrates it: the key stays behind, and the
 * rest of the node comes through.
 *
 * The dataflow is reopened as `ProjectLoader` opens it, `loadProject` and then
 * `useCode().loadTrill`, with the harness of `reopenKeepsRestoredOutputs.test.tsx`.
 * No tab saves the dataflow: the doc writes what the canvas changes, through
 * the serializer a dataflow made from the canvas goes through, which Save a
 * copy is.
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

const mockShowToast = jest.fn();
const mockGetProject = jest.fn();
const mockUpdateProject = jest.fn();
const mockCreateProject = jest.fn();

jest.mock('../../api/projectsApi', () => {
  const actual = jest.requireActual('../../api/projectsApi');
  return {
    ...actual,
    projectsApi: {
      ...actual.projectsApi,
      get: (...args: any[]) => mockGetProject(...args),
      update: (...args: any[]) => mockUpdateProject(...args),
      create: (...args: any[]) => mockCreateProject(...args),
    },
  };
});

jest.mock('../../services/runs/runsApi', () => {
  const actual = jest.requireActual('../../services/runs/runsApi');
  return {
    ...actual,
    runsApi: {
      ...actual.runsApi,
      // Nothing here runs; a run that started anyway would wait forever.
      start: jest.fn(() => new Promise<void>(() => {})),
      follow: () => new Promise<void>(() => {}),
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

const PROJECT_ID = 'commented-reopen';
const NODE_TYPE = 'curio.builtin/computation-analysis';
const DISCUSSED = 'discussed-node';
const PLAIN = 'plain-node';
/** A renamed header, saved beside the comments, which the load keeps. */
const LABEL = 'Clean the parcels';

/** A comment as the canvas wrote it to `metadata.comments`. */
const SAVED_COMMENT = {
  id: 'c-1',
  text: 'check the CRS before the join',
  author: 'ada',
  authorName: 'Ada',
  createdAt: '2026-08-30T12:00:00.000Z',
  resolved: false,
};

function spec() {
  return {
    dataflow: {
      name: 'Commented reopen',
      task: '',
      nodes: [
        {
          id: DISCUSSED, type: NODE_TYPE, x: 0, y: 0, content: 'return 1\n',
          metadata: { packageTemplateLabel: LABEL, comments: [SAVED_COMMENT] },
        },
        { id: PLAIN, type: NODE_TYPE, x: 645, y: 0, content: 'return input_0\n' },
      ],
      edges: [{
        id: `${DISCUSSED}->${PLAIN}`, source: DISCUSSED, target: PLAIN,
        sourceHandle: 'out', targetHandle: 'in',
      }],
    },
  };
}

/** What `GET /api/projects/<id>` answers. */
function loadResponse() {
  return {
    project: {
      id: PROJECT_ID, name: 'Commented reopen', spec_revision: 3,
      updated_at: '2026-10-17T08:00:00Z', categories: {},
    },
    spec: spec(),
    outputs: [],
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

/** Signed in, on the dataflow's own canvas. */
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

/** Open the saved dataflow on a fresh canvas, as `ProjectLoader` does. */
async function reopen() {
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
    code.loadTrill(result.spec);
  });
  await flush();

  // The load built the canvas: nothing refused the dataflow.
  expect(api.nodes.map((n: any) => n.id).sort()).toEqual([DISCUSSED, PLAIN].sort());
  expect(api.edges.map((e: any) => [e.source, e.target])).toEqual([[DISCUSSED, PLAIN]]);
}

const loadedNode = (id: string) => api.nodes.find((n: any) => n.id === id) as any;

beforeEach(() => {
  mockGetProject.mockResolvedValue(loadResponse());
  mockUpdateProject.mockImplementation(async (id: string) => ({
    id, name: 'Commented reopen', spec_revision: 4, spec: spec(), categories: {}, outputs: [],
  }));
  mockCreateProject.mockImplementation(async (body: any) => ({
    id: 'the-copy', name: body.name, spec_revision: 1, spec: body.spec, categories: {}, outputs: [],
  }));
});

afterEach(() => {
  jest.clearAllMocks();
});

describe('a saved dataflow whose node carries comments', () => {
  test('opens without them, keeps the rest of the node, and reports no error', async () => {
    await reopen();

    const node = loadedNode(DISCUSSED);
    expect(node.data.packageTemplateLabel).toBe(LABEL);
    expect(mockShowToast.mock.calls.filter(([, kind]) => kind === 'error')).toEqual([]);
    // Checked last, so a canvas that still loads them fails here and nowhere earlier.
    expect(node.data).not.toHaveProperty('comments');
  });

  test('a dataflow made from it carries none of them', async () => {
    await reopen();

    await act(async () => {
      await api.saveAsNewProject('Commented reopen (copy)', PROJECT_ID);
    });

    expect(mockCreateProject).toHaveBeenCalledTimes(1);
    // No tab sends the dataflow it is open on.
    expect(mockUpdateProject).not.toHaveBeenCalled();
    const [sent] = mockCreateProject.mock.calls[0];
    const sentNode = sent.spec.dataflow.nodes.find((n: any) => n.id === DISCUSSED);
    expect(sentNode.metadata.packageTemplateLabel).toBe(LABEL);
    // Checked last, so a canvas that still sends them fails here and nowhere earlier.
    expect(sentNode.metadata).not.toHaveProperty('comments');
  });
});
