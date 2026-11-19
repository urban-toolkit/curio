/**
 * Inputs that hold a raster beside their tables, as `/get-preview` sends them,
 * after example 34 (park access as an Autark heatmap): its data node loads
 * the parks and the roads of the tip of Lower Manhattan, then builds the
 * heatmap `park_access`, whose one band counts the parks within reach of each
 * cell (`count_tip_parks`). Cut to a grid of 3 by 2 cells and a feature per
 * table.
 *
 * - The data node's run on the server hands on its tables as a list of
 *   `{name, type, geojson}` records, then the heatmap in its envelope
 *   (`rasterEnvelope` in adapters/node/autkDataCompile), each item in the
 *   `dict` envelope `/get` writes it in.
 * - Its run in the browser hands on one `outputs` envelope of `layerName`
 *   layers (`layersToPoolWrapper`), the heatmap's envelope last, kept by the
 *   sandbox as the dict it is.
 * - A Python node that returns a dict of frames with a raster in it, and one
 *   that returns a rasterio dataset on its own: `/get` sends a raster's file
 *   and what the sandbox read of it (`meta`: its size, its bands' labels and
 *   its CRS).
 */

const point = (x: number, y: number) => ({ type: "Point", coordinates: [x, y] });
const line = (x: number, y: number) => ({ type: "LineString", coordinates: [[x, y], [x + 50, y]] });

const collection = (geometry: any, properties: Record<string, unknown>) => ({
  type: "FeatureCollection",
  crs: { type: "name", properties: { name: "urn:ogc:def:crs:EPSG::3395" } },
  features: [{ type: "Feature", geometry, properties }],
});

const PARKS = collection(point(-8239700, 4968900), { osm_id: 1201, leisure: "park" });
const ROADS = collection(line(-8239750, 4968850), { osm_id: 3301, highway: "residential" });

/** The heatmap's envelope: its grid, its one band labelled as autk-db labels a
 * `count` over `tip_parks`, and the band's 6 cells, base64 of little-endian
 * float32 (0, 1, 4, 2, 7, 12). */
export const PARK_ACCESS = {
  dataType: "raster",
  layerName: "park_access",
  data: {
    type: "FeatureCollection",
    bbox: [-8239800, 4968800, -8239500, 4969000],
    grid: { crs: "EPSG:3395", width: 3, height: 2, originX: -8239800, originY: 4969000, resX: 100, resY: -100 },
    features: [
      {
        type: "Feature",
        geometry: null,
        properties: {
          rasterResX: 3,
          rasterResY: 2,
          bands: [{ id: "band_1", label: "count_tip_parks" }],
          band_1: { float32le: "AAAAAAAAgD8AAIBAAAAAQAAA4EAAAEBB" },
        },
      },
    ],
  },
};

/** What the data node's run on the server hands on, as `/get-preview` sends it. */
export const SERVER_LAYERS = {
  dataType: "list",
  data: [
    { dataType: "dict", data: { name: "tip_parks", type: "parks", geojson: PARKS } },
    { dataType: "dict", data: { name: "tip_roads", type: "roads", geojson: ROADS } },
    { dataType: "dict", data: PARK_ACCESS },
  ],
};

/** The map node's input from that run. */
export const SERVER_LAYERS_REF = { path: "park-access-layers", dataType: "list" };

/** What the data node's run in the browser hands on, as `/get-preview` sends it. */
export const BROWSER_LAYERS = {
  dataType: "dict",
  data: {
    dataType: "outputs",
    data: [
      { dataType: "geodataframe", data: PARKS, layerName: "tip_parks", layerType: "parks" },
      { dataType: "geodataframe", data: ROADS, layerName: "tip_roads", layerType: "roads" },
      PARK_ACCESS,
    ],
  },
};

/** The map node's input from that run. */
export const BROWSER_LAYERS_REF = { path: "park-access-wrapper", dataType: "dict" };

/** A Python node's elevation raster, as `/get` describes it beside its file. */
export const ELEVATION = {
  dataType: "raster",
  data: "/srv/curio/.curio/data/artifacts/elevation.tif",
  meta: {
    width: 40,
    height: 30,
    count: 2,
    crs: "EPSG:3395",
    crsWkt: null,
    transform: [10, 0, -8240000, 0, -10, 4969300],
    nodata: null,
    dtype: "float32",
    bands: ["elevation_m", null],
  },
};

/** A Python node's `return {"tip_parks": parks, "tip_roads": roads, "elevation": dem}`. */
export const PYTHON_DICT = {
  dataType: "dict",
  data: {
    tip_parks: { dataType: "geodataframe", data: PARKS, schema: { osm_id: "int64", leisure: "str", geometry: "geometry" } },
    tip_roads: { dataType: "geodataframe", data: ROADS, schema: { osm_id: "int64", highway: "str", geometry: "geometry" } },
    elevation: ELEVATION,
  },
};

/** The next node's input from it. */
export const PYTHON_DICT_REF = { path: "python-dict", dataType: "dict" };

/** A Python node's `return {"tip_parks": parks, "elevation": dem}`: one table and a raster. */
export const PYTHON_PAIR = {
  dataType: "dict",
  data: {
    tip_parks: PYTHON_DICT.data.tip_parks,
    elevation: ELEVATION,
  },
};

/** A Python node's `return parks, dem`: a tuple of a table and a raster. */
export const PYTHON_TUPLE = {
  dataType: "outputs",
  data: [{ dataType: "dataframe", data: { osm_id: [1201], leisure: ["park"] }, schema: { osm_id: "int64", leisure: "str" } }, ELEVATION],
};

/** A Python node's `return {"day": day, "night": night}`: rasters alone. */
export const PYTHON_RASTERS = {
  dataType: "dict",
  data: {
    day: { ...ELEVATION, data: "/srv/curio/.curio/data/artifacts/day.tif" },
    night: { ...ELEVATION, data: "/srv/curio/.curio/data/artifacts/night.tif" },
  },
};

/** A Python node's raster on its own, and the next node's input from it. */
export const PYTHON_RASTER_REF = { path: "elevation-artifact", dataType: "raster" };

/** What each input reads as, by its path. */
export const RASTER_READS: Record<string, unknown> = {
  [SERVER_LAYERS_REF.path]: SERVER_LAYERS,
  [BROWSER_LAYERS_REF.path]: BROWSER_LAYERS,
  [PYTHON_DICT_REF.path]: PYTHON_DICT,
  "python-pair": PYTHON_PAIR,
  "python-tuple": PYTHON_TUPLE,
  "python-rasters": PYTHON_RASTERS,
  [PYTHON_RASTER_REF.path]: ELEVATION,
};
