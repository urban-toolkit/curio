import type { FeatureCollection, Position } from './geojson';
import type { Bounds } from './sidewalkEditOperations';

export type SidewalkTopologyWarning = {
  code: 'dangling_endpoint' | 'duplicate_segment';
  message: string;
  featureIndexes: number[];
};

const coordinateKey = (point: Position): string =>
  `${Math.round(point[0] * 1e8)},${Math.round(point[1] * 1e8)}`;

function endpointOnTileBoundary(point: Position, bounds: Bounds): boolean {
  const tolerance = Math.max(bounds[2] - bounds[0], bounds[3] - bounds[1], 1) * 1e-7;
  return Math.abs(point[0] - bounds[0]) <= tolerance
    || Math.abs(point[0] - bounds[2]) <= tolerance
    || Math.abs(point[1] - bounds[1]) <= tolerance
    || Math.abs(point[1] - bounds[3]) <= tolerance;
}

/** Sidewalk-specific diagnostics. These are advisory until domain rules are approved. */
export function validateSidewalkTopology(
  collection: FeatureCollection,
  bounds: Bounds,
): SidewalkTopologyWarning[] {
  const endpointFeatures = new Map<string, Set<number>>();
  const duplicateSegments = new Map<string, Set<number>>();

  collection.features.forEach((feature, featureIndex) => {
    const geometry = feature.geometry;
    if (!geometry || geometry.type !== 'LineString' || geometry.coordinates.length < 2) return;
    const coordinates = geometry.coordinates as Position[];
    for (const endpoint of [coordinates[0], coordinates[coordinates.length - 1]]) {
      const key = coordinateKey(endpoint);
      const indexes = endpointFeatures.get(key) ?? new Set<number>();
      indexes.add(featureIndex);
      endpointFeatures.set(key, indexes);
    }
    for (let index = 1; index < coordinates.length; index += 1) {
      const a = coordinateKey(coordinates[index - 1]);
      const b = coordinateKey(coordinates[index]);
      const key = a < b ? `${a}|${b}` : `${b}|${a}`;
      const indexes = duplicateSegments.get(key) ?? new Set<number>();
      indexes.add(featureIndex);
      duplicateSegments.set(key, indexes);
    }
  });

  const warnings: SidewalkTopologyWarning[] = [];
  const danglingIndexes = new Set<number>();
  for (const [key, indexes] of endpointFeatures) {
    if (indexes.size !== 1) continue;
    const [x, y] = key.split(',').map(value => Number(value) / 1e8);
    if (endpointOnTileBoundary([x, y], bounds)) continue;
    indexes.forEach(index => danglingIndexes.add(index));
  }
  if (danglingIndexes.size > 0) {
    warnings.push({
      code: 'dangling_endpoint',
      message: `${danglingIndexes.size} network feature(s) have endpoints that do not connect to another feature or reach the tile edge.`,
      featureIndexes: [...danglingIndexes].sort((a, b) => a - b),
    });
  }

  const duplicateIndexes = new Set<number>();
  for (const indexes of duplicateSegments.values()) {
    if (indexes.size > 1) indexes.forEach(index => duplicateIndexes.add(index));
  }
  if (duplicateIndexes.size > 0) {
    warnings.push({
      code: 'duplicate_segment',
      message: `Overlapping network segments appear in ${duplicateIndexes.size} feature(s).`,
      featureIndexes: [...duplicateIndexes].sort((a, b) => a - b),
    });
  }
  return warnings;
}
