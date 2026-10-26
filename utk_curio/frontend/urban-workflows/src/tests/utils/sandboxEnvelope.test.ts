/**
 * The sandbox's per-element envelopes come off before a value is shown (#516).
 * Shapes as `parseOutput` (sandbox/util/parsers.py) writes them.
 */
import { inFrameOrder, unwrapValueEnvelopes } from '../../utils/sandboxEnvelope';

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

// `/get` answers JSON with its keys sorted; `columns` keeps the frame's order.
describe('inFrameOrder', () => {
  const columns = ['Day', 'From', 'To', 'Added'];

  test("a frame's columns", () => {
    const envelope = { dataType: 'dataframe', columns, data: { Added: [1], Day: ['d'], From: ['f'], To: ['t'] } };
    const ordered = inFrameOrder(envelope);
    expect(Object.keys(ordered.data)).toEqual(columns);
    expect(ordered.data).toEqual(envelope.data);
  });

  test("each feature's properties", () => {
    const envelope = {
      dataType: 'geodataframe',
      columns: ['Without', 'With', 'Added', 'geometry'],
      data: {
        type: 'FeatureCollection',
        features: [{ type: 'Feature', geometry: null, properties: { Added: 1, With: 2, Without: 3 } }],
      },
    };
    expect(Object.keys(inFrameOrder(envelope).data.features[0].properties)).toEqual(['Without', 'With', 'Added']);
  });

  test('a name the list does not hold comes after those it does, in its place', () => {
    const envelope = { dataType: 'dataframe', columns: ['Day'], data: { z: [1], a: [2], Day: [3] } };
    expect(Object.keys(inFrameOrder(envelope).data)).toEqual(['Day', 'z', 'a']);
  });

  test('anything else is left as it is', () => {
    const noList = { dataType: 'dataframe', data: { b: [1], a: [2] } };
    expect(inFrameOrder(noList)).toBe(noList);
    const dict = { dataType: 'dict', columns: ['b', 'a'], data: { a: 1, b: 2 } };
    expect(inFrameOrder(dict)).toBe(dict);
    expect(inFrameOrder([1, 2])).toEqual([1, 2]);
  });
});
