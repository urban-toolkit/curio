/**
 * A Vega-Lite node after a Compare Scenarios node draws the node's scenarios
 * as the node's own Chart tab does: every channel of its spec on
 * `scenario_name` takes the Compare node's labels, the scenarios' names in the
 * order of its inputs and the colors of their boxes, over whatever the spec
 * writes for that column. It reads the Compare node on its first input,
 * directly or through nodes of one input each, and is drawn again when a
 * scenario is renamed or recolored, as the Chart tab draws its chart; a label
 * that draws the same draws nothing again. A chart with no Compare node there
 * is compiled as written.
 */
import { act, renderHook } from '@testing-library/react';

// What the behavior hands useVega's compile, which is what the chart draws,
// and how it asks for it drawn.
const mockCompile = jest.fn(async (_spec: string, _how?: unknown) => ({ rowsIn: 4, drawn: 4 }));
// The flow the node reads its upstream from; set per test, read on every render.
let mockFlow: Record<string, unknown> = {};

jest.mock('../../../providers/FlowProvider', () => ({ useFlowContext: () => mockFlow }));
jest.mock('../../../hook/useVega', () => ({ useVega: () => ({ handleCompileGrammar: mockCompile }) }));
jest.mock('../../../providers/ToastProvider', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));

import { useVegaBehavior } from '../../../adapters/node/vegaBehavior';

type Label = { scenario: string; name: string; color: string };
const TALL: Label = { scenario: 's-tall', name: 'Twice as tall', color: '#e76f51' };
const BASELINE: Label = { scenario: 's-base', name: 'Baseline', color: '#2a9d8f' };

const node = (id: string, nodeType: string, extra: Record<string, unknown> = {}) => ({
  id,
  type: '__curioUniversalNode',
  data: { nodeId: id, nodeType, ...extra },
});
const compare = (labels: Label[]) => node('cmp', 'curio.builtin/compare-scenarios@1', { compareScenarios: { inputs: labels } });
const code = (id: string) => node(id, 'curio.builtin/computation-analysis@1', { code: 'return input_0' });
const chart = node('chart', 'curio.builtin/vis-vega@1');
const edge = (source: string, target: string, targetHandle = 'in') => ({
  id: `${source}->${target}:${targetHandle}`,
  source,
  target,
  sourceHandle: 'out',
  targetHandle,
});

/** Bars per scenario, colored by scenario, with no scale written. */
const BARS = {
  mark: 'bar',
  encoding: {
    x: { field: 'scenario_name', type: 'nominal' },
    y: { field: 'sunlight', type: 'quantitative', aggregate: 'mean' },
    color: { field: 'scenario_name', type: 'nominal' },
  },
};
/** The same bars with the scenarios' order and colors written by hand. */
const HAND_SET = {
  ...BARS,
  encoding: {
    ...BARS.encoding,
    color: {
      field: 'scenario_name',
      type: 'nominal',
      scale: { domain: ['Baseline', 'Twice as tall'], range: ['#000000', '#999999'] },
    },
  },
};
/** Bars per segment: no channel reads scenario_name. */
const BY_SEGMENT = {
  mark: 'bar',
  encoding: {
    x: { field: 'segment', type: 'nominal' },
    y: { field: 'sunlight', type: 'quantitative' },
    color: { field: 'segment', type: 'nominal', scale: { range: ['#e76f51', '#2a9d8f'] } },
  },
};

const setFlow = (flow: Record<string, unknown>) => {
  mockFlow = { scenarios: [], nodeExecStatus: {}, isRunActive: false, ...flow };
};

const compiled = () => mockCompile.mock.calls.map((call) => call[0]);
const lastCompiled = () => JSON.parse(compiled()[compiled().length - 1]);

/** The chart node rendered over the current flow, with *spec* applied once. */
async function drawn(spec: unknown) {
  mockCompile.mockClear();
  const text = typeof spec === 'string' ? spec : JSON.stringify(spec);
  const setOutput = jest.fn();
  const data: any = { nodeId: 'chart', input: '', outputCallback: jest.fn() };
  const nodeState: any = { code: text, setOutput, templateData: { code: text } };
  let hook: any;
  await act(async () => {
    hook = renderHook(() => useVegaBehavior(data, nodeState));
  });
  await act(async () => {
    await hook.result.current.applyGrammar(text);
  });
  return { hook, text, setOutput };
}

