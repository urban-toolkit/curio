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

  test('force-disables saving on dataset-palette nodes regardless of toggle/default', () => {
    const datasetNode: any = { saveOutputDataset: true, datasetSource: { datasetId: 'd1' } };
    expect(resolveSaveOutputDataset(datasetNode)).toBe(false);
    expect(resolveSaveOutputDataset(datasetNode, true)).toBe(false);
  });

  test('does NOT force-off a producer node (no datasetSource) — it must keep saving', () => {
    // Producer linkage is derived from the catalog, never stamped as datasetSource,
    // so a node that generates a dataset keeps its save toggle.
    const producerNode: any = { saveOutputDataset: true };
    expect(resolveSaveOutputDataset(producerNode)).toBe(true);
    expect(resolveSaveOutputDataset({}, true)).toBe(true);
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

  test('excludes dataset-palette nodes even when the default is on', () => {
    const nodes = [
      { id: 'a', data: { nodeId: 'a' } },
      { id: 'b', data: { nodeId: 'b', datasetSource: { datasetId: 'd1' } } },
    ];
    const refs = buildSaveableLiveOutputs(outputs, nodes, true);
    expect(refs).toEqual([{ node_id: 'a', filename: 'art_a', data_type: 'dataframe' }]);
  });
});

describe('buildSaveableLiveOutputs sink-node exclusion', () => {
  test('vis nodes (which pass input through) never produce a saveable dataset', () => {
    const outputs = [
      { nodeId: 'transform', output: '1782_3d8f71d7_output.parquet' },
      { nodeId: 'visnode', output: '1782_3d8f71d7_output.parquet' }, // passthrough of input
    ];
    const nodes = [
      { id: 'transform', type: 'curio.builtin/data-transformation', data: { nodeId: 'transform' } },
      { id: 'visnode', type: 'curio.builtin/vis-vega', data: { nodeId: 'visnode' } },
    ];
    const refs = buildSaveableLiveOutputs(outputs, nodes, true) ?? [];
    const ids = refs.map((r) => r.node_id);
    expect(ids).toContain('transform');
    expect(ids).not.toContain('visnode'); // the vis node's passthrough is not saved
  });

  test('vis-simple is also excluded', () => {
    const outputs = [{ nodeId: 'v', output: 'x.parquet' }];
    const nodes = [{ id: 'v', type: 'curio.builtin/vis-simple', data: { nodeId: 'v' } }];
    expect(buildSaveableLiveOutputs(outputs, nodes, true)).toBeUndefined();
  });

  test('versioned sink types (palette-dragged, @1) are excluded too (#169)', () => {
    const outputs = [{ nodeId: 'v', output: 'x.parquet' }];
    const nodes = [{ id: 'v', type: 'curio.builtin/vis-vega@1', data: { nodeId: 'v' } }];
    expect(buildSaveableLiveOutputs(outputs, nodes, true)).toBeUndefined();
  });

  test('universal-node form with a versioned data.nodeType is excluded (#169)', () => {
    const outputs = [{ nodeId: 'v', output: 'x.parquet' }];
    const nodes = [{
      id: 'v',
      type: '__curioUniversalNode',
      data: { nodeId: 'v', nodeType: 'curio.builtin/vis-simple@2' },
    }];
    expect(buildSaveableLiveOutputs(outputs, nodes, true)).toBeUndefined();
  });

  test('a versioned NON-sink type still saves', () => {
    const outputs = [{ nodeId: 't', output: 'y.parquet' }];
    const nodes = [{ id: 't', type: 'curio.builtin/data-transformation@1', data: { nodeId: 't' } }];
    const refs = buildSaveableLiveOutputs(outputs, nodes, true) ?? [];
    expect(refs.map((r) => r.node_id)).toContain('t');
  });
});

describe('isNonProducingNodeType', () => {
  const { isNonProducingNodeType } = require('../../utils/saveOutputDataset');

  test('matches unversioned and versioned sink types', () => {
    expect(isNonProducingNodeType('curio.builtin/vis-vega')).toBe(true);
    expect(isNonProducingNodeType('curio.builtin/vis-vega@1')).toBe(true);
    expect(isNonProducingNodeType('curio.builtin/vis-simple@12')).toBe(true);
  });

  test('rejects non-sink types in either form', () => {
    expect(isNonProducingNodeType('curio.builtin/data-transformation')).toBe(false);
    expect(isNonProducingNodeType('curio.builtin/data-transformation@1')).toBe(false);
    expect(isNonProducingNodeType('')).toBe(false);
  });
});
