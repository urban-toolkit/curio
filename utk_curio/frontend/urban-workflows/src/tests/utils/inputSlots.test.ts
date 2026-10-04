import {
  buildMergeOutputArray,
  mergeSlotForSource,
  mergeSlotsForSource,
  connectedMergeSlotIndices,
} from '../../utils/mergeFlowUtils';

describe('mergeFlowUtils', () => {
  const edges = [
    { source: 'a', target: 'merge', targetHandle: 'in_0' },
    { source: 'b', target: 'merge', targetHandle: 'in_1' },
  ];

  test('buildMergeOutputArray preserves slot order', () => {
    const input = [{ id: 'raster' }, { id: 'csv' }];
    expect(buildMergeOutputArray(input, edges, 'merge')).toEqual([
      { id: 'raster' },
      { id: 'csv' },
    ]);
  });

  test('mergeSlotForSource falls back to edge targetHandle', () => {
    expect(mergeSlotForSource(edges, 'merge', 'b', [undefined, undefined])).toBe(1);
  });

  test('mergeSlotsForSource returns every slot a source feeds (notable B item)', () => {
    const multi = [
      { source: 'a', target: 'merge', targetHandle: 'in_0' },
      { source: 'a', target: 'merge', targetHandle: 'in_2' },
    ];
    expect(mergeSlotsForSource(multi, 'merge', 'a', [undefined, undefined, undefined])).toEqual([0, 2]);
  });

  test('connectedMergeSlotIndices returns sorted slot ids', () => {
    expect(connectedMergeSlotIndices(edges, 'merge')).toEqual([0, 1]);
  });
});
