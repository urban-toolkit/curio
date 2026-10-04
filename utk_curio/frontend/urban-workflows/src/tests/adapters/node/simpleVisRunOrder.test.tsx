/**
 * A Simple View hands its rows downstream before it says it is done.
 *
 * Its outcome is what tells a Run All the node is done, and the run then
 * triggers the next level. Said first, the node it feeds (example 10's
 * Spatial Join) could be asked to run before it had the rows.
 */
import React from 'react';
import { act, render } from '@testing-library/react';
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

function Harness({ data, nodeState }: { data: any; nodeState: any }) {
  const { contentComponent } = useSimpleVisBehavior(data, nodeState);
  return <>{contentComponent}</>;
}

function frame(n: number) {
  return { dataType: 'dataframe', data: { name: Array.from({ length: n }, (_, i) => `p${i}`) } };
}

test('the rows go downstream before the outcome that ends the node', async () => {
  const order: string[] = [];
  const nodeState = { setOutput: jest.fn((o: any) => order.push(`outcome ${o.code}`)) } as any;
  const base = {
    nodeId: 'sv-1',
    outputCallback: jest.fn(() => order.push('rows downstream')),
    interactionsCallback: jest.fn(),
  };
  const { rerender } = render(<Harness data={{ ...base, input: frame(2) }} nodeState={nodeState} />);
  await act(async () => {
    rerender(<Harness data={{ ...base, input: frame(3) }} nodeState={nodeState} />);
  });
  const last = order.slice(-2);
  expect(last).toEqual(['rows downstream', 'outcome success']);
});
