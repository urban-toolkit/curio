import { ResolutionType, VisInteractionType } from '../../constants';
import {
  columnRows,
  featureRows,
  isActiveSelect,
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

  test('a point selection over fields names values: the rows holding them, in any order (#847)', () => {
    const picked = { type: POINT, data: [{ unit_id: 103 }, { unit_id: 105 }] };
    // The chart's own rows, and readings of the units taken in another order.
    const units = objectRows([101, 102, 103, 104, 105, 106].map((unit_id) => ({ unit_id })));
    const readings = columnRows({
      reading: ['104-1', '101-1', '106-1', '103-1', '102-1', '105-1', '104-2', '101-2', '106-2', '103-2'],
      unit_id: [104, 101, 106, 103, 102, 105, 104, 101, 106, 103],
    });
    expect(selectIndices(picked, units)).toEqual([2, 4]);
    expect(selectIndices(picked, readings)).toEqual([3, 5, 9]);
  });

  test('a point over text values, or over several fields, matches each point whole (#847)', () => {
    expect(selectIndices({ type: POINT, data: [{ label: 'd' }, { label: 'b' }] }, rows)).toEqual([1, 3]);
    expect(selectIndices({ type: POINT, data: [{ kind: 'x', value: 30 }, { kind: 'y', value: 10 }] }, rows))
      .toEqual([2]);
  });

  test("a binned field's point holds the rows in its bin, [start, end) (#847)", () => {
    expect(selectIndices({ type: POINT, data: [{ value: [20, 40] }] }, rows)).toEqual([1, 2]);
  });

});

