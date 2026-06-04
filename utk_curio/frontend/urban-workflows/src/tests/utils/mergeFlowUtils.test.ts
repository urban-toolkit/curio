import {
  buildMergeOutputArray,
  mergeSlotForSource,
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

  test('connectedMergeSlotIndices returns sorted slot ids', () => {
    expect(connectedMergeSlotIndices(edges, 'merge')).toEqual([0, 1]);
  });
});
