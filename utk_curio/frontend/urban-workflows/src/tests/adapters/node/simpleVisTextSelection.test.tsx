/**
 * Error text in a node must be selectable and copyable (#267).
 *
 * react-flow sets `user-select: none` on `.react-flow__node` so a drag inside a
 * node pans it rather than selecting text. Simple View's text/error pane
 * inherited that, so the one string a user most needs to hand to an agent - the
 * traceback from a failed upstream node - could not be highlighted at all. The
 * reporter's workaround was retyping it.
 *
 * `OutputContent` and `CodeEditor` already solve this with `userSelect: "text"`
 * plus `nodrag`; the pane here is where several nodes' errors land
 * (spatialJoinBehavior, dataExportBehavior, UniversalNode all route through
 * `setOutput({code: 'error'})`), so it is the one surface worth pinning.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import { useSimpleVisBehavior } from '../../../adapters/node/simpleVisBehavior';

jest.mock('reactflow', () => ({ useEdges: () => [{ source: 'up', target: 'sv-1' }] }));
jest.mock('../../../providers/ProvenanceProvider', () => ({
  useProvenanceContext: () => ({ nodeExecProv: jest.fn() }),
}));
jest.mock('../../../providers/FlowProvider', () => ({
  useFlowContext: () => ({ workflowNameRef: { current: 'wf' }, updateDataNode: jest.fn() }),
}));
jest.mock('../../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock('../../../services/api', () => ({ fetchData: jest.fn() }));
jest.mock('../../../utils/backendUrl', () => ({ backendUrl: () => 'http://backend.test' }));
jest.mock('../../../utils/authApi', () => ({ getToken: () => 'tok-123' }));

const nodeState = { setOutput: jest.fn() } as any;

function Harness({ data }: { data: any }) {
  const { contentComponent } = useSimpleVisBehavior(data, nodeState);
  return <>{contentComponent}</>;
}

const TRACEBACK =
  'Traceback (most recent call last):\n  File "<node>", line 3\nConnectionResetError: [Errno 104]';

function errorData() {
  return {
    nodeId: 'sv-1',
    input: { dataType: 'str', data: TRACEBACK },
    outputCallback: jest.fn(),
    interactionsCallback: jest.fn(),
  };
}

describe('Simple View text pane', () => {
  beforeEach(() => jest.clearAllMocks());

  it('renders the upstream error text', () => {
    render(<Harness data={errorData()} />);
    expect(screen.getByText(/ConnectionResetError/)).toBeInTheDocument();
  });

  it('lets the user select the text', () => {
    render(<Harness data={errorData()} />);
    const pane = screen.getByText(/ConnectionResetError/);
    expect(pane).toHaveStyle({ userSelect: 'text' });
  });

  it('does not let a drag inside the text pan the canvas', () => {
    // Without `nodrag`, react-flow claims the mousedown for a node drag and the
    // selection gesture never starts - so userSelect alone is not enough.
    render(<Harness data={errorData()} />);
    const pane = screen.getByText(/ConnectionResetError/);
    expect(pane.className).toContain('nodrag');
  });

  it('exposes the pane to e2e through a data attribute', () => {
    render(<Harness data={errorData()} />);
    expect(document.querySelector('[data-curio-node-text]')).not.toBeNull();
  });

  it('offers a copy control for the text', () => {
    render(<Harness data={errorData()} />);
    expect(screen.getByLabelText(/copy/i)).toBeInTheDocument();
  });
});
