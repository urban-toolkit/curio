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

describe("DATA_POOL is a save-trigger extra, not a shared sink", () => {
  // FlowProvider.scheduleInstallSync skips `isNonProducingNodeType(t) ||
  // t === DATA_POOL`. The second clause is only load-bearing while DATA_POOL
  // stays OUT of the shared sink set: the backend must keep pruning rights over
  // data-pool refs, so the two sides deliberately disagree here. If someone
  // "tidies" DATA_POOL into NON_PRODUCING_NODE_TYPES, this fails loudly.
  const {
    isNonProducingNodeType,
    NON_PRODUCING_NODE_TYPES,
  } = require('../../utils/saveOutputDataset');
  const DATA_POOL = 'curio.builtin/data-pool';

  test('DATA_POOL is not in the shared sink set', () => {
    expect(NON_PRODUCING_NODE_TYPES.has(DATA_POOL)).toBe(false);
    expect(isNonProducingNodeType(DATA_POOL)).toBe(false);
    expect(isNonProducingNodeType(`${DATA_POOL}@1`)).toBe(false);
  });

  test('the shared sink set is exactly the two view nodes', () => {
    expect([...NON_PRODUCING_NODE_TYPES].sort()).toEqual([
      'curio.builtin/vis-simple',
      'curio.builtin/vis-vega',
    ]);
  });
});

/**
 * Pinning a node to the dashboard is a promise that its tile will draw when
 * someone opens the page, which only holds if the output behind it was saved.
 * So a dashboard source saves whatever its own toggle says.
 *
 * The two directions are both quiet failures: miss a source and the tile is an
 * empty box on a page the owner shared; save too much and the user's Data
 * Catalog fills with rows nothing reads.
 */
describe('outputs a dashboard tile depends on', () => {
  const { shouldSaveOutputOnRun } = require('../../utils/saveOutputDataset');

  // `type` is the React Flow sentinel every canvas node carries; the sink check
  // reads the real kind through it (getFlowNodeCanonicalType), so a fixture
  // without it is not a vis node as far as the filter is concerned.
  const producer = {
    id: 'py',
    type: '__curioUniversalNode',
    data: { nodeId: 'py', nodeType: 'curio.builtin/computation-analysis' },
  };
  const chart = {
    id: 'chart',
    type: '__curioUniversalNode',
    data: { nodeId: 'chart', nodeType: 'curio.builtin/vis-vega' },
  };
  const outputs = [
    { nodeId: 'py', output: { path: 'art_py', dataType: 'dataframe' } },
    { nodeId: 'chart', output: { path: 'art_py', dataType: 'dataframe' } },
  ];

  test('a source is recorded even with its toggle off', () => {
    const refs = buildSaveableLiveOutputs(outputs, [producer, chart], false, new Set(['py']));

    expect(refs?.map((r: any) => r.node_id)).toEqual(['py']);
  });

  test('a view node is still excluded, even pinned', () => {
    // A chart passes its input through; saving it would duplicate the producer's
    // dataset under the chart's name.
    const refs = buildSaveableLiveOutputs(outputs, [producer, chart], false, new Set(['chart']));

    expect(refs).toBeUndefined();
  });

  test('a dataset-palette node feeding a tile is recorded', () => {
    // Its ref resolves against the dataset it reads, so a reload restores the
    // tile's data; the backend installers know not to copy it again.
    const palette = {
      id: 'ds',
      type: '__curioUniversalNode',
      data: {
        nodeId: 'ds',
        nodeType: 'curio.builtin/data-loading',
        datasetSource: { datasetId: 'd1' },
      },
    };
    const paletteOutputs = [{ nodeId: 'ds', output: { path: 'art_ds', dataType: 'dataframe' } }];

    const refs = buildSaveableLiveOutputs(paletteOutputs, [palette], false, new Set(['ds']));

    expect(refs?.map((r: any) => r.node_id)).toEqual(['ds']);
  });

  test('no dashboard sources leaves the toggle in charge', () => {
    expect(buildSaveableLiveOutputs(outputs, [producer, chart], false, new Set())).toBeUndefined();
    expect(buildSaveableLiveOutputs(outputs, [producer, chart], false, null)).toBeUndefined();
    expect(
      buildSaveableLiveOutputs(outputs, [producer, chart], true, new Set())?.map((r: any) => r.node_id),
    ).toEqual(['py']);
  });

  test('shouldSaveOutputOnRun follows the pin, and never a palette node', () => {
    expect(shouldSaveOutputOnRun({}, false, true)).toBe(true);
    expect(shouldSaveOutputOnRun({}, false, false)).toBe(false);
    // An explicit toggle still wins on its own.
    expect(shouldSaveOutputOnRun({ saveOutputDataset: true }, false, false)).toBe(true);
    // A palette node only ever loads; it has nothing new to save.
    expect(
      shouldSaveOutputOnRun({ datasetSource: { datasetId: 'd1' } }, false, true),
    ).toBe(false);
  });
});
