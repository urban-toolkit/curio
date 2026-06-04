import { flowOutputRefFromRaw } from '../../utils/flowOutputRef';

describe('flowOutputRefFromRaw', () => {
  test('prefers dataset parquet and includes dataType', () => {
    const ref = flowOutputRefFromRaw('node-1', {
      path: 'artifact-id',
      dataType: 'dataframe',
      dataset: '1234_abcd_output.parquet',
    });
    expect(ref).toEqual({
      node_id: 'node-1',
      filename: '1234_abcd_output.parquet',
      data_type: 'dataframe',
    });
  });

  test('skips tuple outputs bundle', () => {
    expect(
      flowOutputRefFromRaw('utci-node', {
        path: '1780604607968_abc',
        dataType: 'outputs',
      }),
    ).toBeNull();
  });

  test('falls back to path with dataType for raster', () => {
    const ref = flowOutputRefFromRaw('node-2', {
      path: '1780602628735_abc',
      dataType: 'raster',
    });
    expect(ref).toEqual({
      node_id: 'node-2',
      filename: '1780602628735_abc',
      data_type: 'raster',
    });
  });
});