describe('a Vega-Lite chart after a Compare Scenarios node', () => {
  test("draws scenario_name in the scenarios' colors, in the order of the Compare node's inputs", async () => {
    setFlow({ nodes: [compare([TALL, BASELINE]), chart], edges: [edge('cmp', 'chart')] });
    const { setOutput } = await drawn(BARS);
    const spec = lastCompiled();
    expect(spec.encoding.color.scale).toEqual({
      domain: ['Twice as tall', 'Baseline'],
      range: ['#e76f51', '#2a9d8f'],
    });
    expect(spec.encoding.x.sort).toEqual(['Twice as tall', 'Baseline']);
    expect(setOutput).toHaveBeenLastCalledWith({ code: 'success', content: '', outputType: '' });
  });

  test("a color written for the scenarios is replaced by their boxes'", async () => {
    setFlow({ nodes: [compare([TALL, BASELINE]), chart], edges: [edge('cmp', 'chart')] });
    await drawn(HAND_SET);
    expect(lastCompiled().encoding.color.scale).toEqual({
      domain: ['Twice as tall', 'Baseline'],
      range: ['#e76f51', '#2a9d8f'],
    });
  });

  test('reads the Compare node through a node of one input between them', async () => {
    setFlow({
      nodes: [compare([TALL, BASELINE]), code('keep'), chart],
      edges: [edge('cmp', 'keep'), edge('keep', 'chart')],
    });
    await drawn(BARS);
    expect(lastCompiled().encoding.color.scale.range).toEqual(['#e76f51', '#2a9d8f']);
  });

  test('a spec that reads no scenario_name is compiled as written', async () => {
    setFlow({ nodes: [compare([TALL, BASELINE]), chart], edges: [edge('cmp', 'chart')] });
    const { text } = await drawn(BY_SEGMENT);
    expect(compiled()).toEqual([text]);
  });

  test('a spec that is not JSON reaches the compile as it is, which says why', async () => {
    setFlow({ nodes: [compare([TALL, BASELINE]), chart], edges: [edge('cmp', 'chart')] });
    await drawn('{"mark": "bar",');
    expect(compiled()).toEqual(['{"mark": "bar",']);
  });
});

describe('a Vega-Lite chart with no Compare Scenarios node on its first input', () => {
  test('is compiled as written, its own scenario colors included', async () => {
    setFlow({ nodes: [code('up'), chart], edges: [edge('up', 'chart')] });
    const { text } = await drawn(HAND_SET);
    expect(compiled()).toEqual([text]);
  });

  test('a Compare node on its second input is not read', async () => {
    setFlow({
      nodes: [code('up'), compare([TALL, BASELINE]), chart],
      edges: [edge('up', 'chart', 'in'), edge('cmp', 'chart', 'in_1')],
    });
    const { text } = await drawn(HAND_SET);
    expect(compiled()).toEqual([text]);
  });

  test('a Compare node behind a node of two inputs is not read', async () => {
    setFlow({
      nodes: [compare([TALL, BASELINE]), code('other'), code('join'), chart],
      edges: [edge('cmp', 'join', 'in'), edge('other', 'join', 'in_1'), edge('join', 'chart')],
    });
    const { text } = await drawn(HAND_SET);
    expect(compiled()).toEqual([text]);
  });

  test('a flow that lists no nodes draws the spec as written', async () => {
    setFlow({ edges: [edge('cmp', 'chart')] });
    const { text } = await drawn(HAND_SET);
    expect(compiled()).toEqual([text]);
  });
});

