/**
 * An upstream frame whose first rows have no geometry still loads as a map
 * layer, with every row in its place.
 */
import type { Feature, FeatureCollection, Geometry } from 'geojson';

import { withLoadableFirstFeature } from '../../../adapters/node/autkUpstreamGeometry';

function feature(geometry: Geometry | null, name: string): Feature {
    return { type: 'Feature', geometry: geometry as Geometry, properties: { name } };
}

function collection(...features: Feature[]): FeatureCollection {
    return { type: 'FeatureCollection', features };
}

const point: Geometry = { type: 'Point', coordinates: [-87.63, 41.88] };

describe('withLoadableFirstFeature', () => {
    test('a frame whose first row has a geometry is used as it is', () => {
        const fc = collection(feature(point, 'a'), feature(null, 'b'));
        expect(withLoadableFirstFeature(fc)).toBe(fc);
    });

    test('rows before the first geometry get an empty one of its kind, and keep their place', () => {
        const fc = collection(feature(null, 'video'), feature(null, 'no position'), feature(point, 'photo'), feature(null, 'later'));
        const out = withLoadableFirstFeature(fc)!;
        expect(out.features.map((f) => f.properties!.name)).toEqual(['video', 'no position', 'photo', 'later']);
        expect(out.features[0].geometry).toEqual({ type: 'MultiPoint', coordinates: [] });
        expect(out.features[1].geometry).toEqual({ type: 'MultiPoint', coordinates: [] });
        expect(out.features[2].geometry).toBe(point);
        // A later row without one loads as NULL, which the map already skips.
        expect(out.features[3].geometry).toBeNull();
        // The input is not changed.
        expect(fc.features[0].geometry).toBeNull();
    });

    test.each([
        [{ type: 'LineString', coordinates: [[0, 0], [1, 1]] }, 'MultiLineString'],
        [{ type: 'MultiLineString', coordinates: [[[0, 0], [1, 1]]] }, 'MultiLineString'],
        [{ type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] }, 'MultiPolygon'],
        [{ type: 'GeometryCollection', geometries: [] }, 'MultiPolygon'],
    ] as [Geometry, string][])('a %o layer gets an empty %s', (geometry, kind) => {
        const out = withLoadableFirstFeature(collection(feature(null, 'x'), feature(geometry, 'y')))!;
        expect(out.features[0].geometry).toEqual({ type: kind, coordinates: [] });
    });

    test('a frame with no geometry at all has nothing to map', () => {
        expect(withLoadableFirstFeature(collection(feature(null, 'a'), feature(null, 'b')))).toBeNull();
        expect(withLoadableFirstFeature(collection())).toBeNull();
    });
});
