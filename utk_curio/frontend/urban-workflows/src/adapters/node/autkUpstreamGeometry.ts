import type { FeatureCollection, Geometry } from 'geojson';

/**
 * An upstream frame as a layer autk-db can load, when not every row has a
 * geometry.
 *
 * A collection's rows often do not: a video, a photo that carries no position,
 * a raster that is not georeferenced. autk-db 2.1.2's ``loadGeojson`` reads the
 * layer's kind (points, lines or polygons) off its first feature and refuses
 * the whole layer when that one has no geometry ("First feature has no geometry
 * or geometry type"), while a later feature without one loads as a NULL that
 * autk-map then skips. So only the rows before the first geometry change: each
 * gets an empty geometry of that geometry's kind, which loads, stays out of
 * the layer's bounds and draws nothing. Every row keeps its place, since map
 * picking and a Data Pool's highlights both address rows by their index.
 *
 * Returns the collection itself when its first row has a geometry, and null
 * when no row has one: there is nothing to map.
 */
export function withLoadableFirstFeature(fc: FeatureCollection): FeatureCollection | null {
    const features = Array.isArray(fc?.features) ? fc.features : [];
    const first = features.findIndex((feature) => feature?.geometry != null);
    if (first < 0) return null;
    if (first === 0) return fc;
    const empty = emptyOfKind(features[first].geometry!.type);
    return {
        ...fc,
        features: features.map((feature, index) =>
            index < first ? { ...feature, geometry: empty } : feature,
        ),
    };
}

function emptyOfKind(type: string): Geometry {
    switch (type) {
        case 'Point':
        case 'MultiPoint':
            return { type: 'MultiPoint', coordinates: [] };
        case 'LineString':
        case 'MultiLineString':
            return { type: 'MultiLineString', coordinates: [] };
        default:
            // Polygons, and a GeometryCollection, which autk-db also loads as
            // polygons.
            return { type: 'MultiPolygon', coordinates: [] };
    }
}
