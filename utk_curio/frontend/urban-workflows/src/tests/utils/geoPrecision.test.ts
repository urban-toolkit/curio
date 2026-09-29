import type { FeatureCollection } from 'geojson';
import { snapCollectionToGrid, snapSourceToGrid } from '../../utils/geoPrecision';

/**
 * The layers a grammar node is handed were clipped once already; autk-db clips
 * them again to the first polygon it loads, and GEOS refused that second
 * intersection on the float noise along shared edges (parks in Back Bay and the
 * Chicago Loop, roads in Niterói). On a 1 cm grid every layer loads.
 */

const park: FeatureCollection = {
    type: 'FeatureCollection',
    features: [{
        type: 'Feature',
        properties: { name: 'park' },
        geometry: {
            type: 'Polygon',
            coordinates: [[[-9754158.482475817, 5112622.884376666], [-9754130.123456789, 5112622.884376666],
                [-9754130.123456789, 5112650.000000004], [-9754158.482475817, 5112622.884376666]]],
        },
    }],
};

describe('snapCollectionToGrid', () => {
    it('rounds meters to the centimeter', () => {
        const out = snapCollectionToGrid(park, 'EPSG:3395');
        expect((out.features[0].geometry as any).coordinates[0][0]).toEqual([-9754158.48, 5112622.88]);
        expect((out.features[0].geometry as any).coordinates[0][2]).toEqual([-9754130.12, 5112650]);
    });

    it('rounds degrees to about a centimeter', () => {
        const fc: FeatureCollection = {
            type: 'FeatureCollection',
            features: [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [-87.6312345678, 41.8812345678] } }],
        };
        expect((snapCollectionToGrid(fc, 'EPSG:4326').features[0].geometry as any).coordinates).toEqual([-87.6312346, 41.8812346]);
    });

    it('reaches into geometry collections and keeps the third coordinate', () => {
        const fc: FeatureCollection = {
            type: 'FeatureCollection',
            features: [{
                type: 'Feature', properties: {},
                geometry: { type: 'GeometryCollection', geometries: [{ type: 'Point', coordinates: [1.23456, 2.34567, 3.45678] }] },
            }],
        };
        const g = snapCollectionToGrid(fc, 'EPSG:3395').features[0].geometry as any;
        expect(g.geometries[0].coordinates).toEqual([1.23, 2.35, 3.46]);
    });

    it('leaves the input as it was, and the properties shared', () => {
        const before = JSON.stringify(park);
        const out = snapCollectionToGrid(park, 'EPSG:3395');
        expect(JSON.stringify(park)).toBe(before);
        expect(out.features[0].properties).toBe(park.features[0].properties);
    });
});

describe('snapSourceToGrid', () => {
    it('snaps an inline geojson source, in its own units', () => {
        const out = snapSourceToGrid({ type: 'geojson', geojsonObject: park, outputTableName: 'parks', coordinateFormat: 'EPSG:3395' });
        expect(((out.geojsonObject as FeatureCollection).features[0].geometry as any).coordinates[0][0]).toEqual([-9754158.48, 5112622.88]);
        expect(out.outputTableName).toBe('parks');
    });

    it('passes any other source through untouched', () => {
        const osm = { type: 'osm', pbfFileUrl: 'x.osm.pbf' };
        expect(snapSourceToGrid(osm)).toBe(osm);
    });
});