describe('a numeric range over rows that hold no number for its column (#872)', () => {
  const units = objectRows([
    { unit_id: 101, name: 'Alder', height: 8 },
    { unit_id: 102, name: 'Birch', height: 15 },
    { unit_id: 103, name: 'Cedar', height: 22 },
    { unit_id: 104, name: 'Dogwood', height: 12 },
    { unit_id: 105, name: 'Elm', height: 30 },
    { unit_id: 106, name: 'Fir', height: 18 },
  ]);
  // Three readings per unit, in another order than the units, and no height.
  const readings = columnRows({
    reading: [
      '104-1', '101-1', '106-1', '103-1', '102-1', '105-1',
      '104-2', '101-2', '106-2', '103-2', '102-2', '105-2',
      '104-3', '101-3', '106-3', '103-3', '102-3', '105-3',
    ],
    unit_id: [
      104, 101, 106, 103, 102, 105,
      104, 101, 106, 103, 102, 105,
      104, 101, 106, 103, 102, 105,
    ],
  });

  test('a brush over a column the rows lack marks none of them (#872)', () => {
    const brush = { type: INTERVAL, data: { height: [10, 20] } };
    expect(selectIndices(brush, units)).toEqual([1, 3, 5]);
    expect(readings.count).toBe(18);
    expect(selectIndices(brush, readings)).toEqual([]);
  });

  test('a brush over two columns, one the rows lack, marks none of them (#872)', () => {
    // The unit_id range alone covers the readings of 102 to 104, so a matcher
    // that skipped the missing column would mark these nine.
    expect(selectIndices({ type: INTERVAL, data: { unit_id: [102, 104] } }, readings))
      .toEqual([0, 3, 4, 6, 9, 10, 12, 15, 16]);
    const brush = { type: INTERVAL, data: { height: [10, 20], unit_id: [102, 104] } };
    expect(selectIndices(brush, units)).toEqual([1, 3]);
    expect(selectIndices(brush, readings)).toEqual([]);
    expect(selectIndices({ type: INTERVAL, data: { unit_id: [102, 104], height: [10, 20] } }, readings))
      .toEqual([]);
  });

  test('a null, empty, missing or non-numeric value is outside a numeric range (#872)', () => {
    // The range holds 0, which a null or empty text reads as in a comparison.
    const odd = objectRows([
      { height: 12 }, { height: null }, { height: '' }, { height: '  ' }, { height: 'n/a' }, { height: NaN }, {},
    ]);
    expect(selectIndices({ type: INTERVAL, data: { height: [0, 20] } }, odd)).toEqual([0]);
  });

  test('numeric text is compared as the number it reads (#872)', () => {
    const text = objectRows([{ height: '12' }, { height: '25' }, { height: ' 15 ' }]);
    expect(selectIndices({ type: INTERVAL, data: { height: [10, 20] } }, text)).toEqual([0, 2]);
  });

  test('a date is compared by its time, against time or date bounds (#872)', () => {
    const dated = objectRows([
      { when: new Date(Date.UTC(2024, 2, 15)) },
      { when: new Date(Date.UTC(2024, 8, 1)) },
    ]);
    const [start, end] = [Date.UTC(2024, 0, 1), Date.UTC(2024, 5, 30)];
    expect(selectIndices({ type: INTERVAL, data: { when: [start, end] } }, dated)).toEqual([0]);
    expect(selectIndices({ type: INTERVAL, data: { when: [new Date(start), new Date(end)] } }, dated))
      .toEqual([0]);
  });

  test('a date held as text is compared by its time (#872)', () => {
    const days = objectRows(['2020-01-01', '2020-01-02', '2020-01-03', '2020-01-04', '2020-01-05']
      .map((day) => ({ day })));
    const brush = { type: INTERVAL, data: { day: [Date.parse('2020-01-02'), Date.parse('2020-01-04')] } };
    expect(selectIndices(brush, days)).toEqual([1, 2, 3]);
  });

  test('a date and time held as text is compared by its time (#872)', () => {
    const times = objectRows(['01', '02', '03', '04', '05'].map((day) => ({ at: `2020-01-${day}T10:00:00` })));
    const brush = {
      type: INTERVAL,
      data: { at: [Date.parse('2020-01-02T10:00:00'), Date.parse('2020-01-04T10:00:00')] },
    };
    expect(selectIndices(brush, times)).toEqual([1, 2, 3]);
  });

  test('numeric text that could be a year stays a number (#872)', () => {
    expect(selectIndices({ type: INTERVAL, data: { height: [10, 20] } }, objectRows([{ height: '12' }])))
      .toEqual([0]);
    const years = objectRows([{ year: '2012' }, { year: '1999' }]);
    expect(selectIndices({ type: INTERVAL, data: { year: [2000, 2020] } }, years)).toEqual([0]);
  });

  test('a text interval over a column the rows lack marks none of them (#872)', () => {
    expect(selectIndices({ type: INTERVAL, data: { city: ['A', 'B'] } }, readings)).toEqual([]);
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

  test('MERGE_AND keeps the rows every active selection picked, and skips a cleared one', () => {
    const fromBar = { priority: 0, details: { highlight: { type: POINT, data: [0, 1], priority: 1 } } };
    const fromScatter = { priority: 1, details: { brush: { type: INTERVAL, data: { value: [20, 40] }, priority: 1 } } };
    // A chart that mounted and selected nothing, and one whose brush was cleared.
    const fromMap = { priority: 0, details: { pick: { type: UNDETERMINED, data: [], priority: 1 } } };
    const fromHistogram = { priority: 0, details: { brush: { type: INTERVAL, data: {}, priority: 1 } } };
    const between = { between: ResolutionType.MERGE_AND };

    expect(matchSelections([fromBar, fromScatter], rows, between)).toEqual([1]);
    expect(matchSelections([fromBar, fromScatter, fromMap, fromHistogram], rows, between)).toEqual([1]);
    expect(matchSelections([fromMap, fromHistogram], rows, between)).toEqual([]);
    // An active brush that covers no row is a selection of nothing.
    const empty = { priority: 1, details: { brush: { type: INTERVAL, data: { value: [11, 12] }, priority: 1 } } };
    expect(matchSelections([fromBar, empty], rows, between)).toEqual([]);
  });

  test("MERGE_AND inside a chart skips the chart's selects that hold nothing", () => {
    const chart = {
      priority: 1,
      details: {
        click: { type: POINT, data: [0, 1], priority: 0 },
        brush: { type: INTERVAL, data: {}, priority: 1 },
      },
    };
    expect(matchSelections([chart], rows, { plot: ResolutionType.MERGE_AND })).toEqual([0, 1]);
    // OVERWRITE still reads the newest select, cleared or not.
    expect(matchSelections([chart], rows)).toEqual([]);
  });

  test('a point selection over values is active, and MERGE_AND intersects it like any other (#847)', () => {
    const fromBar = { priority: 0, details: { pick: { type: POINT, data: [{ kind: 'x' }], priority: 1 } } };
    const fromScatter = { priority: 1, details: { brush: { type: INTERVAL, data: { value: [20, 40] }, priority: 1 } } };
    const cleared = { priority: 0, details: { pick: { type: UNDETERMINED, data: [], priority: 1 } } };
    expect(isActiveSelect(fromBar.details.pick)).toBe(true);
    expect(matchSelections([fromBar, fromScatter, cleared], rows, { between: ResolutionType.MERGE_AND }))
      .toEqual([2]);
  });

  test("Autark's map pick is a select like any other", () => {
    const pick = {
      priority: 1,
      details: { autk_selection: { type: POINT, data: [2], priority: 1, layerRef: 'input_0' } },
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
