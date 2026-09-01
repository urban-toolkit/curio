import {
  flowOutputRefFromRaw,
  normalizeFlowInput,
  sandboxArtifactId,
} from '../../utils/flowOutputRef';

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

  test('includes tuple outputs bundle with dataType', () => {
    expect(flowOutputRefFromRaw('utci-node', {
      path: '1780604607968_abc',
      dataType: 'outputs',
    })).toEqual({
      node_id: 'utci-node',
      filename: '1780604607968_abc',
      data_type: 'outputs',
    });
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

describe('normalizeFlowInput', () => {
  test('maps sandbox output and persisted filename refs', () => {
    expect(normalizeFlowInput({
      path: 'LY89307895198_077f721c',
      dataType: 'dataframe',
      dataset: '1780437932988_abc_output.parquet',
    })).toEqual({
      path: 'LY89307895198_077f721c',
      dataType: 'dataframe',
      dataset: '1780437932988_abc_output.parquet',
    });

    expect(normalizeFlowInput('artifact_id')).toEqual({ path: 'artifact_id' });
    expect(normalizeFlowInput('')).toBe('');
  });

  test('returns a fresh object on each call', () => {
    const raw = { path: 'a', dataType: 'dataframe' };
    const first = normalizeFlowInput(raw);
    const second = normalizeFlowInput(raw);
    expect(first).not.toBe(raw);
    expect(second).not.toBe(first);
  });

  test('passes through merge output bundles without artifact paths', () => {
    const mergeOut = {
      dataType: 'outputs',
      data: [{ path: 'a', dataType: 'dataframe' }, { path: 'b', dataType: 'dataframe' }],
    };
    const normalized = normalizeFlowInput(mergeOut);
    expect(normalized).toEqual(mergeOut);
    expect(normalized).not.toBe(mergeOut);
  });
});

describe('sandboxArtifactId', () => {
  test('prefers DuckDB path over catalog dataset parquet for /get', () => {
    expect(sandboxArtifactId({
      path: 'LY89307895198_077f721c',
      dataType: 'dataframe',
      dataset: '1780437932988_443646f8_output.parquet',
    })).toBe('LY89307895198_077f721c');
  });

  test('accepts bare path string and persisted filename', () => {
    expect(sandboxArtifactId('artifact_id')).toBe('artifact_id');
    expect(sandboxArtifactId({ filename: 'artifact_id' })).toBe('artifact_id');
  });

  test('falls back to dataset when path is missing', () => {
    expect(sandboxArtifactId({
      dataset: '1780437932988_443646f8_output.parquet',
      dataType: 'dataframe',
    })).toBe('1780437932988_443646f8_output.parquet');
  });
});
