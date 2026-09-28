/**
 * Snap a grammar source's coordinates to a 1 cm grid before autk-db loads it.
 *
 * autk-db clips every layer it loads after the first to that first polygon
 * layer, the workspace's crop layer. The layers a grammar node is handed were
 * already clipped once, where they were made (autk-db's `loadOsm` clips its
 * layers to the surface), so a park's edge lies on the surface's boundary to
 * within floating-point noise, and GEOS refuses the second intersection with
 * "TopologyException: found non-noded intersection". The node then fails.
 * Rounding to a 1 cm grid, in the layer's own units, takes that noise out:
 * every layer of every example extract then loads, with no feature lost.
 */
import type { FeatureCollection, Geometry } from 'geojson';

/** 1 cm, in meters (EPSG:3395, the workspace CRS). */
export const GRID_METERS = 0.01;
/** About 1 cm at the equator, in degrees (EPSG:4326). */
export const GRID_DEGREES = 1e-7;

function roundCoords(coords: any, scale: number): any {
    if (typeof coords === 'number') return Math.round(coords * scale) / scale;
    return Array.isArray(coords) ? coords.map((c) => roundCoords(c, scale)) : coords;
}

function snapGeometry(geometry: Geometry | null, scale: number): Geometry | null {
    if (!geometry) return geometry;
    if (geometry.type === 'GeometryCollection') {
        return { ...geometry, geometries: geometry.geometries.map((g) => snapGeometry(g, scale) as Geometry) };
    }
    return { ...geometry, coordinates: roundCoords((geometry as any).coordinates, scale) } as Geometry;
}

/** A copy of *fc* on the grid for *coordinateFormat*; the input is not changed. */
export function snapCollectionToGrid(fc: FeatureCollection, coordinateFormat: string): FeatureCollection {
    const grid = /(^|:)4326$/.test(String(coordinateFormat)) ? GRID_DEGREES : GRID_METERS;
    const scale = Math.round(1 / grid);
    return {
        ...fc,
        features: fc.features.map((f) => ({ ...f, geometry: snapGeometry(f.geometry, scale) as Geometry })),
    };
}

/** A grammar data source with its inline GeoJSON on the grid; any other source unchanged. */
export function snapSourceToGrid<T extends { type?: string; geojsonObject?: unknown; coordinateFormat?: string }>(source: T): T {
    const fc = source?.geojsonObject as FeatureCollection | undefined;
    if (source?.type !== 'geojson' || !fc || !Array.isArray(fc.features)) return source;
    return { ...source, geojsonObject: snapCollectionToGrid(fc, source.coordinateFormat ?? 'EPSG:4326') };
}
