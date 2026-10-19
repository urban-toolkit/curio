import type { Feature, FeatureCollection, LineString, Position } from './geojson';

export type Bounds = [number, number, number, number];
export type NetworkFeature = Feature<LineString>;

const round = (n: number) => Math.round(n * 1e8) / 1e8;
const pointKey = (p: Position) => `${round(p[0])},${round(p[1])}`;

export function featureBounds(feature: Feature | undefined): Bounds | null {
  if (!feature?.geometry || !('coordinates' in feature.geometry)) return null;
  const coords: Position[] = [];
  const visit = (value: unknown): void => {
    if (!Array.isArray(value)) return;
    if (typeof value[0] === 'number' && typeof value[1] === 'number') {
      coords.push(value as Position);
      return;
    }
    value.forEach(visit);
  };
  visit(feature.geometry.coordinates);
  if (!coords.length) return null;
  return [
    Math.min(...coords.map(p => p[0])), Math.min(...coords.map(p => p[1])),
    Math.max(...coords.map(p => p[0])), Math.max(...coords.map(p => p[1])),
  ];
}

/** Liang–Barsky clipping of one segment to a tile's rectangular bounds. */
function clipSegment(a: Position, b: Position, bounds: Bounds): [Position, Position] | null {
  const [xmin, ymin, xmax, ymax] = bounds;
  const dx = b[0] - a[0]; const dy = b[1] - a[1];
  let lo = 0; let hi = 1;
  const tests: Array<[number, number]> = [
    [-dx, a[0] - xmin], [dx, xmax - a[0]], [-dy, a[1] - ymin], [dy, ymax - a[1]],
  ];
  for (const [p, q] of tests) {
    if (p === 0) { if (q < 0) return null; continue; }
    const t = q / p;
    if (p < 0) lo = Math.max(lo, t); else hi = Math.min(hi, t);
    if (lo > hi) return null;
  }
  return [
    [a[0] + lo * dx, a[1] + lo * dy],
    [a[0] + hi * dx, a[1] + hi * dy],
  ];
}

/** Clip line features to a selected tile and preserve their properties/IDs. */
export function clipNetworkToBounds(fc: FeatureCollection, bounds: Bounds): FeatureCollection {
  const features: Feature[] = [];
  for (const feature of fc.features) {
    const geometry = feature.geometry;
    if (!geometry || geometry.type !== 'LineString') continue;
    const parts: Position[][] = [];
    let active: Position[] = [];
    for (let i = 1; i < geometry.coordinates.length; i += 1) {
      const segment = clipSegment(geometry.coordinates[i - 1], geometry.coordinates[i], bounds);
      if (!segment) { if (active.length > 1) parts.push(active); active = []; continue; }
      const [a, b] = segment;
      if (!active.length || pointKey(active[active.length - 1]) !== pointKey(a)) {
        if (active.length > 1) parts.push(active);
        active = [a];
      }
      if (pointKey(active[active.length - 1]) !== pointKey(b)) active.push(b);
    }
    if (active.length > 1) parts.push(active);
    parts.forEach((coordinates, partIndex) => {
      features.push({
        ...feature,
        ...(parts.length > 1 ? { id: `${String(feature.id ?? `feature-${features.length}`)}:clip-${partIndex}` } : {}),
        geometry: { type: 'LineString', coordinates },
      } as Feature);
    });
  }
  return { ...fc, features };
}

/** Keep only the parts of linework outside a tile rectangle. Used when an
 * edited tile replaces its old linework in a larger overview network. */
