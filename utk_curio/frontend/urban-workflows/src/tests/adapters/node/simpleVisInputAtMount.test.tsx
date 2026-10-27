/**
 * A Simple View shows an input it already has when it mounts.
 *
 * An input can reach the node before the node mounts: on a dashboard, a
 * tile's saved output lands as the page loads. The node read only the inputs
 * that came after it mounted, and the view it mounted with cannot read a path,
 * so a table whose input names its artifact stayed empty and idle: the Crown
 * Heights dashboard's months table, for one visitor on a GPU runner (10-27,
 * run 40545118565: "the table never showed the twelve months").
 *
 * Read at mount, the input is no new run: it is filed in no provenance and
 * sent no further, as a later input is.
 */
import React from 'react';
import { act, render } from '@testing-library/react';
import { useSimpleVisBehavior } from '../../../adapters/node/simpleVisBehavior';

const mockProvenance = jest.fn();
jest.mock('reactflow', () => ({ useEdges: () => [{ source: 'months', target: 'sv-1' }] }));
jest.mock('../../../providers/ProvenanceProvider', () => ({
  useProvenanceContext: () => ({ nodeExecProv: mockProvenance }),
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

const api = jest.requireMock('../../../services/api') as { fetchData: jest.Mock };

function Harness({ data, nodeState }: { data: any; nodeState: any }) {
  const { contentComponent } = useSimpleVisBehavior(data, nodeState);
  return <>{contentComponent}</>;
}

/** The months table's rows, as its artifact holds them. */
const MONTHS = { dataType: 'dataframe', data: { Month: { 0: 'January', 1: 'February' }, Added: { 0: '19 ± 4 min', 1: '2 ± 2 min' } } };
/** An input that names its artifact, as a saved output reaches a tile. */
const NAMED = { path: 'months-7', dataType: 'dataframe' };

function base() {
  return { nodeId: 'sv-1', outputCallback: jest.fn(), interactionsCallback: jest.fn() };
}

/** What the body says it is waiting for, or null when it shows what it has. */
function emptyReason(container: HTMLElement): string | null {
  return container.querySelector('[data-curio-node-empty]')?.getAttribute('data-curio-node-empty') ?? null;
}

beforeEach(() => {
  mockProvenance.mockClear();
  api.fetchData.mockReset();
});

test('it reads an input it mounts with that names its artifact, says Computing... until the rows are in, then shows them', async () => {
  let deliver: (value: unknown) => void = () => {};
  api.fetchData.mockImplementationOnce(() => new Promise((resolve) => { deliver = resolve; }));
  const nodeState = { setOutput: jest.fn() };
  const view = render(<Harness data={{ ...base(), input: NAMED }} nodeState={nodeState} />);
  await act(async () => {});

  expect(api.fetchData).toHaveBeenCalledWith('months-7');
  expect(emptyReason(view.container)).toBe('upstream-running');
  expect(view.container.textContent).toContain('Computing...');

  await act(async () => {
    deliver(MONTHS);
  });
  expect(emptyReason(view.container)).toBeNull();
  expect(view.container.textContent).toContain('February');
  expect(view.container.textContent).toContain('19 ± 4 min');
  expect(nodeState.setOutput).toHaveBeenLastCalledWith({ code: 'success', content: MONTHS });
});

test('read at mount, the input is filed in no provenance and sent no further; the next one is', async () => {
  api.fetchData.mockResolvedValue(MONTHS);
  const nodeState = { setOutput: jest.fn() };
  const data = base();
  const view = render(<Harness data={{ ...data, input: NAMED }} nodeState={nodeState} />);
  await act(async () => {});
  expect(view.container.textContent).toContain('February');
  expect(mockProvenance).not.toHaveBeenCalled();
  expect(data.outputCallback).not.toHaveBeenCalled();

  const next = { path: 'months-8', dataType: 'dataframe' };
  await act(async () => {
    view.rerender(<Harness data={{ ...data, input: next }} nodeState={nodeState} />);
  });
  expect(mockProvenance).toHaveBeenCalledTimes(1);
  expect(data.outputCallback).toHaveBeenCalledWith('sv-1', next);
});

test('an input it mounts with that carries its rows shows at once, with no read', async () => {
  const nodeState = { setOutput: jest.fn() };
  const view = render(<Harness data={{ ...base(), input: MONTHS }} nodeState={nodeState} />);
  expect(emptyReason(view.container)).toBeNull();
  expect(view.container.textContent).toContain('February');
  await act(async () => {});
  expect(api.fetchData).not.toHaveBeenCalled();
  expect(nodeState.setOutput).toHaveBeenLastCalledWith({ code: 'success', content: MONTHS });
});
