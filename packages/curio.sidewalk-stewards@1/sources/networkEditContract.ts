import type { Feature, FeatureCollection } from './geojson';

/** Versioned package-owned interaction payload sent only across interaction edges. */
export const SIDEWALK_NETWORK_EDIT_CHANNEL = 'sidewalk.network-edit';
export const SIDEWALK_NETWORK_EDIT_SCHEMA = 'io.github.lzml0.sidewalk-stewards/network-edit' as const;
export interface SidewalkNetworkEdit {
  schema: typeof SIDEWALK_NETWORK_EDIT_SCHEMA;
  version: 1;
  tileId: string;
  editRevision: number;
  operationTypes: string[];
  tileFeature: Feature;
  before: FeatureCollection;
  after: FeatureCollection;
  provenance: Record<string, unknown>;
}

export function makeNetworkEditEnvelope(edit: Omit<SidewalkNetworkEdit, 'schema' | 'version'>): SidewalkNetworkEdit {
  return { schema: SIDEWALK_NETWORK_EDIT_SCHEMA, version: 1, ...edit };
}

export function isSidewalkNetworkEdit(value: unknown): value is SidewalkNetworkEdit {
  const edit = value as SidewalkNetworkEdit | null;
  return !!edit && edit.schema === SIDEWALK_NETWORK_EDIT_SCHEMA && edit.version === 1
    && typeof edit.tileId === 'string' && Number.isInteger(edit.editRevision)
    && edit.after?.type === 'FeatureCollection' && Array.isArray(edit.after.features);
}