export function removeNetworkInsideBounds(fc: FeatureCollection, bounds: Bounds): FeatureCollection {
  const features: Feature[] = [];
  for (const feature of fc.features) {
    if (feature.geometry?.type !== 'LineString') { features.push(feature); continue; }
    const parts: Position[][] = [];
    let active: Position[] = [];
    const flush = () => { if (active.length > 1) parts.push(active); active = []; };
    for (let i = 1; i < feature.geometry.coordinates.length; i += 1) {
      const a = feature.geometry.coordinates[i - 1];
      const b = feature.geometry.coordinates[i];
      const clipped = clipSegment(a, b, bounds);
      if (!clipped) {
        if (!active.length) active = [a];
        if (pointKey(active[active.length - 1]) !== pointKey(b)) active.push(b);
        continue;
      }
      const [insideA, insideB] = clipped;
      const startsInside = pointKey(a) === pointKey(insideA);
      const endsInside = pointKey(b) === pointKey(insideB);
      if (startsInside) flush();
      else {
        if (!active.length) active = [a];
        if (pointKey(active[active.length - 1]) !== pointKey(insideA)) active.push(insideA);
        flush();
      }
      if (endsInside) flush();
      else {
        active = [insideB];
        if (pointKey(active[active.length - 1]) !== pointKey(b)) active.push(b);
      }
    }
    flush();
    parts.forEach((coordinates, partIndex) => features.push({
      ...feature,
      ...(parts.length > 1 ? { id: `${String(feature.id ?? `feature-${features.length}`)}:outside-${partIndex}` } : {}),
      geometry: { type: 'LineString', coordinates },
    } as Feature));
  }
  return { ...fc, features };
}

function isLineFeature(feature: Feature): feature is NetworkFeature {
  return feature.geometry?.type === 'LineString';
}

export function moveNetworkNode(fc: FeatureCollection, from: Position, to: Position): FeatureCollection {
  const features = fc.features.flatMap(feature => {
    if (!isLineFeature(feature)) return [feature];
    let changed = false;
    const coordinates = feature.geometry.coordinates.reduce<Position[]>((result, position) => {
      const next = pointKey(position) === pointKey(from)
        ? [to[0], to[1], ...position.slice(2)]
        : position;
      if (next !== position) changed = true;
      if (!result.length || pointKey(result[result.length - 1]) !== pointKey(next)) result.push(next);
      else changed = true;
      return result;
    }, []);
    // Dropping a node onto the opposite end of a two-node edge can collapse
    // that edge to a self-loop. Joining graph nodes should not leave invalid
    // zero-length features behind.
    if (coordinates.length < 2 || new Set(coordinates.map(pointKey)).size < 2) return [];
    if (!changed) return [feature];
    return [{
      ...feature,
      geometry: { ...feature.geometry, coordinates },
    } as Feature];
  });
  return { ...fc, features };
}

