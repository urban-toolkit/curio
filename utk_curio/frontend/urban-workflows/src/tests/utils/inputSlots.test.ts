import {
  circleValue,
  compactedHandles,
  emptyWiredSlots,
  growsInputCircles,
  holdsValuePerCircle,
  inputCapacity,
  inputCircleCount,
  inputSlotOf,
  isDataEdge,
  nodeInputFromPorts,
  nodeInputFromSlots,
  slotHandleId,
  slotsFedBy,
  wiredInputSlots,
  withPortValues,
  withoutSlot,
} from '../../utils/inputSlots';

describe('slots held per circle (growing nodes)', () => {
  const edges = [
    { source: 'a', target: 't', targetHandle: 'in_0' },
    { source: 'b', target: 't', targetHandle: 'in_1' },
  ];

  test('the wired circles read their values in circle order', () => {
    // By circle, as the sandbox's `input_0`, `input_1` are: the edge into
    // circle 1 is listed first, and the bundle still starts with circle 0.
    const input = [{ id: 'raster' }, { id: 'csv' }];
    expect(nodeInputFromSlots(input, wiredInputSlots([edges[1], edges[0]], 't'))).toEqual({
      dataType: 'outputs',
      data: [{ id: 'raster' }, { id: 'csv' }],
    });
  });

  test('slotsFedBy falls back to edge targetHandle', () => {
    expect(slotsFedBy(edges, 't', 'b', [undefined, undefined])).toEqual([1]);
  });

  test('slotsFedBy returns every slot a source feeds (notable B item)', () => {
    const multi = [
      { source: 'a', target: 't', targetHandle: 'in_0' },
      { source: 'a', target: 't', targetHandle: 'in_2' },
    ];
    expect(slotsFedBy(multi, 't', 'a', [undefined, undefined, undefined])).toEqual([0, 2]);
  });

  test('wiredInputSlots returns sorted slot ids', () => {
    expect(wiredInputSlots(edges, 't')).toEqual([0, 1]);
  });
});

describe('circles', () => {
  test('the plain in handle is circle 0, and circles past 9 parse', () => {
    expect(inputSlotOf('in')).toBe(0);
    expect(inputSlotOf(undefined)).toBe(0);
    expect(inputSlotOf('in_3')).toBe(3);
    expect(inputSlotOf('in_10')).toBe(10);
    expect(inputSlotOf('in_points')).toBe(-1);
    expect(inputSlotOf('in/out')).toBe(-1);
    expect(slotHandleId(0)).toBe('in');
    expect(slotHandleId(12)).toBe('in_12');
  });

  test('interaction edges take no circle', () => {
    const edges = [
      { source: 'a', target: 't', targetHandle: 'in' },
      { source: 'v', target: 't', sourceHandle: 'in/out', targetHandle: 'in/out' },
    ];
    expect(wiredInputSlots(edges, 't')).toEqual([0]);
  });

  test("an interaction edge from a view's handle, or one a dataflow saved with no handles, takes no circle", () => {
    const edges = [
      { source: 'a', target: 't', targetHandle: 'in' },
      { source: 'v', target: 't', sourceHandle: 'in/out@heights', targetHandle: 'in/out' },
      { source: 'w', target: 't', type: 'Interaction' },
    ];
    expect(wiredInputSlots(edges, 't')).toEqual([0]);
    expect(edges.map(isDataEdge)).toEqual([true, false, false]);
  });

  test("a port's declared maximum is the capacity", () => {
    expect(inputCapacity([{ cardinality: '[1,n]' }])).toBe(Infinity);
    expect(inputCapacity([{ cardinality: '[0,n]' }])).toBe(Infinity);
    expect(inputCapacity([{ cardinality: '[1,2]' }])).toBe(2);
    expect(inputCapacity([{ cardinality: '1' }])).toBe(1);
    expect(inputCapacity([{ cardinality: '1' }, { cardinality: '1' }])).toBe(2);
    expect(inputCapacity([])).toBe(0);
  });

  test('one port taking more than one edge grows its circles; named ports do not', () => {
    expect(growsInputCircles([{ cardinality: '[1,n]' }])).toBe(true);
    expect(growsInputCircles([{ cardinality: '[1,2]' }])).toBe(true);
    expect(growsInputCircles([{ cardinality: '1' }])).toBe(false);
    expect(growsInputCircles([{ cardinality: '[0,1]' }])).toBe(false);
    expect(growsInputCircles([{ cardinality: '1' }, { cardinality: '1' }])).toBe(false);
    expect(growsInputCircles(undefined)).toBe(false);
  });

  test('there is always one free circle below the last wired one, up to the maximum', () => {
    expect(inputCircleCount([], Infinity)).toBe(1);
    expect(inputCircleCount([0], Infinity)).toBe(2);
    expect(inputCircleCount([0, 1, 2], Infinity)).toBe(4);
    expect(inputCircleCount([0, 1], 2)).toBe(2);
    expect(inputCircleCount([1], Infinity)).toBe(3);
  });
});

