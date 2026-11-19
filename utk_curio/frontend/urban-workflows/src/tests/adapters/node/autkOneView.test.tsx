/**
 * An Autark node draws every view of its document (adapters/node/autkGrammarBehavior):
 * a map and a plot, or a list of maps or of plots, each in an element of its
 * own. Views autk-grammar refuses, such as two plots of one table without
 * ids, fail before anything runs, with the grammar's words, which name the
 * fix: the node is marked errored, so the nodes it feeds say so, and its error
 * is what Solve and the Node Builder read. A document with one map or one plot
 * runs as it always has, and a `map` or `plot` written as a list of one is that
 * view: a map's layers are counted, filtered and picked, and a plot is drawn in
 * the node's pane, checked against the tables at hand and brushed by its layer,
 * as an object's are.
 *
 * The grammar is a stand-in that records what the node hands it
 * (_support/autkNodeMocks).
 *
 * A pick or a brush on a view that names its rows by key columns
 * (`selectFields`) sends their values, `{unit_id: 103}`, as a Vega-Lite point
 * select over fields does, read from the input row behind what was picked.
 * A view that names none sends the input rows. The units and readings are
 * _support/keyedSelections' fixture.
 */
import { act } from '@testing-library/react';

// The node reads its input edge from the flow context (hook/useGrammarInputState);
// the real provider would load the whole node registry, vega included.
jest.mock('../../../providers/FlowProvider', () => require('../../_support/autkNodeMocks').flowProviderModule);
jest.mock('../../../providers/ToastProvider', () => require('../../_support/autkNodeMocks').toastProviderModule);
jest.mock('../../../services/api', () => require('../../_support/autkNodeMocks').apiModule);
jest.mock('../../../JavaScriptInterpreter', () => ({
  JavaScriptInterpreter: class { },
}));
jest.mock(
  '@urban-toolkit/autk-grammar',
  () => require('../../_support/autkNodeMocks').autkGrammarModule,
  { virtual: true },
);
jest.mock('@urban-toolkit/autk-compute', () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });
// A document that loads its own tables, with no sandbox and no database here.
jest.mock(
  '@urban-toolkit/autk-db',
  () => ({ AutkDb: class { async init() { throw new Error('no autk-db in this test'); } } }),
  { virtual: true },
);

import { NodeType, ResolutionType, VisInteractionType } from '../../../constants';
import { columnRows, isActiveSelect, matchSelections } from '../../../utils/selectionMatch';
import {
  AutkGrammar as mockAutkGrammar,
  grammarRuns as mockRuns,
  markNodeErrored as mockMarkNodeErrored,
  resetAutkNodeMocks,
  showToast as mockShowToast,
} from '../../_support/autkNodeMocks';
import { lastSelection, mountAutkNode, stubWebGpu, unstubWebGpu } from '../../_support/autkNode';
import {
  LOAD_ORDER,
  UNIT_PROPERTIES,
  UNIT_ROW,
  YARD_ROW,
  atPositions,
  drawnAt,
  expectDiscriminates,
  inHeightRange,
  looselyHolding,
  readingColumns,
  readingsOf,
  unitsCollection,
} from '../../_support/keyedSelections';

/** What autk-grammar, and so the node, says of two plots of one table without ids. */
const PLOTS_WITHOUT_IDS = 'Two plots of the table "input_0" have no id; give each plot an id.';

const NODE = 'view-1';
/** The canvas the node draws its first map on; map k draws on `<CANVAS>-<k>`. */
const CANVAS = 'autk-grammar-map-' + NODE;
/** The pane the node draws its first plot in; plot k draws in `<PANE>-<k>`. */
const PANE = 'autk-grammar-plot-' + NODE;
/** The element of view *index* whose first is *first*. */
const nth = (first: string, index: number) => (index === 0 ? first : `${first}-${index}`);
const MAP = { layerRefs: [{ dataRef: 'input_0', getFnv: 'pop' }] };
const PLOT = {
  dataRef: 'input_0', mark: 'bar', axis: ['pop', '@transform'],
  transform: { preset: 'binning-1d' }, events: ['brushX'],
};

const mountNode = () => mountAutkNode(NODE);

