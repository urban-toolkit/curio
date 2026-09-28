import { ResolutionType, VisInteractionType } from '../../constants';
import {
  columnRows,
  featureRows,
  matchSelections,
  objectRows,
  resolveIndices,
  selectIndices,
} from '../../utils/selectionMatch';

const POINT = VisInteractionType.POINT;
const INTERVAL = VisInteractionType.INTERVAL;
const UNDETERMINED = VisInteractionType.UNDETERMINED;

const rows = objectRows([
  { label: 'a', value: 10, kind: 'x' },
  { label: 'b', value: 20, kind: 'y' },
  { label: 'c', value: 30, kind: 'x' },
  { label: 'd', value: 40, kind: 'y' },
]);

describe('selectIndices', () => {
  test('a point selection names row positions', () => {
    expect(selectIndices({ type: POINT, data: [2, 0] }, rows)).toEqual([2, 0]);
  });

  test('a numeric interval keeps the rows inside its bounds, ends included', () => {
    expect(selectIndices({ type: INTERVAL, data: { value: [20, 30] } }, rows)).toEqual([1, 2]);
  });

  test('a categorical interval keeps the rows whose value it lists', () => {
    expect(selectIndices({ type: INTERVAL, data: { label: ['a', 'd'] } }, rows)).toEqual([0, 3]);
  });

  test('several brushed columns must all match', () => {
    expect(selectIndices({ type: INTERVAL, data: { value: [10, 30], kind: ['x'] } }, rows))
      .toEqual([0, 2]);
  });

  test('an interval over no column, or a cleared selection, picks nothing', () => {
    expect(selectIndices({ type: INTERVAL, data: {} }, rows)).toEqual([]);
    expect(selectIndices({ type: UNDETERMINED, data: [] }, rows)).toEqual([]);
  });

});

describe('resolveIndices', () => {
  const entries = [
    { priority: 0, indices: [0, 1, 2] },
    { priority: 1, indices: [1, 2, 3] },
  ];

  test('OVERWRITE keeps the latest selection', () => {
    expect(resolveIndices(entries, ResolutionType.OVERWRITE)).toEqual([1, 2, 3]);
  });

  test('MERGE_AND keeps rows every selection picked', () => {
    expect(resolveIndices(entries, ResolutionType.MERGE_AND)).toEqual([1, 2]);
  });

  test('MERGE_OR keeps rows any selection picked', () => {
    expect(resolveIndices(entries, ResolutionType.MERGE_OR).sort()).toEqual([0, 1, 2, 3]);
  });
});

describe('matchSelections', () => {
  test("resolves each chart's params, then the charts", () => {
    const fromBar = {
      priority: 1,
      details: {
        old: { type: POINT, data: [0], priority: 0 },
        highlight: { type: POINT, data: [3], priority: 1 },
      },
    };
    const fromScatter = { priority: 0, details: { brush: { type: POINT, data: [1], priority: 1 } } };

    expect(matchSelections([fromBar, fromScatter], rows)).toEqual([3]);
    expect(matchSelections([fromBar, fromScatter], rows, { between: ResolutionType.MERGE_OR }).sort())
      .toEqual([1, 3]);
  });

  test("Autark's map pick is a select like any other", () => {
    const pick = {
      priority: 1,
      details: { autk_selection: { type: POINT, data: [2], priority: 1, layerRef: 'upstream' } },
    };
    expect(matchSelections([pick], rows)).toEqual([2]);
  });

  test('a select of an unknown kind is ignored, not read as a cleared one', () => {
    const selection = {
      priority: 1,
      details: {
        highlight: { type: POINT, data: [1], priority: 1 },
        other: { type: 'lasso', data: [], priority: 1 },
      },
    };
    expect(matchSelections([selection], rows)).toEqual([1]);
  });
});

describe('row accessors', () => {
  test('column-major frames, as arrays or index-keyed', () => {
    const asArrays = columnRows({ label: ['a', 'b'], value: [1, 2] });
    expect(asArrays.count).toBe(2);
    expect(asArrays.value(1, 'value')).toBe(2);

    const keyed = columnRows({ label: { 5: 'a', 9: 'b' }, value: { 5: 1, 9: 2 } });
    expect(keyed.count).toBe(2);
    expect(keyed.value(1, 'label')).toBe('b');
  });

  test('feature properties', () => {
    const features = featureRows({
      features: [{ properties: { zone: 'n' } }, { properties: { zone: 's' } }],
    });
    expect(features.count).toBe(2);
    expect(features.value(1, 'zone')).toBe('s');
    expect(featureRows(null).count).toBe(0);
  });
});
