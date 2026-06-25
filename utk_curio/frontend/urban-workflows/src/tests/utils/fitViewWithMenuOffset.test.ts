import { fitViewWithMenuOffset } from '../../utils/fitViewWithMenuOffset';

// react-flow's geometry helpers are mocked: getNodesBounds/getViewportForBounds
// are pure math we don't need to re-derive, only that the function routes
// through them (or its pane fallback) correctly.
jest.mock('reactflow', () => ({
  getNodesBounds: jest.fn(() => ({ x: 0, y: 0, width: 100, height: 100 })),
  getViewportForBounds: jest.fn(() => ({ x: 5, y: 6, zoom: 1 })),
}));

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
});
