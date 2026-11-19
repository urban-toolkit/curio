/**
 * An Autark node draws every view of its document, each in a pane of its own
 * (adapters/node/autkGrammarBehavior, autkViews `layOutPanes`), placed where
 * autk-grammar's `arrangeViews` says: a grid of its rows and columns, `gap`
 * pixels apart, stacked without a `layout`. Map k draws on
 * `autk-grammar-map-<node>` for k = 0, else `autk-grammar-map-<node>-<k>`, and
 * plots likewise; the grammar's targets name each view's element, one view of
 * a kind by its id and several by a list in the grammar's order. Each plot is
 * fitted to its own pane, and a view the run leaves out takes its target and
 * the links to it along. A layout the grammar cannot arrange fails the run in
 * the grammar's words.
 *
 * The grammar is the stand-in of _support/autkNodeMocks, with the grammar's
 * own arrangeViews rule (_support/autkArrangeViews).
 */
import { act } from '@testing-library/react';

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
// Each map's canvas gets the zoom fix and the press guard, which the next run takes off.
const mockDisposed: string[] = [];
jest.mock('../../../adapters/node/autkMapZoom', () => ({
  attachMapInteractionZoomFix: jest.fn((canvas: HTMLCanvasElement) => () => { mockDisposed.push(`zoom:${canvas.id}`); }),
}));
jest.mock('../../../adapters/node/autkMapPressGuard', () => ({
  attachMapPressGuard: jest.fn((canvas: HTMLCanvasElement) => () => { mockDisposed.push(`press:${canvas.id}`); }),
}));

import { attachMapInteractionZoomFix } from '../../../adapters/node/autkMapZoom';
import { attachMapPressGuard } from '../../../adapters/node/autkMapPressGuard';
import {
  AutkGrammar as mockAutkGrammar,
  grammarRuns as mockRuns,
  resetAutkNodeMocks,
  showToast as mockShowToast,
} from '../../_support/autkNodeMocks';
import { mountAutkNode, stubWebGpu, unstubWebGpu } from '../../_support/autkNode';
import { arrangeViews } from '../../_support/autkArrangeViews';

const NODE = 'panes-1';
const MAP_ID = `autk-grammar-map-${NODE}`;
const PLOT_ID = `autk-grammar-plot-${NODE}`;
/** The element of view *index* whose first is *first*. */
const nth = (first: string, index: number) => (index === 0 ? first : `${first}-${index}`);
const LAYERS = [{ dataRef: 'input_0', getFnv: 'pop' }];
const plot = (id: string, dataRef = 'input_0') => ({ id, dataRef, mark: 'bar', axis: ['pop'], events: ['brushX'] });

/** The pane that holds the element *id*. */
const paneOf = (id: string) => document.getElementById(id)!.parentElement as HTMLElement;

beforeEach(() => {
  resetAutkNodeMocks();
  stubWebGpu();
  mockDisposed.length = 0;
  (attachMapInteractionZoomFix as jest.Mock).mockClear();
  (attachMapPressGuard as jest.Mock).mockClear();
});

afterEach(() => {
  jest.restoreAllMocks();
  unstubWebGpu();
});