/** Run *spec* and expect it refused: nothing ran, and the node failed with the fix, *says*. */
async function expectRefused(spec: object, says: string): Promise<void> {
  const node = mountNode();

  await node.run(spec);

  expect(node.lastOutput()).toEqual({ code: 'error', content: says });
  expect(mockAutkGrammar).not.toHaveBeenCalled();
  // The nodes it feeds say it failed, and the person running it is told.
  expect(mockMarkNodeErrored).toHaveBeenCalledWith(NODE);
  expect(mockShowToast).toHaveBeenCalledWith(says, 'error');
}

/** Run *spec* and expect it drawn as one run: the grammar handed *targets* and the views as written. */
async function expectDrawn(spec: { map?: unknown; plot?: unknown }, targets: object): Promise<void> {
  const node = mountNode();

  await node.run(spec);

  expect(mockRuns).toHaveLength(1);
  expect(mockRuns[0].targets).toEqual(targets);
  for (const view of ['map', 'plot'] as const) {
    const written = Array.isArray(spec[view]) && (spec[view] as unknown[]).length === 1
      ? (spec[view] as unknown[])[0]
      : spec[view];
    expect(mockRuns[0].spec[view]).toEqual(written);
  }
  expect(node.lastOutput()).toEqual({ code: 'success', content: '' });
  expect(mockMarkNodeErrored).not.toHaveBeenCalled();
  // Each element the grammar is handed is on the page.
  for (const id of Object.values(targets).flat()) expect(document.getElementById(id as string)).not.toBeNull();
}

beforeEach(() => {
  resetAutkNodeMocks();
  stubWebGpu();
});

afterEach(unstubWebGpu);

test.each([2, 3])('a document with %i maps draws each on a canvas of its own', async (count) => {
  await expectDrawn(
    { map: Array.from({ length: count }, () => MAP) },
    { map: Array.from({ length: count }, (_, k) => nth(CANVAS, k)) },
  );
});

test.each([2, 3])('a document with %i plots of one table without ids fails before anything runs, and its error names the fix', async (count) => {
  await expectRefused({ plot: Array.from({ length: count }, () => PLOT) }, PLOTS_WITHOUT_IDS);
});

test.each([2, 3])('a document with %i plots of one table with ids draws each in a pane of its own', async (count) => {
  await expectDrawn(
    { plot: Array.from({ length: count }, (_, k) => ({ ...PLOT, id: `heights-${k}` })) },
    { plot: Array.from({ length: count }, (_, k) => nth(PANE, k)) },
  );
});

test.each([
  ['a map and a plot', { map: MAP, plot: PLOT }],
  ['a list of one map and a plot', { map: [MAP], plot: PLOT }],
  ['a map and a list of one plot', { map: MAP, plot: [PLOT] }],
])('a document with %s draws both', async (_, spec) => {
  await expectDrawn(spec, { map: CANVAS, plot: PANE });
});

test('a document with one map runs as before', async () => {
  const node = mountNode();

  await node.run({ map: MAP });

  expect(mockRuns).toHaveLength(1);
  expect(mockRuns[0].targets).toEqual({ map: CANVAS });
  expect(mockRuns[0].spec.map).toEqual(MAP);
  expect(node.lastOutput()).toEqual({ code: 'success', content: '' });
  expect(mockMarkNodeErrored).not.toHaveBeenCalled();
});

test('a document with one plot runs as before', async () => {
  const node = mountNode();

  await node.run({ plot: PLOT });

  expect(mockRuns).toHaveLength(1);
  expect(mockRuns[0].targets).toEqual({ plot: PANE });
  expect(mockRuns[0].spec.plot).toEqual(PLOT);
  expect(node.lastOutput()).toEqual({ code: 'success', content: '' });
  expect(mockMarkNodeErrored).not.toHaveBeenCalled();
});

test('a list of one map is that map: its layers are counted, filtered and picked', async () => {
  const node = mountNode();
  const picked = { dataRef: 'input_0', isPick: true };

  await node.run({ map: [{ layerRefs: [picked, { dataRef: 'parks' }] }] });

  // Drawn as one map on the node's canvas, less the layer that names a table
  // the dataflow does not produce, which the run's note names.
  expect(mockRuns).toHaveLength(1);
  expect(mockRuns[0].targets).toEqual({ map: CANVAS });
  expect(mockRuns[0].spec.map).toEqual({ layerRefs: [picked] });
  expect(node.lastOutput()).toEqual({ code: 'success', content: expect.stringMatching(/^drew 1 of 2 layers: /) });

  // A pick on it names the layer it came from.
  mockRuns[0].pick([0]);
  expect(node.interactions).toHaveBeenCalledWith(
    { autk_selection: expect.objectContaining({ layerRef: 'input_0' }) },
    NODE,
  );
});

