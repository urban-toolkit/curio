import type { Feature, FeatureCollection } from './geojson';

const stable = (value: unknown) => JSON.stringify(value, (_key, item) => {
  if (!item || Array.isArray(item) || typeof item !== 'object') return item;
  return Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b)));
});

/** Deterministic lightweight source fingerprint when no source revision exists. */
export function geometryHash(collection: FeatureCollection): string {
  const input = stable(collection);
  let hash = 2166136261;
  for (let i = 0; i < input.length; i += 1) hash = Math.imul(hash ^ input.charCodeAt(i), 16777619);
  return `fnv1a32:${(hash >>> 0).toString(16).padStart(8, '0')}`;
}

function idOf(feature: Feature, index: number): string {
  return String(feature.id ?? feature.properties?.feature_id ?? feature.properties?.id ?? `row:${index}`);
}

export function buildEditProvenance(args: {
  tileId: string; operations: string[]; before: FeatureCollection; after: FeatureCollection;
  editRevision: number; validationWarnings: string[]; sourceRevision?: string | null;
}) {
  const beforeById = new Map(args.before.features.map((feature, index) => [idOf(feature, index), stable(feature.geometry)]));
  const afterById = new Map(args.after.features.map((feature, index) => [idOf(feature, index), stable(feature.geometry)]));
  const affectedFeatureIds = [...new Set([...beforeById.keys(), ...afterById.keys()])]
    .filter(id => beforeById.get(id) !== afterById.get(id)).sort();
  return {
    schema: 'io.github.lzml0.sidewalk-stewards/provenance', version: 1,
    selectedTileId: args.tileId,
    operations: args.operations.map((type, index) => ({ sequence: index + 1, type })),
    affectedFeatureIds,
    sourceRevision: args.sourceRevision ?? geometryHash(args.before),
    before: args.before,
    after: args.after,
    editRevision: args.editRevision,
    timestamp: new Date().toISOString(),
    validationWarnings: [...args.validationWarnings],
  };
}
