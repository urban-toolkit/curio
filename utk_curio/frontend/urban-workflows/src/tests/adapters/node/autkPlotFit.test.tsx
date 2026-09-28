/**
 * An Autark plot is drawn at its pane's size, not at autk-plot's fixed
 * 800 x 500, when its document does not size it (`utils/autkPlotSizing.ts`).
 *
 * The node measures the pane just before the grammar runs, and hands the size
 * to autk-grammar as the plot's `width` and `height`. autk-plot's SVG is then
 * made a block: inline, it sits on a text line whose descender space overflows
 * a pane the plot exactly fills.
 *
 * jsdom lays nothing out, so the pane's size is stubbed.
 */
import React from 'react';
import { render, act } from '@testing-library/react';

// The node reads its input edge from the flow context (hook/useGrammarInputState);
// the real provider would load the whole node registry, vega included.
jest.mock('../../../providers/FlowProvider', () => ({
  useFlowContext: () => ({ edges: [], nodeExecStatus: {} }),
}));
jest.mock('../../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
// One upstream row, so the plot's `upstream` table resolves and the node gets
// as far as running the grammar.
jest.mock('../../../services/api', () => ({
  fetchData: jest.fn().mockResolvedValue({
    dataType: 'geodataframe',
    data: {
      type: 'FeatureCollection',
      features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: { sunlight: 1 } }],
    },
  }),
  fetchPreviewData: jest.fn(),
}));
jest.mock('../../../JavaScriptInterpreter', () => ({
  JavaScriptInterpreter: class { },
}));
jest.mock('../../../adapters/autkGrammarAdapter', () => ({
  autkGrammarAdapter: { getDefaultSpec: () => '{"plot":{}}' },
}));

// What autk-plot does with the plot target: an inline SVG straight inside it.
const mockRunSpecs: any[] = [];
const mockAutkGrammar = jest.fn().mockImplementation((targets: Record<string, string>) => ({
  run: jest.fn(async (spec: any) => {
    mockRunSpecs.push(spec);
    const pane = targets.plot ? document.getElementById(targets.plot) : null;
    pane?.appendChild(document.createElementNS('http://www.w3.org/2000/svg', 'svg'));
  }),
  data: {},
}));
jest.mock(
  '@urban-toolkit/autk-grammar',
  () => ({ AutkGrammar: mockAutkGrammar }),
  { virtual: true },
);
jest.mock('@urban-toolkit/autk-compute', () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });

import { useAutkGrammarBehavior } from '../../../adapters/node/autkGrammarBehavior';
import { __resetWebGpuSupportCache } from '../../../utils/webgpuSupport';

const PANE = { width: 735, height: 480 };

function mountNode(): (spec: object) => Promise<void> {
  let apply: (spec: string) => Promise<void> = async () => { };
  const Probe: React.FC = () => {
    const behavior = useAutkGrammarBehavior(
      { nodeId: 'plot-1', input: { path: 'art-1', dataType: 'geodataframe' }, defaultCode: '{}' } as any,
      {
        output: { code: '', content: '' },
        setOutput: jest.fn(),
        setCode: jest.fn(),
        templateData: {},
      } as any,
    );
    apply = behavior.applyGrammar as (spec: string) => Promise<void>;
    return <>{behavior.contentComponent}</>;
  };
  render(<Probe />);
  return async (spec) => {
    await act(async () => { await apply(JSON.stringify(spec)); });
  };
}

function isPlotPane(el: Element): boolean {
  return el.id === 'autk-grammar-plot-plot-1';
}

beforeEach(() => {
  mockRunSpecs.length = 0;
  __resetWebGpuSupportCache();
  Object.defineProperty(navigator, 'gpu', {
    configurable: true,
    value: {
      requestAdapter: jest.fn().mockResolvedValue({ name: 'fake' }),
      getPreferredCanvasFormat: () => 'bgra8unorm',
    },
  });
  jest.spyOn(Element.prototype, 'clientWidth', 'get')
    .mockImplementation(function (this: Element) { return isPlotPane(this) ? PANE.width : 0; });
  jest.spyOn(Element.prototype, 'clientHeight', 'get')
    .mockImplementation(function (this: Element) { return isPlotPane(this) ? PANE.height : 0; });
});

afterEach(() => {
  jest.restoreAllMocks();
  __resetWebGpuSupportCache();
  Object.defineProperty(navigator, 'gpu', { configurable: true, value: undefined });
});

const BAR = { dataRef: 'upstream', mark: 'bar', axis: ['sunlight'] };

test('a plot the document did not size is drawn at its pane size', async () => {
  const apply = mountNode();

  await apply({ plot: BAR });

  expect(mockRunSpecs).toHaveLength(1);
  expect(mockRunSpecs[0].plot).toEqual({ ...BAR, width: PANE.width, height: PANE.height });
});

test('a size the document set is kept', async () => {
  const apply = mountNode();

  await apply({ plot: { ...BAR, width: 1200 } });

  expect(mockRunSpecs[0].plot).toEqual({ ...BAR, width: 1200, height: PANE.height });
});

test("the plot's SVG is a block, so a plot that fills its pane does not overflow it", async () => {
  const apply = mountNode();

  await apply({ plot: BAR });

  const svg = document.getElementById('autk-grammar-plot-plot-1')!.querySelector('svg')!;
  expect(svg.style.display).toBe('block');
});