test("the views are placed in panes where arrangeViews says, and each draws in its own element", async () => {
  const spec = {
    layout: { type: 'grid', columns: 2, gap: 8 },
    map: [{ id: 'north', layerRefs: LAYERS }, { id: 'south', layerRefs: LAYERS }],
    plot: [plot('heights'), plot('floors')],
  };
  const node = mountAutkNode(NODE);

  await node.run(spec);

  expect(node.lastOutput()).toEqual({ code: 'success', content: '' });
  expect(mockRuns[0].targets).toEqual({
    map: [MAP_ID, nth(MAP_ID, 1)],
    plot: [PLOT_ID, nth(PLOT_ID, 1)],
  });
  const grid = document.querySelector<HTMLElement>('[data-curio-autk-views]')!;
  expect(grid.style.display).toBe('grid');
  expect(grid.style.gridTemplateColumns).toBe('repeat(2, minmax(0, 1fr))');
  expect(grid.style.gridTemplateRows).toBe('repeat(2, minmax(0, 1fr))');
  expect(grid.style.gap).toBe('8px');
  for (const pane of arrangeViews(spec).panes) {
    const id = nth(pane.kind === 'map' ? MAP_ID : PLOT_ID, pane.index);
    const element = document.getElementById(id)!;
    expect(element.tagName.toLowerCase()).toBe(pane.kind === 'map' ? 'canvas' : 'div');
    expect(element.dataset.viewId).toBe(pane.id);
    // autk-map puts a map's menu, legend and watermark in its canvas's parent: the pane.
    const slot = paneOf(id);
    expect(slot.parentElement).toBe(grid);
    expect(slot.style.position).toBe('relative');
    expect(slot.style.overflow).toBe('hidden');
    expect(slot.style.gridRow).toBe(String(pane.row + 1));
    expect(slot.style.gridColumn).toBe(String(pane.column + 1));
    expect(slot.dataset.viewId).toBe(pane.id);
  }
  // The notebook gives the node a map's height for each of its two rows.
  expect(node.viewRows()).toBe(2);
});

test('without a layout the panes stack, maps first, in the order the document lists them', async () => {
  const node = mountAutkNode(NODE);

  await node.run({ plot: plot('heights'), map: { id: 'city', layerRefs: LAYERS } });

  expect(mockRuns[0].targets).toEqual({ map: MAP_ID, plot: PLOT_ID });
  const grid = document.querySelector<HTMLElement>('[data-curio-autk-views]')!;
  expect(grid.style.gridTemplateColumns).toBe('repeat(1, minmax(0, 1fr))');
  expect(grid.style.gridTemplateRows).toBe('repeat(2, minmax(0, 1fr))');
  expect(paneOf(MAP_ID).style.gridRow).toBe('1');
  expect(paneOf(PLOT_ID).style.gridRow).toBe('2');
  expect(node.viewRows()).toBe(2);
});

test('a horizontal layout puts the views side by side, on one row', async () => {
  const node = mountAutkNode(NODE);

  await node.run({ layout: { type: 'horizontal' }, map: { id: 'city', layerRefs: LAYERS }, plot: plot('heights') });

  expect(paneOf(MAP_ID).style.gridColumn).toBe('1');
  expect(paneOf(PLOT_ID).style.gridColumn).toBe('2');
  expect(paneOf(PLOT_ID).style.gridRow).toBe('1');
  expect(node.viewRows()).toBe(1);
});

test('one view fills the node as it always has: its element is the body, with no pane around it', async () => {
  const node = mountAutkNode(NODE);

  await node.run({ map: { layerRefs: LAYERS } });

  expect(mockRuns[0].targets).toEqual({ map: MAP_ID });
  expect(document.querySelector('[data-curio-autk-views]')).toBeNull();
  const canvas = document.getElementById(MAP_ID)!;
  expect(canvas.style.width).toBe('100%');
  expect(canvas.style.height).toBe('100%');
  expect(canvas.parentElement!.style.position).toBe('relative');
  expect(canvas.parentElement!.children).toHaveLength(1);
  expect(node.viewRows()).toBe(1);
});

test("a layout the grammar cannot arrange fails the run in the grammar's words, before anything draws", async () => {
  const node = mountAutkNode(NODE);
  const says = 'Layout type must be vertical, horizontal or grid, not "diagonal".';

  await node.run({ layout: { type: 'diagonal' }, map: { layerRefs: LAYERS } });

  expect(node.lastOutput()).toEqual({ code: 'error', content: says });
  expect(mockShowToast).toHaveBeenCalledWith(says, 'error');
  expect(mockAutkGrammar).not.toHaveBeenCalled();
});