export function drawNetworkEdge(fc: FeatureCollection, coordinates: Position[]): FeatureCollection {
  if (coordinates.length < 2) return fc;
  const feature: NetworkFeature = {
    type: 'Feature',
    id: `curio-sidewalk-edge-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    // Autark's `roads` layer sizes each feature from `properties.highway`.
    // Missing this tag falls back to a city street width (3.5 m half-width),
    // making newly drawn sidewalk segments much heavier than the input paths.
    properties: { highway: 'path', source: 'curio-sidewalk-tile-edit', edit: 'draw_edge' },
    geometry: { type: 'LineString', coordinates },
  };
  return { ...fc, features: [...fc.features, feature] };
}

export function connectNetworkNodes(fc: FeatureCollection, a: Position, b: Position): FeatureCollection {
  if (pointKey(a) === pointKey(b)) return fc;
  // Stewards' addDrawnEdge checks adjacency within every graph edge, including
  // polylines. A separate GeoJSON feature with the same segment is not an edit.
  const exists = fc.features.some(f => isLineFeature(f) && f.geometry.coordinates.some((p, index) => {
    if (index === 0) return false;
    const previous = f.geometry.coordinates[index - 1];
    return (pointKey(previous) === pointKey(a) && pointKey(p) === pointKey(b))
      || (pointKey(previous) === pointKey(b) && pointKey(p) === pointKey(a));
  }));
  return exists ? fc : drawNetworkEdge(fc, [a, b]);
}

export function splitNetworkEdge(fc: FeatureCollection, featureIndex: number, segmentIndex: number, at: Position): FeatureCollection {
  const source = fc.features[featureIndex];
  if (!source || !isLineFeature(source)) return fc;
  const coords = source.geometry.coordinates;
  if (segmentIndex < 0 || segmentIndex >= coords.length - 1) return fc;
  const left = [...coords.slice(0, segmentIndex + 1), at];
  const right = [at, ...coords.slice(segmentIndex + 1)];
  const common = { ...source, properties: { ...(source.properties ?? {}) } };
  const first = { ...common, id: `${String(source.id ?? `feature-${featureIndex}`)}:a`, properties: { ...common.properties, split_from: source.id ?? featureIndex }, geometry: { type: 'LineString' as const, coordinates: left } };
  const second = { ...common, id: `${String(source.id ?? `feature-${featureIndex}`)}:b`, properties: { ...common.properties, split_from: source.id ?? featureIndex }, geometry: { type: 'LineString' as const, coordinates: right } };
  return { ...fc, features: [...fc.features.slice(0, featureIndex), first, second, ...fc.features.slice(featureIndex + 1)] };
}

export function deleteNetworkNode(fc: FeatureCollection, node: Position): FeatureCollection {
  const features = fc.features.filter(feature => {
      if (!isLineFeature(feature)) return true;
      return !feature.geometry.coordinates.some(position => pointKey(position) === pointKey(node));
    });
  return features.length === fc.features.length ? fc : { ...fc, features };
}

export function deleteNetworkNodesInBounds(fc: FeatureCollection, bounds: Bounds): FeatureCollection {
  const [xmin, ymin, xmax, ymax] = bounds;
  const removed = new Set<string>();
  for (const feature of fc.features) {
    if (!isLineFeature(feature)) continue;
    for (const position of feature.geometry.coordinates) {
      if (position[0] >= xmin && position[0] <= xmax && position[1] >= ymin && position[1] <= ymax) removed.add(pointKey(position));
    }
  }
  const features = fc.features.filter(feature => {
      if (!isLineFeature(feature)) return true;
      const coords = feature.geometry.coordinates;
      return !coords.some(position => removed.has(pointKey(position)));
    });
  return features.length === fc.features.length ? fc : { ...fc, features };
}

/** Stewards' graph indexes every coordinate, including intermediate vertices. */
export function networkNodes(fc: FeatureCollection): Position[] {
  const seen = new Set<string>(); const result: Position[] = [];
  for (const feature of fc.features) {
    if (!isLineFeature(feature)) continue;
    for (const p of feature.geometry.coordinates) {
      const key = pointKey(p);
      if (!seen.has(key)) { seen.add(key); result.push(p); }
    }
  }
  return result;
}

export function endpointNodes(fc: FeatureCollection): Position[] {
  const seen = new Set<string>(); const result: Position[] = [];
  for (const feature of fc.features) {
    if (!isLineFeature(feature) || feature.geometry.coordinates.length < 2) continue;
    for (const p of [feature.geometry.coordinates[0], feature.geometry.coordinates.at(-1)!]) {
      const key = pointKey(p);
      if (!seen.has(key)) { seen.add(key); result.push(p); }
    }
  }
  return result;
}

export function validateNetwork(fc: FeatureCollection, bounds: Bounds): string[] {
  const issues: string[] = [];
  for (const [index, feature] of fc.features.entries()) {
    if (!isLineFeature(feature)) { issues.push(`Feature ${index + 1} is not a LineString.`); continue; }
    if (feature.geometry.coordinates.length < 2) issues.push(`Feature ${index + 1} has fewer than two points.`);
    for (const p of feature.geometry.coordinates) {
      if (!Number.isFinite(p[0]) || !Number.isFinite(p[1])) issues.push(`Feature ${index + 1} contains an invalid coordinate.`);
      if (p[0] < bounds[0] - 1e-9 || p[0] > bounds[2] + 1e-9 || p[1] < bounds[1] - 1e-9 || p[1] > bounds[3] + 1e-9) {
        issues.push(`Feature ${index + 1} extends beyond this tile.`); break;
      }
    }
  }
  return [...new Set(issues)];
}
