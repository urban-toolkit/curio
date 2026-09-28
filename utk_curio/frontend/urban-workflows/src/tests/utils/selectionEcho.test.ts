import { isSelectionEcho, markSelectionEcho } from '../../utils/selectionEcho';
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

  test('anything that is not an object is not an echo', () => {
    expect(isSelectionEcho('')).toBe(false);
    expect(isSelectionEcho(null)).toBe(false);
    expect(isSelectionEcho(undefined)).toBe(false);
  });
});