test("a list of one plot is that plot: drawn in the node's pane, and its brush names its layer", async () => {
  const node = mountNode();

  await node.run({ plot: [PLOT] });

  expect(mockRuns).toHaveLength(1);
  expect(mockRuns[0].targets).toEqual({ plot: PANE });
  expect(mockRuns[0].spec.plot).toEqual(PLOT);
  expect(node.lastOutput()).toEqual({ code: 'success', content: '' });

  // A brush on it names the layer it came from.
  mockRuns[0].brush([0]);
  expect(node.interactions).toHaveBeenCalledWith(
    { autk_selection: expect.objectContaining({ layerRef: 'input_0' }) },
    NODE,
  );
});

test('a list of one plot that names a table the dataflow does not produce is reported, not drawn', async () => {
  const node = mountNode();

  await node.run({ plot: [{ ...PLOT, dataRef: 'parks' }] });

  expect(mockAutkGrammar).not.toHaveBeenCalled();
  expect(node.lastOutput()).toMatchObject({
    code: 'error',
    content: expect.stringContaining('(asked for: parks; available: input_0)'),
  });
});

describe('a pick or a brush on a view that names its rows by key columns (selectFields)', () => {
  const KEYED_MAP = {
    map: { layerRefs: [{ dataRef: 'input_0', getFnv: 'height', isPick: true, selectFields: ['unit_id'] }] },
  };
  const KEYED_PLOT = {
    plot: { dataRef: 'input_0', mark: 'bar', axis: ['name', 'height'], events: ['brushX'], selectFields: ['unit_id'] },
  };
  /** A Vega-Lite chart's selection of unit 105, as it reaches a Data Pool beside the node's. */
  const VEGA_105 = {
    priority: 0,
    details: { pick: { type: VisInteractionType.POINT, data: [{ unit_id: 105 }], priority: 1 } },
  };
  /** The readings a Data Pool linked to the node marks for its *selection*, and with VEGA_105 under MERGE_AND. */
  const marked = (selection: any) =>
    matchSelections([{ details: { autk_selection: selection }, priority: 1 }], columnRows(readingColumns()));
  const markedWithVega = (selection: any) =>
    matchSelections(
      [{ details: { autk_selection: selection }, priority: 1 }, VEGA_105],
      columnRows(readingColumns()),
      { between: ResolutionType.MERGE_AND },
    );

  /** The node over the units, after a run of *spec* that drew. */
  async function drawn(spec: object) {
    const node = mountAutkNode(NODE, unitsCollection());
    await node.run(spec);
    expect(node.lastOutput()).toEqual({ code: 'success', content: '' });
    return node;
  }

  test("repro: a pick sends the key of the input row drawn where it landed, and a Data Pool marks that unit's readings", async () => {
    const node = await drawn(KEYED_MAP);
    const at = drawnAt(UNIT_ROW[103]);
    // The input row at that position is another unit.
    expect(UNIT_PROPERTIES[at].unit_id).toBe(101);

    act(() => mockRuns[0].pick([at]));

    expect(lastSelection(node)).toEqual({
      type: VisInteractionType.POINT,
      data: [{ unit_id: 103 }],
      priority: 1,
      source: NodeType.AUTK_GRAMMAR,
      layerRef: 'input_0',
    });
    expect(marked(lastSelection(node))).toEqual(readingsOf(103));
    expectDiscriminates(readingsOf(103), {
      positions: atPositions([UNIT_ROW[103]]),
      range: inHeightRange([103]),
      looseEquality: looselyHolding([103]),
    });
  });

  test('repro: a plot brush sends the keys of the rows it covers, read in the order the plot holds them', async () => {
    const node = await drawn(KEYED_PLOT);
    // Bars 1 to 3: the depot, which holds no unit_id, then units 103 and 101.
    const brushed = [1, 2, 3];
    expect(brushed.map((p) => UNIT_PROPERTIES[LOAD_ORDER[p]].unit_id)).toEqual([undefined, 103, 101]);
    expect(brushed.map((p) => UNIT_PROPERTIES[p].unit_id)).toEqual([104, 103, 101]);

    act(() => mockRuns[0].brush(brushed));

    expect(lastSelection(node)).toMatchObject({
      type: VisInteractionType.POINT,
      data: [{ unit_id: 103 }, { unit_id: 101 }],
      layerRef: 'input_0',
    });
    expect(marked(lastSelection(node))).toEqual(readingsOf(101, 103));
    expectDiscriminates(readingsOf(101, 103), {
      positions: atPositions(brushed.map((p) => LOAD_ORDER[p])),
      range: inHeightRange([101, 103]),
      looseEquality: looselyHolding([101, 103]),
    });
  });

  test('guard: a view that names no key sends the input rows, as before', async () => {
    const map = await drawn({ map: { layerRefs: [{ dataRef: 'input_0', isPick: true }] } });
    act(() => mockRuns[0].pick([drawnAt(UNIT_ROW[103])]));
    expect(lastSelection(map)).toMatchObject({ type: VisInteractionType.POINT, data: [UNIT_ROW[103]] });

    const plot = await drawn({ plot: { ...KEYED_PLOT.plot, selectFields: undefined } });
    act(() => mockRuns[1].brush([1, 2, 3]));
    expect(lastSelection(plot)).toMatchObject({ type: VisInteractionType.POINT, data: [0, 2, 3] });
  });

  test('repro: a pick on a drawn row that holds no key selects nothing, and MERGE_AND passes over it', async () => {
    const node = await drawn(KEYED_MAP);
    expect(UNIT_PROPERTIES[YARD_ROW].unit_id).toBeUndefined();

    act(() => mockRuns[0].pick([drawnAt(YARD_ROW)]));

    expect(lastSelection(node)).toMatchObject({ type: VisInteractionType.UNDETERMINED, data: [] });
    expect(isActiveSelect(lastSelection(node))).toBe(false);
    expect(markedWithVega(lastSelection(node))).toEqual(readingsOf(105));
  });

  test('guard: an empty pick selects nothing, and MERGE_AND passes over it', async () => {
    const node = await drawn(KEYED_MAP);
    act(() => mockRuns[0].pick([drawnAt(UNIT_ROW[103])]));

    act(() => mockRuns[0].pick([]));

    expect(lastSelection(node)).toMatchObject({ type: VisInteractionType.UNDETERMINED, data: [] });
    expect(isActiveSelect(lastSelection(node))).toBe(false);
    expect(markedWithVega(lastSelection(node))).toEqual(readingsOf(105));
  });

  /** Run *spec* over the units and expect it failed with *message*: nothing drawn, nothing sent. */
  async function expectFailed(spec: object, message: string) {
    const node = mountAutkNode(NODE, unitsCollection());
    await node.run(spec);
    expect(node.lastOutput()).toEqual({ code: 'error', content: message });
    expect(mockAutkGrammar).not.toHaveBeenCalled();
    expect(node.interactions).not.toHaveBeenCalled();
    expect(mockMarkNodeErrored).toHaveBeenCalledWith(NODE);
    expect(mockShowToast).toHaveBeenCalledWith(message, 'error');
  }

  test('repro: a key column no feature of the layer has fails the run, naming the column and the layer', async () => {
    await expectFailed(
      { map: { layerRefs: [{ dataRef: 'input_0', isPick: true, selectFields: ['unit_id', 'unit_idx'] }] } },
      'selectFields names unit_idx, which no feature of input_0 has.',
    );
  });

  test('repro: a key on a table the document loads itself fails the run, and says to load it upstream', async () => {
    await expectFailed(
      {
        data: [{ type: 'csv', url: 'https://example.org/parks.csv', outputTableName: 'parks' }],
        map: { layerRefs: [{ dataRef: 'parks', isPick: true, selectFields: ['park_id'] }] },
      },
      "selectFields needs parks to come from this node's input, but this document loads it. "
        + 'Load parks in an upstream node and connect that node here.',
    );
  });
});
