import { resolveSaveOutputDataset, buildSaveableLiveOutputs } from '../../utils/saveOutputDataset';

describe('resolveSaveOutputDataset', () => {
  test('uses explicit defaultSave argument when node field unset', () => {
    expect(resolveSaveOutputDataset({}, false)).toBe(false);
    expect(resolveSaveOutputDataset({}, true)).toBe(true);
  });

  test('respects per-node override', () => {
    expect(resolveSaveOutputDataset({ saveOutputDataset: true })).toBe(true);
    expect(resolveSaveOutputDataset({ saveOutputDataset: false }, true)).toBe(false);
  });
});

describe('buildSaveableLiveOutputs', () => {
  const outputs = [
    { nodeId: 'a', output: { path: 'art_a', dataType: 'dataframe' } },
    { nodeId: 'b', output: { path: 'art_b', dataType: 'dataframe' } },
  ];

  test('excludes outputs whose node has saving disabled (default off)', () => {
    const nodes = [
      { id: 'a', data: { nodeId: 'a' } },
      { id: 'b', data: { nodeId: 'b' } },
    ];
    expect(buildSaveableLiveOutputs(outputs, nodes, false)).toBeUndefined();
  });

  test('includes only nodes with saving enabled', () => {
    const nodes = [
      { id: 'a', data: { nodeId: 'a', saveOutputDataset: true } },
      { id: 'b', data: { nodeId: 'b', saveOutputDataset: false } },
    ];
    const refs = buildSaveableLiveOutputs(outputs, nodes, false);
    expect(refs).toEqual([{ node_id: 'a', filename: 'art_a', data_type: 'dataframe' }]);
  });

  test('honors workflow-wide default when node field unset', () => {
    const nodes = [
      { id: 'a', data: { nodeId: 'a' } },
      { id: 'b', data: { nodeId: 'b' } },
    ];
    const refs = buildSaveableLiveOutputs(outputs, nodes, true);
    expect(refs?.map((r) => r.node_id).sort()).toEqual(['a', 'b']);
  });

  test('returns undefined when there are no outputs', () => {
    expect(buildSaveableLiveOutputs([], [], true)).toBeUndefined();
  });
});
