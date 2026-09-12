/**
 * Inference results to a GEODATAFRAME-shaped FeatureCollection.
 *
 * This used to live in the CV Gallery, which meant the gallery was the only
 * thing standing between HF CV Inference and every downstream node: Spatial
 * Join reads `dominant_class` / `dominant_pct` from these properties, and the
 * example's Vega specs read the flattened per-class columns. Retiring the
 * gallery moved the conversion here, so the inference node emits a
 * GEODATAFRAME directly (#276).
 *
 * Kept as a pure function, separate from the behavior, so the shape every
 * downstream consumer depends on can be tested without React.
 */

export interface ResultItem {
  image_id: string;
  image_url?: string;
  latitude?: number;
  longitude?: number;
  class_ratios?: Record<string, number>;
  object_counts?: Record<string, number>;
  detections?: { label: string; confidence: number; bbox: number[] }[];
  /** Present instead of results when one image failed to download or infer. */
  error?: string;
}

/**
 * Where Simple View can fetch the segmentation overlay for an image.
 *
 * Relative on purpose: the path is resolved against the running backend, so a
 * dataflow saved on one deployment still works on another. The route reads
 * WHICH user is asking from the bearer token, which is why Simple View fetches
 * these rather than putting them straight in an `<img src>`.
 */
export function overlayUrlFor(imageId: string): string {
  return `/api/streetvision/inference/overlay/${encodeURIComponent(imageId)}`;
}

export function resultsToFeatureCollection(results: ResultItem[]): any {
  const round = (n: number | null | undefined, places: number) =>
    n == null ? null : Number(n.toFixed(places));

  // A run reports per-image failures in the same array as its successes, as
  // `{image_id, error}` with no geometry and no classes. Carrying those would
  // put a row with no picture and no values in front of the user and skew the
  // dominant-class scan, so they never become features.
  const usable = results.filter(r => r && !r.error);

  // Union of all detected class keys so the table doesn't show holes when
  // one image didn't surface a class that another did.
  const allClassKeys = new Set<string>();
  usable.forEach(r => {
    if (r.class_ratios) Object.keys(r.class_ratios).forEach(k => allClassKeys.add(k));
    if (r.object_counts) Object.keys(r.object_counts).forEach(k => allClassKeys.add(k));
  });

  const features = usable.map(r => {
    const lat = round(r.latitude, 5);
    const lon = round(r.longitude, 5);
    const props: Record<string, any> = {
      image_id: r.image_id,
      image_url: r.image_url,
      latitude: lat,
      longitude: lon,
    };
    allClassKeys.forEach(k => { props[k] = 0; });
    if (r.class_ratios) {
      Object.entries(r.class_ratios).forEach(([k, v]) => { props[k] = round((v as number) * 100, 1); });
      props.analysis_type = 'segmentation';
      // Only a segmentation run writes an overlay PNG.
      props.overlay_url = overlayUrlFor(r.image_id);
    }
    if (r.object_counts) {
      Object.entries(r.object_counts).forEach(([k, v]) => { props[k] = v; });
      props.analysis_type = 'detection';
    }
    let dominantClass: string | null = null;
    let dominantPct = -Infinity;
    allClassKeys.forEach(k => {
      const v = props[k] as number;
      if (typeof v === 'number' && v > dominantPct) { dominantPct = v; dominantClass = k; }
    });
    props.dominant_class = dominantClass;
    props.dominant_pct = dominantPct === -Infinity ? 0 : dominantPct;
    return {
      type: 'Feature',
      geometry: lat != null && lon != null
        ? { type: 'Point', coordinates: [lon, lat] }
        : null,
      properties: props,
    };
  });
  return {
    type: 'FeatureCollection',
    features,
    metadata: { name: 'cv_inference_results' },
  };
}

/**
 * Per-class averages across a run, for the node's own summary.
 *
 * The denominator is the number of images that reported that class, not the
 * number of images, so a class only some images contain is not diluted by the
 * ones that never saw it.
 */
export function aggregateStats(results: ResultItem[]): {
  averages: Record<string, number>;
  classCount: number;
  geoCount: number;
} | null {
  const usable = results.filter(r => r && !r.error);
  if (usable.length === 0) return null;
  const allClasses = new Map<string, number[]>();
  usable.forEach(r => {
    const push = (k: string, v: number) => {
      if (!allClasses.has(k)) allClasses.set(k, []);
      allClasses.get(k)!.push(v);
    };
    if (r.class_ratios) Object.entries(r.class_ratios).forEach(([k, v]) => push(k, v as number));
    if (r.object_counts) Object.entries(r.object_counts).forEach(([k, v]) => push(k, v as number));
  });
  const averages: Record<string, number> = {};
  allClasses.forEach((vals, key) => {
    averages[key] = vals.reduce((a, b) => a + b, 0) / vals.length;
  });
  return {
    averages,
    classCount: allClasses.size,
    geoCount: usable.filter(r => r.latitude != null).length,
  };
}
