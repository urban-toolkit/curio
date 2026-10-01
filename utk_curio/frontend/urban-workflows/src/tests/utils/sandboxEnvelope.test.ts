/**
 * The sandbox's per-element envelopes come off before a value is shown (#516).
 * Shapes as `parseOutput` (sandbox/util/parsers.py) writes them.
 */
import { unwrapValueEnvelopes } from '../../utils/sandboxEnvelope';

const int = (n: number) => ({ data: n, dataType: 'int' });

describe('unwrapValueEnvelopes', () => {
  test("a list's elements", () => {
    expect(unwrapValueEnvelopes([int(2), int(4), int(6)])).toEqual([2, 4, 6]);
  });

  test('a list of dicts, and lists inside lists', () => {
    expect(unwrapValueEnvelopes([
      { data: { a: 1 }, dataType: 'dict' },
      { data: [int(1), { data: 'x', dataType: 'str' }], dataType: 'list' },
    ])).toEqual([{ a: 1 }, [1, 'x']]);
  });

  test("a tuple of outputs", () => {
    expect(unwrapValueEnvelopes({ data: [int(1), { data: true, dataType: 'bool' }], dataType: 'outputs' }))
      .toEqual([1, true]);
  });

  test('frames and rasters keep their envelope', () => {
    const frame = { data: { n: [1] }, dataType: 'dataframe' };
    const raster = { data: '/x.tif', dataType: 'raster' };
    expect(unwrapValueEnvelopes([frame, raster])).toEqual([frame, raster]);
  });

  test("a user dict with those keys and some other dataType is data", () => {
    const own = { data: 5, dataType: 'reading' };
    expect(unwrapValueEnvelopes([own])).toEqual([own]);
  });

  test("a dict's own values are not touched", () => {
    const dict = { inner: int(3) };
    expect(unwrapValueEnvelopes(dict)).toBe(dict);
  });
});
