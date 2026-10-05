/**
 * autk-core's `LayerType` values a GeoJSON source can be loaded as. A
 * geodataframe whose `metadata` names one loads into an Autark node as that
 * layer. KEEP IN SYNC with `AUTARK_LAYER_TYPES` in
 * `backend/app/datasets/domain/constants.py`.
 */
export const AUTARK_LAYER_TYPES: ReadonlySet<string> = new Set([
  "background", "surface", "parks", "water", "roads", "buildings", "points", "polygons", "polylines",
]);
