import { renderHook, act } from '@testing-library/react';

/**
 * dev/136: compiling is not drawing.
 *
 * The owner's report — "Vega-Lite and Autark nodes render empty plots" — with
 * the mechanism: `applyGrammar` reported `success` whatever the view drew, so
 * a chart over zero rows (axes and nothing else) and a chart whose encoded
 * field is entirely null (an empty panel) both landed as a green *Done*, and
 * since dev/135 both were journaled as `ok` — telling the harness the node
 * was fine.
 */

let mockCounts: unknown = { rowsIn: 3, drawn: 3 };
const mockCompile = jest.fn(async () => mockCounts);
const mockToasts: Array<[string, string]> = [];

// The behavior reads its incoming edges to decide the empty state, which
// needs React Flow's store; this suite renders the hook bare.
jest.mock('reactflow', () => ({ useEdges: () => [{ source: 'up', target: 'vega-1' }] }));

jest.mock('../../../hook/useVega', () => ({
  useVega: () => ({ handleCompileGrammar: mockCompile }),
}));

jest.mock('../../../providers/ToastProvider', () => ({
  useToastContext: () => ({
    showToast: (message: string, kind: string) => {
      mockToasts.push([message, kind]);
    },
  }),
}));

import { useVegaBehavior } from '../../../adapters/node/vegaBehavior';

const SPEC = '{"mark": "bar"}';

async function applyWith(nextCounts: unknown) {
  mockCounts = nextCounts;
  mockToasts.length = 0;
  const setOutput = jest.fn();
  const data: any = { nodeId: 'vega-1', input: '', outputCallback: jest.fn() };
  const nodeState: any = { code: SPEC, setOutput, templateData: { code: SPEC } };
  let hook: any;
  await act(async () => {
    hook = renderHook(() => useVegaBehavior(data, nodeState)).result;
  });
  await act(async () => {
    await hook.current.applyGrammar(SPEC);
  });
  return setOutput.mock.calls.map((c) => c[0]);
}

describe('useVegaBehavior — an empty plot is a failed render', () => {
  test('a chart over zero rows is an ERROR that names the upstream', async () => {
    const outputs = await applyWith({ rowsIn: 0, drawn: 0 });
    expect(outputs[0].code).toBe('error');
    expect(outputs[0].content).toContain('0 rows arrived');
    expect(outputs[0].content).toContain('not at fault');
    expect(mockToasts[0][1]).toBe('error');
  });

  test('rows in and no mark drawn is an ERROR that blames the document', async () => {
    const outputs = await applyWith({ rowsIn: 12, drawn: 0 });
    expect(outputs[0].code).toBe('error');
    expect(outputs[0].content).toContain('12 rows arrived');
    expect(outputs[0].content).toContain('encoding');
  });

  test('a chart that drew marks is a success, exactly as before', async () => {
    const outputs = await applyWith({ rowsIn: 12, drawn: 12 });
    expect(outputs[0]).toEqual({ code: 'success', content: '', outputType: '' });
    expect(mockToasts).toHaveLength(0);
  });

  test('an uncountable render makes no claim and stays a success', async () => {
    // `countDrawnMarks` returns undefined when the scene graph cannot be read.
    const outputs = await applyWith({ rowsIn: 12, drawn: undefined });
    expect(outputs[0].code).toBe('success');
    const legacy = await applyWith(undefined);
    expect(legacy[0].code).toBe('success');
  });

  test('a compile failure is still reported as its own error', async () => {
    mockCounts = { rowsIn: 1, drawn: 1 };
    mockCompile.mockRejectedValueOnce(new Error('outputs is not a valid input type'));
    const setOutput = jest.fn();
    const data: any = { nodeId: 'vega-1', input: '', outputCallback: jest.fn() };
    let hook: any;
    await act(async () => {
      hook = renderHook(() =>
        useVegaBehavior(data, { code: SPEC, setOutput, templateData: { code: SPEC } } as any),
      ).result;
    });
    await act(async () => {
      await hook.current.applyGrammar(SPEC);
    });
    expect(setOutput.mock.calls[0][0]).toEqual({
      code: 'error',
      content: 'outputs is not a valid input type',
      outputType: '',
    });
  });
});