describe('the value a growing node reads', () => {
  const a = { path: 'a', dataType: 'dataframe' };
  const b = { path: 'b', dataType: 'dataframe' };

  test('one wired circle is its value; several are a bundle in circle order', () => {
    expect(nodeInputFromSlots([a], [0])).toBe(a);
    expect(nodeInputFromSlots([a, b], [0, 1])).toEqual({ dataType: 'outputs', data: [a, b] });
    expect(nodeInputFromSlots([undefined, b, a], [1, 2])).toEqual({ dataType: 'outputs', data: [b, a] });
  });

  test('nothing until every wired circle holds a value', () => {
    expect(nodeInputFromSlots([a, ''], [0, 1])).toBe('');
    expect(nodeInputFromSlots([], [])).toBe('');
    expect(emptyWiredSlots([a, undefined, b], [0, 1, 2])).toEqual([1]);
  });
});

describe('what a node holds on each circle, as its run reads it', () => {
  const a = { path: 'a', dataType: 'geodataframe' };
  const b = { path: 'b', dataType: 'geodataframe' };

  test("a node with several ports: each port's value on its circle, which its one value is read from", () => {
    // input_1 arrived first, as the Spatial Join's zones did on dev.
    const portInputs = withPortValues(withPortValues(undefined, ['in_1'], b), ['in'], a);
    const data = { portInputs, input: nodeInputFromPorts(portInputs, [0, 1]) };
    expect([circleValue(data, 0), circleValue(data, 1)]).toEqual([a, b]);
    expect(data.input).toEqual({ dataType: 'outputs', data: [a, b] });
    expect(holdsValuePerCircle(data)).toBe(true);
  });

  test('a node with several ports, one still empty: that circle holds nothing', () => {
    const data = { portInputs: withPortValues(undefined, ['in_1'], b), input: '' };
    expect([circleValue(data, 0), circleValue(data, 1)]).toEqual([undefined, b]);
    expect(holdsValuePerCircle(data)).toBe(true);
  });

  test("a growing node: each circle's value", () => {
    const data = { inputSlots: [a, undefined, b], input: '' };
    expect([0, 1, 2].map((slot) => circleValue(data, slot))).toEqual([a, undefined, b]);
    expect(holdsValuePerCircle(data)).toBe(true);
  });

  test('any other node: its one input, on circle 0', () => {
    const data = { input: a };
    expect([circleValue(data, 0), circleValue(data, 1)]).toEqual([a, undefined]);
    expect(holdsValuePerCircle(data)).toBe(false);
    expect(circleValue(undefined, 0)).toBeUndefined();
  });
});

describe('closing up after a deleted edge', () => {
  const edges = [
    { id: 'e0', source: 'a', target: 't', targetHandle: 'in' },
    { id: 'e2', source: 'c', target: 't', targetHandle: 'in_2' },
    { id: 'e3', source: 'd', target: 't', targetHandle: 'in_3' },
    { id: 'x', source: 'c', target: 'other', targetHandle: 'in_2' },
  ];

  test('every edge below the deleted circle moves up one', () => {
    expect(compactedHandles(edges, 't', 1)).toEqual(new Map([['e2', 'in_1'], ['e3', 'in_2']]));
  });

  test('deleting circle 0 moves circle 1 onto the plain in handle', () => {
    const moved = compactedHandles([{ id: 'e1', target: 't', targetHandle: 'in_1' }], 't', 0);
    expect(moved.get('e1')).toBe('in');
  });

  test('the values move with their circles', () => {
    expect(withoutSlot(['a', 'b', 'c'], 1)).toEqual(['a', 'c']);
    expect(withoutSlot(undefined, 0)).toEqual([]);
  });
});
