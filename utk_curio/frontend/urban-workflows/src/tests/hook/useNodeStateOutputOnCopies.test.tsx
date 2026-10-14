/**
 * A node's outcome, and the run key that produced it, are mirrored onto its
 * data by mutation (hook/useNodeState, dev/70), which is where
 * `reactFlow.getNodes()`, `playNodesUpTo` and the scenario boxes read them.
 *
 * The flow replaces a node's data with a copy whenever it changes a field: an
 * input arriving, a step of a run on the server (`serverOutput`). A copy made
 * before the node applied its new outcome holds the outcome from before, and
 * the node renders with it after the mirror ran on the old object. On a run on
 * the server this is the usual order: the step's result and the input a Data
 * Pool hands on land together. The outcome and its run key go onto the copy.
 */
import { act, renderHook } from '@testing-library/react';

jest.mock('../../providers/StarterProvider', () => ({
  useStarterContext: () => ({ editUserStarter: jest.fn() }),
}));
jest.mock('../../providers/UserProvider', () => ({
  useUserContext: () => ({ user: null }),
}));
jest.mock('../../providers/FlowProvider', () => ({
  useFlowContext: () => ({ projectId: 'project', nodes: [] }),
}));
jest.mock('../../services/nodeRuntimeReport', () => ({
  reportFromNodeOutput: () => null,
  reportNodeRuntime: jest.fn(),
}));

import { useNodeState, type NodeOutput } from '../../hook/useNodeState';

const TYPE = 'curio.builtin/computation-analysis' as any;
const RESULT: NodeOutput = { code: 'success', content: 'stdout:\n7 removed.\nSaved to file: art-out' };

function mount(data: any) {
  return renderHook(({ data: current }) => useNodeState(current, TYPE), { initialProps: { data } });
}

test('a copy made before the result landed gets the result and its run key', () => {
  const before: any = { nodeId: 'edit', code: 'return input_0', output: { code: 'exec', content: '' } };
  const node = mount(before);
  // The flow copies the data (an input arriving) in the same moment the node
  // takes its result, so the copy predates the mirror.
  const copy: any = { ...before, input: { path: 'art-in', dataType: 'list' } };
  act(() => { node.result.current.setOutput(RESULT); });
  expect(before.output).toBe(RESULT);
  expect(copy.output.code).toBe('exec');

  node.rerender({ data: copy });

  expect(copy.output).toBe(RESULT);
  expect(typeof before.executedCode).toBe('string');
  expect(copy.executedCode).toBe(before.executedCode);
});

test('a copy made later keeps the result, and the next outcome reaches the copy in use', () => {
  const first: any = { nodeId: 'edit', code: 'return input_0', output: { code: '', content: '' } };
  const node = mount(first);
  act(() => { node.result.current.setOutput(RESULT); });
  const later: any = { ...first, input: { path: 'art-in', dataType: 'list' } };
  node.rerender({ data: later });
  expect(later.output).toBe(RESULT);
  expect(later.executedCode).toBe(first.executedCode);

  const running: NodeOutput = { code: 'exec', content: '' };
  act(() => { node.result.current.setOutput(running); });
  expect(later.output).toBe(running);
});

test('a node that never ran leaves its copies without a run key', () => {
  const first: any = { nodeId: 'edit', code: 'return input_0' };
  const node = mount(first);
  const copy: any = { ...first, input: { path: 'art-in', dataType: 'list' } };
  node.rerender({ data: copy });
  expect('executedCode' in copy).toBe(false);
  expect(copy.output).toEqual({ code: '', content: '', outputType: '' });
});
