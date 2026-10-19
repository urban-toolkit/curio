/**
 * A package Vega-Lite template that ships its own spec opens with that spec and
 * its widgets, even when an input reaches the node before the starters feed
 * does: a node wired as it is made, or a drop while the feed is still loading.
 * The Vega-Lite node's own starter ladder, which fills an empty editor from the
 * input's columns, never replaces a template's starter.
 */
import { act, renderHook, waitFor } from '@testing-library/react';

// vega/vega-lite ship ESM Jest's default transform skips; nothing here compiles a chart.
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });
jest.mock('../../hook/useVega', () => ({
  useVega: () => ({ handleCompileGrammar: jest.fn().mockResolvedValue(undefined) }),
}));
jest.mock('../../providers/FlowProvider', () => ({
  useFlowContext: () => ({ edges: [], nodeExecStatus: {}, markNodeErrored: jest.fn() }),
}));
jest.mock('../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock('../../services/api', () => ({
  fetchData: jest.fn(),
  fetchPreviewData: jest.fn(),
  fetchRaster: jest.fn(),
}));

// The starters feed, empty until a test says it has arrived.
let mockFeed: Array<Record<string, unknown>> = [];
jest.mock('../../providers/StarterProvider', () => ({
  useStarterContext: () => ({
    // A new function on every render, as the provider hands one out.
    getStarters: (type: string) => mockFeed.filter((starter) => starter.type === type),
  }),
}));

import '../../registry/builtinBehaviors'; // side-effect: registers 'vega', ...
import '../../registry/iconRegistry';
import { useVegaBehavior } from '../../adapters/node/vegaBehavior';
import { registerPackageTemplates } from '../../registry/packagesClient';
import { clearPackageNodes } from '../../registry/nodeRegistry';
import { behaviorDataView } from '../../utils/behaviorDataView';
import type { NodeBehaviorData, UseNodeStateReturn } from '../../registry/types';

const TYPE = 'test.charts/lines@1';
const SPEC = '{"mark": "line", "encoding": {"x": {"field": "[!! x !!]"}, "y": {"field": "[!! y !!]", "type": "quantitative"}}}';
const WIDGETS = [
  { name: 'x', type: 'text', label: 'X column', default: 'x' },
  { name: 'y', type: 'text', label: 'Y column', default: 'y' },
];
// A DataFrame the Vega-Lite ladder draws as bars of pop by zone.
const INPUT = { dataType: 'dataframe', data: { zone: ['N', 'S'], pop: [1, 2] }, schema: { zone: 'str', pop: 'int64' } };

const PACK = {
  packageId: 'test.charts',
  major: 1,
  version: '1.0.0',
  name: 'Test charts',
  publisher: 'Test',
  description: '',
  license: 'MIT',
  permissions: [],
  lineage: null,
  templates: [{
    id: TYPE,
    templateId: 'lines',
    label: 'Lines',
    category: 'vis_grammar',
    engine: 'python' as const,
    description: '',
    icon: null,
    iconRef: null,
    behavior: 'vega',
    paletteOrder: null,
    editor: 'grammar' as const,
    hasCode: false,
    hasWidgets: true,
    hasGrammar: true,
    grammarId: 'vega-lite',
    badge: 'VEGA',
    inputPorts: [{ types: ['DATAFRAME'], cardinality: '1' }],
    outputPorts: [{ types: ['DATAFRAME'], cardinality: '1' }],
    // Listed in the feed as "lines.vl": its file name without the last extension.
    source: 'sources/lines.vl.json',
    widgets: WIDGETS,
    bidirectional: false,
    containerStyle: null,
    hasProvenance: null,
  }],
};

const STARTER = { id: 's1', type: TYPE, name: 'lines.vl', description: '', accessLevel: 'ANY', code: SPEC, custom: false };

function nodeState(): UseNodeStateReturn {
  return { code: '', output: { code: '', content: '', outputType: '' }, setOutput: jest.fn() } as unknown as UseNodeStateReturn;
}

describe('a package Vega-Lite template wired before its starter arrives', () => {
  beforeEach(() => {
    clearPackageNodes();
    mockFeed = [];
  });
  afterEach(() => clearPackageNodes());

  test('opens with its own spec and widgets, not a chart drawn from its input', async () => {
    const [descriptor] = registerPackageTemplates([PACK]);
    // A fresh node, with no code yet, whose input is already there.
    const node: Record<string, unknown> = { nodeId: 'n1', nodeType: descriptor.id, input: INPUT };
    const state = nodeState();
    const offered: string[] = [];
    const template = renderHook(() => {
      const result = descriptor.adapter.useNodeBehavior(behaviorDataView(node) as unknown as NodeBehaviorData, state);
      if (result.defaultValueOverride !== undefined) offered.push(result.defaultValueOverride);
      return result;
    });
    // A built-in Vega-Lite node given the same input at the same moment: once
    // its ladder has drawn a chart, the template's has had the same chance.
    const plain = renderHook(() => useVegaBehavior(
      { nodeId: 'n2', nodeType: 'curio.builtin/vis-vega@1', input: INPUT } as unknown as NodeBehaviorData,
      nodeState(),
    ));
    await waitFor(() => expect(plain.result.current.defaultValueOverride).toBeDefined());

    // The editor takes what the node offers, as CodeEditor's defaultValueBypass does.
    const editorTakesTheOffer = async () => {
      for (let round = 0; round < 3; round += 1) {
        await act(async () => {});
        const last = offered[offered.length - 1];
        if (last !== undefined && last !== state.code) {
          (state as { code: string }).code = last;
          template.rerender();
        }
      }
    };
    await editorTakesTheOffer();

    mockFeed = [STARTER]; // the starters feed arrives
    template.rerender();
    await editorTakesTheOffer();

    expect(state.code).toBe(SPEC);
    expect(offered.every((text) => text === SPEC)).toBe(true);
    expect((node.widgets as Array<{ name: string }> | undefined)?.map((w) => w.name)).toEqual(['x', 'y']);
  });
});
