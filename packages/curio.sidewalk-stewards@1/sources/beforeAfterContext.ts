import type { FeatureCollection } from './geojson';
import type { SidewalkTileEditConfig } from './SidewalkTileEditor';
import { assetUrl, fetchData } from './resourceResolver';
import { buildOverview, stableJson, validateOverview, type OverviewContext } from './overviewData';

export const CONTEXT_SCHEMA = 'io.github.lzml0.sidewalk-stewards/context/v1';
export interface ImageSource {
  kind: 'sidewalk-image'; datasetId: string; sha256: string;
  source: { type: 'geotiff'; geotiffFileUrl: string; outputTableName: string; coordinateFormat: string };
  gridUrl: string; boundariesUrl: string; imageUrlTemplate: string;
  georeferencing: { crs: string; bounds: number[]; gridSha256: string; mapping: string };
}
export interface NetworkSource {
  kind: 'sidewalk-network'; datasetId: string; url: string; sha256: string; crs: 'EPSG:4326'; data: FeatureCollection;
}
export interface PreparedContext extends OverviewContext {
  schema: typeof CONTEXT_SCHEMA; image: ImageSource; original: Omit<NetworkSource, 'data'>; sourceIdentity: string;
  measurements?: FeatureCollection;
}
const collection = (v: any): v is FeatureCollection => v?.type === 'FeatureCollection' && Array.isArray(v.features);
const hash = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
function path(v: unknown): v is string {
  return typeof v === 'string' && !!v && v === v.trim() && !/\s/.test(v)
    && !v.startsWith('//') && (!/^[a-z][a-z0-9+.-]*:/i.test(v) || /^https?:\/\//i.test(v));
}
export async function hydrate(value: any, signal?: AbortSignal): Promise<any> {
  if (typeof value === 'string') {
    if (!value.trim()) return null;
    try { return hydrate(JSON.parse(value), signal); } catch { return hydrate(await fetchData(value, signal), signal); }
  }
  if (value?.path && !value.data) return hydrate({ ...value, path: undefined, data: await fetchData(value.path, signal) }, signal);
  if (value?.dataType === 'dict') return hydrate(value.data, signal);
  if (value?.dataType === 'outputs') return { ...value, data: await Promise.all((value.data ?? []).map((v: any) => hydrate(v, signal))) };
  return value;
}
export async function sha256(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map(v => v.toString(16).padStart(2, '0')).join('');
}
/** Both real Data Loading dicts must be supplied through separate input circles. */
export async function prepareContext(input: unknown, load = async (url: string, signal?: AbortSignal) => {
  const response = await fetch(assetUrl(url), { signal });
  if (!response.ok) throw new Error(`Declared context resource failed (HTTP ${response.status}): ${url}`);
  return response.json();
}, digest = sha256, signal?: AbortSignal): Promise<PreparedContext> {
  const bundle = await hydrate(input, signal);
  const values = bundle?.dataType === 'outputs' && Array.isArray(bundle.data) ? bundle.data : [];
  const images = values.filter((v: any) => v?.kind === 'sidewalk-image');
  const networks = values.filter((v: any) => v?.kind === 'sidewalk-network');
  if (images.length !== 1 || networks.length !== 1 || values.length !== 2) throw new Error('Required inputs: one satellite reference and one original network in separate Sidewalk Prepare input circles.');
  const image: ImageSource = images[0], original: NetworkSource = networks[0];
  const source = image.source;
  if (!image.datasetId || image.datasetId !== original.datasetId || !hash(image.sha256) || !hash(original.sha256)
    || !hash(image.georeferencing?.gridSha256) || !image.georeferencing?.mapping
    || !image.georeferencing.crs || image.georeferencing.bounds?.length !== 4 || !image.georeferencing.bounds.every(Number.isFinite)
    || source?.type !== 'geotiff' || !path(source.geotiffFileUrl) || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(source.outputTableName)
    || ['upstream', 'sidewalk_network', 'tile_boundaries'].includes(source.outputTableName)
    || !/^EPSG:[1-9]\d*$/.test(source.coordinateFormat) || source.coordinateFormat !== image.georeferencing.crs
    || !path(image.gridUrl) || !path(image.boundariesUrl) || !path(image.imageUrlTemplate)
    || !image.imageUrlTemplate.includes('{tile_id}') || !path(original.url) || original.crs !== 'EPSG:4326' || !collection(original.data)) {
    throw new Error('Invalid or mismatched satellite/network source identity, GeoTIFF reference, CRS or declared resources.');
  }
  const [grid, boundaries] = await Promise.all([load(image.gridUrl, signal), load(image.boundariesUrl, signal)]);
  if (!collection(grid) || !collection(boundaries)) throw new Error('Declared grid and boundaries must be GeoJSON FeatureCollections.');
  const context = { grid: { ...grid, features: grid.features.map(f => ({ ...f, properties: { ...f.properties,
    image_url: image.imageUrlTemplate.replace('{tile_id}', String(f.properties?.tile_id ?? '')) } })) }, network: original.data, boundaries };
  validateOverview(context);
  const sourceIdentity = await digest(stableJson([image, original, grid, boundaries]));
  return { ...context, schema: CONTEXT_SCHEMA, image, original: { kind: original.kind, datasetId: original.datasetId,
    url: original.url, sha256: original.sha256, crs: original.crs }, sourceIdentity };
}
export function contextConfig(context: PreparedContext, persisted: SidewalkTileEditConfig): SidewalkTileEditConfig {
  return { ...persisted, mode: 'input-overview', imageUrlTemplate: context.image.imageUrlTemplate,
    networkUrlTemplate: context.original.url, overview: { datasetId: context.image.datasetId,
      gridUrl: context.image.gridUrl, boundariesUrl: context.image.boundariesUrl, networkUrl: context.original.url,
      sourceIdentity: context.sourceIdentity } };
}
/** Keep sparse measured rows separate from the complete editing and map grid. */
export function withTileMeasurements(context: PreparedContext, measurements: FeatureCollection, fields: string[]): PreparedContext {
  if (!collection(measurements) || !fields.length || !fields.every(field => typeof field === 'string' && !!field.trim() && field !== 'tile_id')) {
    throw new Error('Tile measurements require a GeoJSON FeatureCollection and named metric fields.');
  }
  const byId = new Map<string, Record<string, number>>();
  const gridIds = new Set(context.grid.features.map(feature => String(feature.properties?.tile_id)));
  for (const feature of measurements.features) {
    const id = feature.properties?.tile_id;
    if (id === undefined || id === null || !gridIds.has(String(id)) || byId.has(String(id))) {
      throw new Error(`Tile measurement has a missing, duplicate, or unknown tile ID: ${String(id)}`);
    }
    const values: Record<string, number> = {};
    for (const field of fields) {
      const value = feature.properties?.[field];
      if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`Invalid measured ${field} for tile ${String(id)}`);
      values[field] = value;
    }
    byId.set(String(id), values);
  }
  return { ...context, measurements: { ...measurements, features: measurements.features.map(feature => ({ ...feature,
    properties: { tile_id: feature.properties?.tile_id, ...byId.get(String(feature.properties?.tile_id)) } })) } };
}
export function contextOutput(context: PreparedContext, config: SidewalkTileEditConfig, latest?: unknown) {
  const output = buildOverview(context, contextConfig(context, config), latest);
  return { ...output, data: [...output.data, { dataType: 'dict', data: { ...context.image.source } },
    ...(context.measurements ? [{ dataType: 'geodataframe', layerName: 'sidewalk_typology', layerType: 'polygons', data: context.measurements }] : [])],
    metadata: { ...output.metadata, sidewalkContext: { schema: CONTEXT_SCHEMA, image: context.image,
      original: context.original, sourceIdentity: context.sourceIdentity } } };
}
/** Reads only the explicit preparation output; legacy fixed fixtures are never a fallback. */
export async function readPreparedContext(input: unknown, signal?: AbortSignal): Promise<PreparedContext> {
  const value = await hydrate(input, signal), metadata = value?.metadata?.sidewalkContext;
  const layers = value?.dataType === 'outputs' && Array.isArray(value.data) ? value.data : [];
  const grid = layers.find((v: any) => v?.layerName === 'upstream')?.data;
  const network = layers.find((v: any) => v?.layerName === 'sidewalk_network')?.data;
  const boundaries = layers.find((v: any) => v?.layerName === 'tile_boundaries')?.data;
  const measurements = layers.find((v: any) => v?.layerName === 'sidewalk_typology')?.data;
  if (metadata?.schema !== CONTEXT_SCHEMA || !hash(metadata.sourceIdentity) || !collection(grid) || !collection(network) || !collection(boundaries)) {
    throw new Error('Prepared satellite and original-network inputs are required. Connect Sidewalk Prepare; no fixture fallback is used.');
  }
  if (measurements !== undefined && !collection(measurements)) throw new Error('Invalid prepared measured tile layer.');
  const context = { ...metadata, grid, network, boundaries, ...(measurements ? { measurements } : {}) } as PreparedContext;
  validateOverview(context);
  return context;
}