test('each plot is fitted to its own pane', async () => {
  const sizes: Record<string, [number, number]> = { [PLOT_ID]: [420, 260], [nth(PLOT_ID, 1)]: [300, 500] };
  jest.spyOn(Element.prototype, 'clientWidth', 'get')
    .mockImplementation(function (this: Element) { return sizes[this.id]?.[0] ?? 0; });
  jest.spyOn(Element.prototype, 'clientHeight', 'get')
    .mockImplementation(function (this: Element) { return sizes[this.id]?.[1] ?? 0; });
  const node = mountAutkNode(NODE);

  await node.run({ layout: { type: 'horizontal' }, plot: [plot('heights'), { ...plot('floors'), width: 900 }] });

  expect(mockRuns[0].spec.plot).toEqual([
    { ...plot('heights'), width: 420, height: 260 },
    // A size the document set is kept.
    { ...plot('floors'), width: 900, height: 500 },
  ]);
});

test('a plot of a table the dataflow does not produce is left out with its target and its links, and the rest draw in their own panes', async () => {
  const node = mountAutkNode(NODE);

  await node.run({
    map: { id: 'city', layerRefs: [{ dataRef: 'input_0' }, { dataRef: 'parks' }] },
    plot: [plot('parks', 'parks'), plot('heights')],
    links: [{ source: 'parks', target: 'city' }, { source: 'heights', target: 'city' }],
  });

  expect(mockRuns).toHaveLength(1);
  // The plot that draws is the document's second: it draws in that plot's element.
  expect(mockRuns[0].targets).toEqual({ map: MAP_ID, plot: nth(PLOT_ID, 1) });
  expect(mockRuns[0].spec.plot).toEqual(plot('heights'));
  expect(mockRuns[0].spec.map).toEqual({ id: 'city', layerRefs: [{ dataRef: 'input_0' }] });
  expect(mockRuns[0].spec.links).toEqual([{ source: 'heights', target: 'city' }]);
  expect(node.lastOutput()).toMatchObject({ code: 'success', content: expect.stringMatching(/^drew 2 of 4 layers: /) });
});

test('a map left with no layer is left out with its target and the links to it, and the next map draws on its own canvas', async () => {
  const node = mountAutkNode(NODE);

  await node.run({
    map: [{ id: 'parks', layerRefs: [{ dataRef: 'parks' }] }, { id: 'city', layerRefs: LAYERS }],
    plot: plot('heights'),
    links: [{ source: 'heights', target: 'parks', layer: 'parks' }, { source: 'heights', target: 'city' }],
  });

  expect(mockRuns).toHaveLength(1);
  expect(mockRuns[0].targets).toEqual({ map: nth(MAP_ID, 1), plot: PLOT_ID });
  expect(mockRuns[0].spec.map).toEqual({ id: 'city', layerRefs: LAYERS });
  expect(mockRuns[0].spec.links).toEqual([{ source: 'heights', target: 'city' }]);
});

test("every map's canvas gets the zoom fix and the press guard, and the next run takes all of them off", async () => {
  const node = mountAutkNode(NODE);
  const spec = { map: [{ layerRefs: LAYERS }, { layerRefs: LAYERS }], plot: plot('heights') };

  await node.run(spec);

  const canvases = [MAP_ID, nth(MAP_ID, 1)];
  expect((attachMapInteractionZoomFix as jest.Mock).mock.calls.map(([canvas]) => canvas.id)).toEqual(canvases);
  expect((attachMapPressGuard as jest.Mock).mock.calls.map(([canvas]) => canvas.id)).toEqual(canvases);
  expect(mockDisposed).toEqual([]);

  await node.run(spec);

  expect(mockDisposed.sort()).toEqual([...canvases.map((id) => `zoom:${id}`), ...canvases.map((id) => `press:${id}`)].sort());
});

test('the panes are made anew by each run, so a view a run no longer has leaves the page', async () => {
  const node = mountAutkNode(NODE);
  await node.run({ map: [{ layerRefs: LAYERS }, { layerRefs: LAYERS }] });
  expect(document.getElementById(nth(MAP_ID, 1))).not.toBeNull();

  await act(async () => { await node.run({ map: { layerRefs: LAYERS } }); });

  expect(document.getElementById(nth(MAP_ID, 1))).toBeNull();
  expect(document.querySelector('[data-curio-autk-views]')).toBeNull();
  expect(mockRuns[1].targets).toEqual({ map: MAP_ID });
});
