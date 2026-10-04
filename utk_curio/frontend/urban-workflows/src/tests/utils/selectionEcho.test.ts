import { echoedCircle, isSelectionEcho, markSelectionEcho, selectionEchoSource } from '../../utils/selectionEcho';
import { normalizeFlowInput } from '../../utils/flowOutputRef';

describe('selectionEcho', () => {
  test('marks an input and reads the mark back', () => {
    const input = { dataType: 'dataframe', data: { a: [1] } };
    expect(isSelectionEcho(input)).toBe(false);
    expect(markSelectionEcho(input)).toBe(input);
    expect(isSelectionEcho(input)).toBe(true);
  });

  test('is never written into a request or a saved project', () => {
    const input = markSelectionEcho({ dataType: 'dataframe', data: { a: [1] } });
    expect(JSON.parse(JSON.stringify(input))).toEqual({ dataType: 'dataframe', data: { a: [1] } });
  });

  test('a fresh delivery starts unmarked', () => {
    // The flow provider tags what it delivers, not the output it caches, so a
    // chart connected later draws the cached rows like any new input.
    const cached = { dataType: 'dataframe', data: { a: [1] } };
    const delivered = markSelectionEcho(normalizeFlowInput(cached) as object);
    expect(isSelectionEcho(delivered)).toBe(true);
    expect(isSelectionEcho(cached)).toBe(false);
  });

  test('names the node whose selection it is, through a delivery too', () => {
    const delivered = markSelectionEcho(normalizeFlowInput({ dataType: 'dataframe', data: { a: [1] } }) as object, 'plot-1');
    expect(selectionEchoSource(delivered)).toBe('plot-1');
    expect(selectionEchoSource({ ...delivered })).toBe('plot-1');
    expect(selectionEchoSource(markSelectionEcho({ a: 1 }))).toBeUndefined();
    expect(JSON.parse(JSON.stringify(delivered))).toEqual({ dataType: 'dataframe', data: { a: [1] } });
  });

  test('anything that is not an object is not an echo', () => {
    expect(isSelectionEcho('')).toBe(false);
    expect(isSelectionEcho(null)).toBe(false);
    expect(isSelectionEcho(undefined)).toBe(false);
  });
});

describe('echoedCircle (#662)', () => {
  const frame = () => ({ dataType: 'dataframe', data: { a: [1] } });
  const bundle = (...data: unknown[]) => ({ dataType: 'outputs', data });

  test('one input that is an echo is circle 0, whatever came before', () => {
    expect(echoedCircle(markSelectionEcho(frame()), undefined)).toBe(0);
    expect(echoedCircle(frame(), frame())).toBeNull();
  });

  test('several inputs: the one circle that changed, when it is an echo', () => {
    const first = frame();
    const second = frame();
    const before = bundle(first, second);
    expect(echoedCircle(bundle(first, markSelectionEcho(frame())), before)).toBe(1);
    expect(echoedCircle(bundle(markSelectionEcho(frame()), second), before)).toBe(0);
  });

  test('new data on a circle, two circles changed, or a different count is not an echo', () => {
    const first = frame();
    const second = frame();
    const before = bundle(first, second);
    expect(echoedCircle(bundle(first, frame()), before)).toBeNull();
    expect(echoedCircle(bundle(markSelectionEcho(frame()), frame()), before)).toBeNull();
    expect(echoedCircle(bundle(first, second, markSelectionEcho(frame())), before)).toBeNull();
    expect(echoedCircle(bundle(first, markSelectionEcho(frame())), undefined)).toBeNull();
  });
});