describe("the chart follows its scenarios' boxes", () => {
  test('a scenario recolored draws the chart again in its new color, as the Chart tab draws', async () => {
    setFlow({ nodes: [compare([TALL, BASELINE]), chart], edges: [edge('cmp', 'chart')] });
    const { hook } = await drawn(BARS);
    expect(compiled()).toHaveLength(1);

    setFlow({ nodes: [compare([{ ...TALL, color: '#7b3294' }, BASELINE]), chart], edges: [edge('cmp', 'chart')] });
    await act(async () => {
      hook.rerender();
    });
    expect(compiled()).toHaveLength(2);
    expect(lastCompiled().encoding.color.scale).toEqual({
      domain: ['Twice as tall', 'Baseline'],
      range: ['#7b3294', '#2a9d8f'],
    });
    // Play compiles in full. The recolor draws as the Chart tab draws its chart,
    // with no version recorded and nothing handed on, and keeps a selection.
    expect(mockCompile.mock.calls[0][1]).toBeUndefined();
    expect(mockCompile.mock.calls[1][1]).toEqual({ recordsProvenance: false, forwardsInput: false, keepsSelection: true });
  });

  test("a label whose scenario id alone changed draws nothing again", async () => {
    setFlow({ nodes: [compare([TALL, BASELINE]), chart], edges: [edge('cmp', 'chart')] });
    const { hook } = await drawn(BARS);

    setFlow({ nodes: [compare([{ ...TALL, scenario: 's-tall-copy' }, BASELINE]), chart], edges: [edge('cmp', 'chart')] });
    await act(async () => {
      hook.rerender();
    });
    expect(compiled()).toHaveLength(1);
  });

  test('the same labels with their keys in another order draw nothing again', async () => {
    // Read off the graph, a label is {scenario, name, color}; once the Compare
    // node stores it, {name, color, scenario}.
    const a = code('a');
    const b = code('b');
    const scenarios = [
      { id: TALL.scenario, name: TALL.name, color: TALL.color, nodes: ['a'] },
      { id: BASELINE.scenario, name: BASELINE.name, color: BASELINE.color, nodes: ['b'] },
    ];
    const edges = [edge('a', 'cmp', 'in'), edge('b', 'cmp', 'in_1'), edge('cmp', 'chart')];
    setFlow({ nodes: [a, b, node('cmp', 'curio.builtin/compare-scenarios@1'), chart], edges, scenarios });
    const { hook } = await drawn(BARS);
    expect(lastCompiled().encoding.color.scale.range).toEqual([TALL.color, BASELINE.color]);

    setFlow({ nodes: [a, b, compare([TALL, BASELINE]), chart], edges, scenarios });
    await act(async () => {
      hook.rerender();
    });
    expect(compiled()).toHaveLength(1);
  });

  test('a scenario renamed during a run is drawn by the run, then again once it ends if the run did not', async () => {
    setFlow({ nodes: [compare([TALL, BASELINE]), chart], edges: [edge('cmp', 'chart')] });
    const { hook } = await drawn(BARS);

    const renamed = [{ ...TALL, name: 'Three times as tall' }, BASELINE];
    setFlow({ nodes: [compare(renamed), chart], edges: [edge('cmp', 'chart')], isRunActive: true });
    await act(async () => {
      hook.rerender();
    });
    expect(compiled()).toHaveLength(1);

    setFlow({ nodes: [compare(renamed), chart], edges: [edge('cmp', 'chart')], isRunActive: false });
    await act(async () => {
      hook.rerender();
    });
    expect(compiled()).toHaveLength(2);
    expect(lastCompiled().encoding.x.sort).toEqual(['Three times as tall', 'Baseline']);
  });

  test('nothing is drawn before the chart has been drawn once', async () => {
    setFlow({ nodes: [compare([TALL, BASELINE]), chart], edges: [edge('cmp', 'chart')] });
    mockCompile.mockClear();
    const data: any = { nodeId: 'chart', input: '', outputCallback: jest.fn() };
    const nodeState: any = { code: JSON.stringify(BARS), setOutput: jest.fn(), templateData: { code: '' } };
    let hook: any;
    await act(async () => {
      hook = renderHook(() => useVegaBehavior(data, nodeState));
    });
    setFlow({ nodes: [compare([{ ...TALL, color: '#7b3294' }, BASELINE]), chart], edges: [edge('cmp', 'chart')] });
    await act(async () => {
      hook.rerender();
    });
    expect(compiled()).toEqual([]);
  });
});
