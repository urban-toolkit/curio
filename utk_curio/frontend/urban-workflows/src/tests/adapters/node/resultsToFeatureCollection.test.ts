/**
 * The conversion that moved out of the CV Gallery (#276).
 *
 * It is the only thing between HF CV Inference and everything downstream:
 * Spatial Join reads `dominant_class` / `dominant_pct` off these properties,
 * and the example's Vega specs read the flattened per-class columns. The
 * behavior is imported from `packages/` rather than `src/`, the pattern
 * `exampleUiColumnFilter.test.tsx` established, because the package sources are
 * what ships.
 */
import { normalizeFlowInput, flowOutputRefFromRaw } from '../../../utils/flowOutputRef';

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { resultsToFeatureCollection, aggregateStats, overlayUrlFor } = require(
  '../../../../../../../packages/curio.streetvision@1/sources/resultsToFeatureCollection',
);

const segmentation = [
  {
    image_id: 'CAoSL1',
    image_url: 'https://maps.googleapis.test/streetview?pano=CAoSL1',
    latitude: 41.921123456,
    longitude: -87.647812345,
    class_ratios: { vegetation: 0.312, road: 0.208 },
  },
  {
    image_id: 'CAoSL2',
    image_url: 'https://maps.googleapis.test/streetview?pano=CAoSL2',
    latitude: 41.93,
    longitude: -87.64,
    class_ratios: { road: 0.448 },
  },
];

describe('resultsToFeatureCollection', () => {
  it('emits a FeatureCollection of points with percentage class columns', () => {
    const fc = resultsToFeatureCollection(segmentation);
    expect(fc.type).toBe('FeatureCollection');
    expect(fc.metadata).toEqual({ name: 'cv_inference_results' });
    expect(fc.features).toHaveLength(2);
    const [first] = fc.features;
    expect(first.geometry).toEqual({ type: 'Point', coordinates: [-87.64781, 41.92112] });
    expect(first.properties.vegetation).toBe(31.2);
    expect(first.properties.analysis_type).toBe('segmentation');
  });

  it('zero-fills the union of class keys', () => {
    // Load-bearing: the table view derives its columns from features[0] alone,
    // so a class only the first image saw would otherwise make a holey table.
    const fc = resultsToFeatureCollection(segmentation);
    expect(fc.features[1].properties.vegetation).toBe(0);
    expect(Object.keys(fc.features[0].properties)).toEqual(
      expect.arrayContaining(['vegetation', 'road']),
    );
  });

  it('names the dominant class and its percentage, which Spatial Join reads', () => {
    const fc = resultsToFeatureCollection(segmentation);
    expect(fc.features[0].properties.dominant_class).toBe('vegetation');
    expect(fc.features[0].properties.dominant_pct).toBe(31.2);
    expect(fc.features[1].properties.dominant_class).toBe('road');
  });

  it('carries an overlay_url for segmentation, and none for detection', () => {
    const fc = resultsToFeatureCollection(segmentation);
    expect(fc.features[0].properties.overlay_url).toBe(
      '/api/streetvision/inference/overlay/CAoSL1',
    );
    const detection = resultsToFeatureCollection([
      { image_id: 'd1', latitude: 1, longitude: 2, object_counts: { car: 3 } },
    ]);
    expect(detection.features[0].properties.overlay_url).toBeUndefined();
    expect(detection.features[0].properties.analysis_type).toBe('detection');
    expect(detection.features[0].properties.car).toBe(3);
  });

  it('escapes an image id that is not URL-safe', () => {
    expect(overlayUrlFor('a b/c.jpg')).toBe(
      '/api/streetvision/inference/overlay/a%20b%2Fc.jpg',
    );
  });

  it('drops per-image failures instead of emitting empty rows', () => {
    // A run reports failures in the same array as its successes.
    const fc = resultsToFeatureCollection([
      ...segmentation,
      { image_id: 'CAoSL3', error: 'unreadable image_url' },
    ]);
    expect(fc.features).toHaveLength(2);
    expect(fc.features.map((f: any) => f.properties.image_id)).toEqual(['CAoSL1', 'CAoSL2']);
  });

  it('emits null geometry when a result has no coordinates', () => {
    const fc = resultsToFeatureCollection([{ image_id: 'x', class_ratios: { sky: 1 } }]);
    expect(fc.features[0].geometry).toBeNull();
  });

  it('survives Curio propagation intact, and is not taken for an artifact id', () => {
    // The reported bug: a bare string is read as a DuckDB artifact id, so the
    // payload arrived downstream as `{ path: "<the whole blob>" }`.
    const emitted = { data: resultsToFeatureCollection(segmentation), dataType: 'geodataframe' };
    const propagated = normalizeFlowInput(emitted) as any;
    expect(propagated.dataType).toBe('geodataframe');
    expect(propagated.data.features).toHaveLength(2);
    expect(flowOutputRefFromRaw('hf-1', emitted)).toBeNull();
  });
});

describe('aggregateStats', () => {
  it('averages each class over the images that reported it', () => {
    const stats = aggregateStats(segmentation)!;
    expect(stats.classCount).toBe(2);
    expect(stats.geoCount).toBe(2);
    expect(stats.averages.vegetation).toBeCloseTo(0.312);
    // road appeared in both images: (0.208 + 0.448) / 2
    expect(stats.averages.road).toBeCloseTo(0.328);
  });

  it('is null when a run produced nothing usable', () => {
    expect(aggregateStats([])).toBeNull();
    expect(aggregateStats([{ image_id: 'x', error: 'boom' }])).toBeNull();
  });
});
