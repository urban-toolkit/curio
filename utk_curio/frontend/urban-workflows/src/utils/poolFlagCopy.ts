/**
 * A copy of one Data Pool layer that its `interacted` flags can be written
 * into.
 *
 * The objects a pool reads are never its own to change: an inline input is
 * its upstream node's object, and an output it already sent is held by every
 * chart downstream, which may read it again later. So the pool flags a copy
 * and sends that (#582). Only the flags differ, so only what holds them is
 * copied: a geodataframe's features and their properties, a dataframe's
 * `interacted` column. Geometry and the other columns are shared.
 */
export function copyForFlags(layer: any): any {
  if (!layer || typeof layer !== "object") return layer;
  const data = layer.data;
  if (layer.dataType === "geodataframe" && Array.isArray(data?.features)) {
    return {
      ...layer,
      data: {
        ...data,
        features: data.features.map((feature: any) => ({
          ...feature,
          properties: { ...(feature?.properties ?? {}) },
        })),
      },
    };
  }
  if (data && typeof data === "object" && !Array.isArray(data)) {
    const copied = { ...data };
    if (data.interacted && typeof data.interacted === "object") copied.interacted = { ...data.interacted };
    return { ...layer, data: copied };
  }
  return { ...layer };
}
