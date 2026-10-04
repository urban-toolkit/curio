/**
 * The Autark editor's starter must not fight the user (#157).
 *
 * #157 was a feedback loop: the override was derived from `data.code`, which
 * GrammarEditor writes back on every change (floatCode -> nodeState.setCode ->
 * useNodeState's `data.code = code` effect), so it flipped between the starter
 * and `undefined` on every render, and @monaco-editor/react's controlled value
 * replaced the whole model on the first real keystroke.
 *
 * A fresh node now opens empty, like a Vega chart, and the starter comes from
 * the arriving input (hook/useStarterSpec). Once offered it stays the same
 * string while the editor writes back and the user types, and it steps aside
 * only for a document written in from outside. These tests drive exactly the
 * mutation useNodeState performs.
 */
import React from 'react';
import { render, act, waitFor } from '@testing-library/react';

// The node reads its input edge from the flow context (hook/useGrammarInputState);
// the real provider would load the whole node registry, vega included.
jest.mock('../../../providers/FlowProvider', () => ({
  useFlowContext: () => ({ edges: [], nodeExecStatus: {} }),
}));
jest.mock('../../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock('../../../services/api', () => ({ fetchData: jest.fn(), fetchPreviewData: jest.fn() }));
jest.mock('../../../JavaScriptInterpreter', () => ({
  JavaScriptInterpreter: class { },
}));

import { useAutkGrammarBehavior } from '../../../adapters/node/autkGrammarBehavior';

const INPUT = {
  dataType: 'geodataframe',
  data: {
    type: 'FeatureCollection',
    features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: { pop: 3 } }],
  },
};

/** Renders the hook and reports every `defaultValueOverride` it has produced. */
function renderBehavior(data: any, code = '') {
  const seen: Array<string | undefined> = [];
  const Probe: React.FC<{ data: any; code: string }> = ({ data, code }) => {
    const behavior = useAutkGrammarBehavior(data, {
      output: { code: '', content: '' },
      setCode: jest.fn(),
      templateData: {},
      code,
    } as any);
    seen.push(behavior.defaultValueOverride);
    return null;
  };
  const utils = render(<Probe data={data} code={code} />);
  return { seen, rerender: (next: any, nextCode: string) => utils.rerender(<Probe data={next} code={nextCode} />) };
}

describe('useAutkGrammarBehavior defaultValueOverride', () => {
  test('a fresh node with no input opens empty', async () => {
    const { seen } = renderBehavior({ nodeId: 'n1' });
    await act(async () => {});
    expect(seen.every((v) => v === undefined)).toBe(true);
  });

  test('a node with saved code gets no override, so data.defaultCode wins', async () => {
    const { seen } = renderBehavior({ nodeId: 'n1', defaultCode: '{"map":{"layerRefs":[]}}', input: INPUT });
    await act(async () => {});
    expect(seen.every((v) => v === undefined)).toBe(true);
  });

  test('the starter stays constant after the editor writes data.code and the user types (#157)', async () => {
    // `data` is the same mutable object React Flow holds, exactly as on canvas.
    const data: any = { nodeId: 'n1', input: INPUT };
    const { seen, rerender } = renderBehavior(data);
    await waitFor(() => expect(seen[seen.length - 1]).toBeDefined());
    const starter = seen[seen.length - 1]!;
    expect(JSON.parse(starter).map.layerRefs[0]).toMatchObject({ dataRef: 'input_0', getFnv: 'pop' });

    // What useNodeState does once GrammarEditor floats the starter up...
    act(() => {
      data.code = starter;
      rerender(data, starter);
    });
    // ...and after the user's first keystroke.
    act(() => {
      data.code = '{\n  "map": {"layerRefs": []}\n}';
      rerender(data, data.code);
    });

    const offered = seen.filter((v) => v !== undefined);
    expect(new Set(offered).size).toBe(1);
    expect(seen[seen.length - 1]).toBe(starter);
  });

  test('a document written in from outside wins over the starter', async () => {
    const data: any = { nodeId: 'n1', input: INPUT };
    const { seen, rerender } = renderBehavior(data);
    await waitFor(() => expect(seen[seen.length - 1]).toBeDefined());

    act(() => {
      rerender({ ...data, defaultCode: '{"map":{"layerRefs":[{"dataRef":"input_0"}]}}' }, '');
    });
    expect(seen[seen.length - 1]).toBeUndefined();
  });
});
