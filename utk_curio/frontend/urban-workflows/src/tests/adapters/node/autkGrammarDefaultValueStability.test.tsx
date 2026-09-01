/**
 * Regression test for #157 — the Autark grammar editor rejected edits.
 *
 * Root cause was a feedback loop, not a layout problem. The behavior derived
 * `defaultValueOverride` from `data.code`, but GrammarEditor writes back into
 * `data.code` on every change (floatCode -> nodeState.setCode -> useNodeState's
 * `data.code = code` effect). So the override flipped between the starter spec
 * and `undefined` on every render, and @monaco-editor/react's controlled-value
 * effect replaced the full model range on the first real keystroke — mid-document
 * edits vanished and only the last line appeared to accept input.
 *
 * The fix decides the override ONCE, on mount. This test drives exactly the
 * mutation useNodeState performs, so it fails against the old behavior.
 */
import React from 'react';
import { render, act } from '@testing-library/react';

jest.mock('../../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock('../../../services/api', () => ({ fetchData: jest.fn() }));
jest.mock('../../../JavaScriptInterpreter', () => ({
  JavaScriptInterpreter: class { },
}));

const DEFAULT_SPEC = '{\n  "map": {}\n}';
jest.mock('../../../adapters/autkGrammarAdapter', () => ({
  autkGrammarAdapter: { getDefaultSpec: () => DEFAULT_SPEC },
}));

import { useAutkGrammarBehavior } from '../../../adapters/node/autkGrammarBehavior';

/** Renders the hook and reports every `defaultValueOverride` it has produced. */
function renderBehavior(data: any) {
  const seen: Array<string | undefined> = [];
  const Probe: React.FC<{ data: any }> = ({ data }) => {
    const behavior = useAutkGrammarBehavior(data, {
      output: { code: '', content: '' },
      setCode: jest.fn(),
      templateData: {},
    } as any);
    seen.push(behavior.defaultValueOverride);
    return null;
  };
  const utils = render(<Probe data={data} />);
  return { seen, rerender: (next: any) => utils.rerender(<Probe data={next} />) };
}

describe('useAutkGrammarBehavior defaultValueOverride', () => {
  test('a fresh node gets the starter spec', () => {
    const { seen } = renderBehavior({ nodeId: 'n1' });
    expect(seen[0]).toBe(DEFAULT_SPEC);
  });

  test('a node with saved code gets no override, so data.defaultCode wins', () => {
    const { seen } = renderBehavior({ nodeId: 'n1', defaultCode: '{"map":{"layerRefs":[]}}' });
    expect(seen[0]).toBeUndefined();
  });

  test('stays constant after the editor writes data.code — the #157 loop', () => {
    // `data` is the same mutable object React Flow holds, exactly as on canvas.
    const data: any = { nodeId: 'n1' };
    const { seen, rerender } = renderBehavior(data);
    expect(seen[0]).toBe(DEFAULT_SPEC);

    // What useNodeState does once GrammarEditor floats the spec up.
    act(() => {
      data.code = DEFAULT_SPEC;
      rerender(data);
    });
    // ...and again after the user's first keystroke.
    act(() => {
      data.code = '{\n  "map": {"layerRefs": []}\n}';
      rerender(data);
    });

    // Pre-fix this alternated DEFAULT_SPEC -> undefined -> DEFAULT_SPEC, and the
    // `undefined` is what let the controlled value clobber the Monaco model.
    expect(new Set(seen).size).toBe(1);
    expect(seen.every((v) => v === DEFAULT_SPEC)).toBe(true);
  });
});
