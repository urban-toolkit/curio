import { toRows } from "./rowSource";
export const shortenString = (str: string) => {
  if (str.length > 15) {
    return str.slice(0, 15) + "...";
  } else {
    return str;
  }
};

// list will contain all coordinates from all layers
export const get_camera = (coordinates: number[]) => {
  let minLat = undefined;
  let minLon = undefined;
  let maxLat = undefined;
  let maxLon = undefined;

  for (let i = 0; i < Math.trunc(coordinates.length / 3); i++) {
    if (minLat == undefined || coordinates[i * 3] < minLat) {
      minLat = coordinates[i * 3];
    }

    if (minLon == undefined || coordinates[i * 3 + 1] < minLon) {
      minLon = coordinates[i * 3 + 1];
    }

    if (maxLat == undefined || coordinates[i * 3] > maxLat) {
      maxLat = coordinates[i * 3];
    }

    if (maxLon == undefined || coordinates[i * 3 + 1] > maxLon) {
      maxLon = coordinates[i * 3 + 1];
    }
  }

  let center = [0, 0, 1];

  if (minLat != undefined && maxLat != undefined && minLon != undefined && maxLon != undefined)
    center = [(minLat + maxLat) / 2.0, (minLon + maxLon) / 2.0, 1];

  return {
    position: center,
    direction: {
      right: [0, 0, 3000],
      lookAt: [0, 0, 0],
      up: [0, 1, 0],
    },
  };
};

export const parseDataframe = (data: any) => {
  // The original of the five copies; see utils/rowSource. Eager, because
  // these rows become vega-lite `values`.
  return toRows({ data });
};

export type ParsedGeoDataframe = {
  values: any[];
  /** The active geometry column's pandas name, or null when there is none. */
  geometryName: string | null;
  /** The declared CRS urn, when the payload carried one. */
  crsName?: string;
};

/**
 * Flatten a geodataframe payload into rows, optionally keeping the geometry.
 *
 * The geometry is attached **under the active column's own pandas name** --
 * `geom` stays `geom` -- which is possible because geopandas excludes the
 * active column from each feature's `properties`, so it can never collide with
 * a real property of the same name.
 *
 * Each geometry is wrapped as `{type: "Feature", geometry}` rather than passed
 * bare. That is not decoration: vega-geo's GeoJSON transform pushes the raw
 * field value straight into `features[]` without wrapping it
 * (`vega-geo/src/GeoJSON.js`), and d3-geo's FeatureCollection stream then reads
 * `features[i].geometry` -- `undefined` for a bare geometry -- which yields
 * empty bounds and a `scale(NaN)`. The map renders as nothing at all, with no
 * error. Anyone who "simplifies" the wrapper away reintroduces a blank map.
 *
 * The wrapper shares the coordinate arrays by reference; nothing is copied.
 */
/**
 * The active geometry column of a geodataframe payload, or null.
 *
 * The sandbox wire shape always declares `geometry_name` (null when the frame
 * has no active geometry, see test_geodataframe_wire_shape.py). A payload
 * without the key never came off that wire: it is plain GeoJSON assembled in
 * the browser or by a backend route, as Spatial Join, a Data Pool layer or a
 * JS node emit. GeoJSON has exactly one geometry per feature, so that IS the
 * active column, and "geometry" is its conventional name (geopandas' default).
 * Before this fallback every geoshape over such a payload ended in
 * "No geometry to draw", example 10's map among them.
 *
 * The inference steps aside when a property already uses the name "geometry":
 * attaching the Feature there would overwrite a real column.
 */
export const activeGeometryName = (data: any): string | null => {
  if (data == null || typeof data !== "object") return null;
  if ("geometry_name" in data) return data.geometry_name ?? null;
  const features: any[] = Array.isArray(data.features) ? data.features : [];
  if (!features.some((f) => f?.geometry != null)) return null;
  if (features.some((f) => f?.properties && "geometry" in f.properties)) return null;
  return "geometry";
};

export const parseGeoDataframeWithGeometry = (
  data: any,
  withGeometry: boolean,
): ParsedGeoDataframe => {
  const features: any[] = Array.isArray(data?.features) ? data.features : [];
  const geometryName: string | null = activeGeometryName(data);
  const crsName: string | undefined = data?.crs?.properties?.name;

  const attachGeometry = withGeometry && geometryName != null;

  const values = features.map((feature: any) => {
    const row = { ...feature.properties };
    if (attachGeometry) {
      // A missing geometry stays null rather than becoming an empty Feature:
      // vega-lite emits an `isValid(datum[...])` filter ahead of the geojson
      // transform, which drops those rows cleanly.
      row[geometryName as string] =
        feature.geometry == null
          ? null
          : { type: "Feature", geometry: feature.geometry };
    }
    return row;
  });

  return { values, geometryName, crsName };
};

/** The long-standing shape: properties only, geometry discarded. */
export const parseGeoDataframe = (data: any) =>
  parseGeoDataframeWithGeometry(data, false).values;