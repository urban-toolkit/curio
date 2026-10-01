import fs from 'fs';
import path from 'path';
import {
  CANVAS_TITLE_ATTR,
  fitViewWithMenuOffset,
  MENU_BAR_ATTR,
} from '../../utils/fitViewWithMenuOffset';
import { getViewportForBounds } from 'reactflow';

// react-flow's geometry helpers are mocked: getNodesBounds/getViewportForBounds
// are pure math we don't need to re-derive, only that the function routes
// through them (or its pane fallback) correctly.
jest.mock('reactflow', () => ({
  getNodesBounds: jest.fn(() => ({ x: 0, y: 0, width: 100, height: 100 })),
  getViewportForBounds: jest.fn(() => ({ x: 5, y: 6, zoom: 1 })),
}));

const getViewportForBoundsMock = getViewportForBounds as jest.Mock;

type FakeNode = { id: string; width: number | null; height: number | null };

function makeRf(nodes: FakeNode[]) {
  return {
    getNodes: () => nodes,
    setViewport: jest.fn(),
    fitView: jest.fn(() => true),
  } as any;
}

describe('fitViewWithMenuOffset', () => {
  afterEach(() => {
    jest.restoreAllMocks();
    document.body.innerHTML = '';
  });

  test('returns false when no nodes exist', () => {
    const rf = makeRf([]);
    expect(fitViewWithMenuOffset(rf)).toBe(false);
    expect(rf.fitView).not.toHaveBeenCalled();
    expect(rf.setViewport).not.toHaveBeenCalled();
  });

  test('returns false (retry-worthy) when a node is unmeasured', () => {
    // Zero/null dimensions mean react-flow has not measured the node yet;
    // the function must report failure so the caller's retry loop waits.
    const rf = makeRf([{ id: 'a', width: 0, height: 0 }]);
    expect(fitViewWithMenuOffset(rf)).toBe(false);
    expect(rf.setViewport).not.toHaveBeenCalled();
  });

  test('measured nodes + no measurable pane falls back to plain fitView', () => {
    // jsdom getBoundingClientRect returns a zero-sized rect, so the pane is
    // "not measurable" — the fallback rf.fitView must run.
    const container = document.createElement('div');
    container.className = 'react-flow';
    document.body.appendChild(container);

    const rf = makeRf([{ id: 'a', width: 120, height: 80 }]);
    expect(fitViewWithMenuOffset(rf)).toBe(true);
    expect(rf.fitView).toHaveBeenCalledTimes(1);
    expect(rf.setViewport).not.toHaveBeenCalled();
  });

  test('measured nodes + measurable pane applies an offset setViewport', () => {
    const container = document.createElement('div');
    container.className = 'react-flow';
    document.body.appendChild(container);
    container.getBoundingClientRect = () =>
      ({ width: 800, height: 600, left: 0, top: 0 }) as DOMRect;

    const rf = makeRf([{ id: 'a', width: 120, height: 80 }]);
    expect(fitViewWithMenuOffset(rf)).toBe(true);
    expect(rf.setViewport).toHaveBeenCalledTimes(1);
    expect(rf.fitView).not.toHaveBeenCalled();
  });

  test('an open palette panel widens the occluded strip beyond the dock rect', () => {
    // The rail (#tools-palette-dock) is narrow; an open palette panel is
    // absolutely positioned beside it, so it falls OUTSIDE the dock's own
    // bounding rect. Measuring the dock alone would under-report the occlusion
    // and fit content underneath the open panel.
    const container = document.createElement('div');
    container.className = 'react-flow';
    document.body.appendChild(container);
    container.getBoundingClientRect = () =>
      ({ width: 1000, height: 600, left: 0, top: 0 }) as DOMRect;

    const dock = document.createElement('div');
    dock.id = 'tools-palette-dock';
    document.body.appendChild(dock);
    dock.getBoundingClientRect = () => ({ right: 60, left: 0, top: 0, width: 60 }) as DOMRect;

    // The panel lives inside the dock in the DOM but paints far to its right.
    const panel = document.createElement('div');
    panel.setAttribute('data-curio-tools-palette-panel', 'true');
    dock.appendChild(panel);
    panel.getBoundingClientRect = () => ({ right: 380, left: 60, top: 0, width: 320 }) as DOMRect;

    getViewportForBoundsMock.mockReturnValueOnce({ x: 5, y: 6, zoom: 1 });
    const rf = makeRf([{ id: 'a', width: 120, height: 80 }]);
    expect(fitViewWithMenuOffset(rf)).toBe(true);

    // Occlusion is the panel's right edge (380), not the rail's (60).
    const [, widthArg] = getViewportForBoundsMock.mock.calls.at(-1)!;
    expect(widthArg).toBe(1000 - 380);
    expect(rf.setViewport).toHaveBeenCalledWith({ x: 5 + 380, y: 6, zoom: 1 }, undefined);
  });

  test('a closed palette contributes nothing, leaving the rail as the occluder', () => {
    // Same DOM minus the panel marker: the panel element is only rendered while
    // open, so the occluded strip collapses back to the rail's own width.
    const container = document.createElement('div');
    container.className = 'react-flow';
    document.body.appendChild(container);
    container.getBoundingClientRect = () =>
      ({ width: 1000, height: 600, left: 0, top: 0 }) as DOMRect;

    const dock = document.createElement('div');
    dock.id = 'tools-palette-dock';
    document.body.appendChild(dock);
    dock.getBoundingClientRect = () => ({ right: 60, left: 0, top: 0, width: 60 }) as DOMRect;

    getViewportForBoundsMock.mockReturnValueOnce({ x: 5, y: 6, zoom: 1 });
    const rf = makeRf([{ id: 'a', width: 120, height: 80 }]);
    expect(fitViewWithMenuOffset(rf)).toBe(true);

    const [, widthArg] = getViewportForBoundsMock.mock.calls.at(-1)!;
    expect(widthArg).toBe(1000 - 60);
    expect(rf.setViewport).toHaveBeenCalledWith({ x: 5 + 60, y: 6, zoom: 1 }, undefined);
  });

  test('the widest open panel wins when several are marked', () => {
    const container = document.createElement('div');
    container.className = 'react-flow';
    document.body.appendChild(container);
    container.getBoundingClientRect = () =>
      ({ width: 1000, height: 600, left: 0, top: 0 }) as DOMRect;

    const dock = document.createElement('div');
    dock.id = 'tools-palette-dock';
    document.body.appendChild(dock);
    dock.getBoundingClientRect = () => ({ right: 60, left: 0, top: 0, width: 60 }) as DOMRect;

    for (const right of [200, 420, 310]) {
      const p = document.createElement('div');
      p.setAttribute('data-curio-tools-palette-panel', 'true');
      dock.appendChild(p);
      p.getBoundingClientRect = () => ({ right, left: 60, top: 0, width: right - 60 }) as DOMRect;
    }

    getViewportForBoundsMock.mockReturnValueOnce({ x: 5, y: 6, zoom: 1 });
    const rf = makeRf([{ id: 'a', width: 120, height: 80 }]);
    expect(fitViewWithMenuOffset(rf)).toBe(true);

    const [, widthArg] = getViewportForBoundsMock.mock.calls.at(-1)!;
    expect(widthArg).toBe(1000 - 420);
  });

  // #493: the menu bar is `position: fixed` over the top of the pane, so a
  // dataflow whose height set the zoom put its top node's title bar under it.
  const menuBar = (bottom: number) => {
    const bar = document.createElement('div');
    bar.setAttribute('data-curio-menu-bar', 'true');
    document.body.appendChild(bar);
    bar.getBoundingClientRect = () => ({ top: 0, bottom, height: bottom }) as DOMRect;
  };

  test('fits against the height below the menu bar and shifts down past it', () => {
    const container = document.createElement('div');
    container.className = 'react-flow';
    document.body.appendChild(container);
    container.getBoundingClientRect = () =>
      ({ width: 1000, height: 600, left: 0, top: 0 }) as DOMRect;
    menuBar(65);

    getViewportForBoundsMock.mockReturnValueOnce({ x: 5, y: 6, zoom: 1 });
    const rf = makeRf([{ id: 'a', width: 120, height: 80 }]);
    expect(fitViewWithMenuOffset(rf)).toBe(true);

    const [, widthArg, heightArg] = getViewportForBoundsMock.mock.calls.at(-1)!;
    expect(widthArg).toBe(1000);
    expect(heightArg).toBe(600 - 65);
    expect(rf.setViewport).toHaveBeenCalledWith({ x: 5, y: 6 + 65, zoom: 1 }, undefined);
  });

  test('a pane that starts below the bar is not shifted again', () => {
    const container = document.createElement('div');
    container.className = 'react-flow';
    document.body.appendChild(container);
    container.getBoundingClientRect = () =>
      ({ width: 1000, height: 600, left: 0, top: 65 }) as DOMRect;
    menuBar(65);

    getViewportForBoundsMock.mockReturnValueOnce({ x: 5, y: 6, zoom: 1 });
    const rf = makeRf([{ id: 'a', width: 120, height: 80 }]);
    expect(fitViewWithMenuOffset(rf)).toBe(true);

    const [, , heightArg] = getViewportForBoundsMock.mock.calls.at(-1)!;
    expect(heightArg).toBe(600);
    expect(rf.setViewport).toHaveBeenCalledWith({ x: 5, y: 6, zoom: 1 }, undefined);
  });

  test('the canvas menu bar carries the attribute the fit measures', () => {
    const upMenu = fs.readFileSync(
      path.resolve(__dirname, '../../components/menus/top/UpMenu.tsx'),
      'utf8',
    );
    expect(upMenu).toContain(`${MENU_BAR_ATTR}="true"`);
    expect(upMenu).toContain(`${CANVAS_TITLE_ATTR}="true"`);
  });

  // The category chips hang under the dataflow title, below the bar; a fitted
  // top node sat partly under them, which is #493 again one row lower.
  test('the title and its chips push the fit below them, not just the bar', () => {
    const container = document.createElement('div');
    container.className = 'react-flow';
    document.body.appendChild(container);
    container.getBoundingClientRect = () =>
      ({ width: 1000, height: 600, left: 0, top: 0 }) as DOMRect;
    menuBar(65);
    const title = document.createElement('div');
    title.setAttribute(CANVAS_TITLE_ATTR, 'true');
    title.getBoundingClientRect = () => ({ top: 80, bottom: 108 }) as DOMRect;
    const chips = document.createElement('div');
    chips.setAttribute('data-curio-category-chips', 'true');
    chips.getBoundingClientRect = () => ({ top: 104, bottom: 124 }) as DOMRect;
    title.appendChild(chips);
    document.body.appendChild(title);

    getViewportForBoundsMock.mockReturnValueOnce({ x: 5, y: 6, zoom: 1 });
    const rf = makeRf([{ id: 'a', width: 120, height: 80 }]);
    expect(fitViewWithMenuOffset(rf)).toBe(true);

    const [, , heightArg] = getViewportForBoundsMock.mock.calls.at(-1)!;
    expect(heightArg).toBe(600 - 124);
    expect(rf.setViewport).toHaveBeenCalledWith({ x: 5, y: 6 + 124, zoom: 1 }, undefined);
  });

  test('with an open dock, fits against the VISIBLE width and shifts past the dock', () => {
    const container = document.createElement('div');
    container.className = 'react-flow';
    document.body.appendChild(container);
    container.getBoundingClientRect = () =>
      ({ width: 1000, height: 600, left: 0, top: 0 }) as DOMRect;

    // An open palette dock occluding the left 400px of the pane.
    const dock = document.createElement('div');
    dock.id = 'tools-palette-dock';
    document.body.appendChild(dock);
    dock.getBoundingClientRect = () => ({ right: 400, left: 0, top: 0, width: 400 }) as DOMRect;

    getViewportForBoundsMock.mockReturnValueOnce({ x: 5, y: 6, zoom: 1 });
    const rf = makeRf([{ id: 'a', width: 120, height: 80 }]);
    expect(fitViewWithMenuOffset(rf)).toBe(true);

    // Zoom is computed against the VISIBLE width (1000 - 400 = 600), not 1000,
    // so a framed node fits in the strip right of the dock rather than overflowing.
    const [, widthArg] = getViewportForBoundsMock.mock.calls.at(-1)!;
    expect(widthArg).toBe(600);
    // The centered-in-visible result is shifted right by the full occluded width.
    expect(rf.setViewport).toHaveBeenCalledWith(
      { x: 5 + 400, y: 6, zoom: 1 },
      undefined,
    );
  });
});
