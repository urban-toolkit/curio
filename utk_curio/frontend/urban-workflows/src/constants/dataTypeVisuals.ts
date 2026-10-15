/**
 * How a loader's data type and source are drawn: one table, read by the
 * Data Loading preview and its folded chip (plans/data-loading-expressive-preview-memo.md).
 *
 * The glyphs are the workshop deck's ("Data supported by Curio"), so the slides
 * and the app draw a type the same way. The colours are the Data Catalog's
 * format tokens (`--curio-format-<fmt>-*`), spelled out literally so the token
 * test sees every one of them. Only the type carries colour; a source is drawn
 * in the neutral text colour.
 */
import type { IconDefinition } from "@fortawesome/fontawesome-svg-core";
import {
  faBookOpen,
  faBoxArchive,
  faBus,
  faCode,
  faCube,
  faDrawPolygon,
  faFileCsv,
  faHardDrive,
  faMap,
  faPenToSquare,
  faPlug,
  faSatellite,
  faStreetView,
  faTable,
  faWind,
} from "@fortawesome/free-solid-svg-icons";
import type { LoaderDataType, LoaderSourceKind } from "../services/datasetCatalog/loaderProfile";

export interface DataTypeVisual {
  /** The short name on the preview and the chip ("GeoJSON", "Raster", "Data"). */
  label: string;
  /** The badge on the database; null draws the database alone. */
  glyph: IconDefinition | null;
  /** The database's colour. */
  fg: string;
  /** The tile behind the database. */
  bg: string;
  /** Text and badge on the tint, and the chip label's fill. */
  onTint: string;
}

const tokens = (fg: string, bg: string, onTint: string) => ({ fg, bg, onTint });

const GEOJSON = tokens("var(--curio-format-geojson-fg)", "var(--curio-format-geojson-bg)", "var(--curio-format-geojson-on-tint)");
const CSV = tokens("var(--curio-format-csv-fg)", "var(--curio-format-csv-bg)", "var(--curio-format-csv-on-tint)");
const GEOTIFF = tokens("var(--curio-format-geotiff-fg)", "var(--curio-format-geotiff-bg)", "var(--curio-format-geotiff-on-tint)");
const NEUTRAL = tokens("var(--curio-text-secondary)", "var(--curio-surface-muted)", "var(--curio-text-secondary)");

export const DATA_TYPE_VISUALS: Record<LoaderDataType, DataTypeVisual> = {
  geojson: { label: "GeoJSON", glyph: faDrawPolygon, ...GEOJSON },
  shp: {
    label: "SHP",
    glyph: faDrawPolygon,
    ...tokens("var(--curio-format-shp-fg)", "var(--curio-format-shp-bg)", "var(--curio-format-shp-on-tint)"),
  },
  gpkg: {
    label: "GeoPackage",
    glyph: faDrawPolygon,
    ...tokens("var(--curio-format-gpkg-fg)", "var(--curio-format-gpkg-bg)", "var(--curio-format-gpkg-on-tint)"),
  },
  csv: { label: "CSV", glyph: faFileCsv, ...CSV },
  parquet: {
    label: "Parquet",
    glyph: faFileCsv,
    ...tokens("var(--curio-format-parquet-fg)", "var(--curio-format-parquet-bg)", "var(--curio-format-parquet-on-tint)"),
  },
  geotiff: { label: "Raster", glyph: faSatellite, ...GEOTIFF },
  netcdf: {
    label: "NetCDF",
    glyph: faWind,
    ...tokens("var(--curio-format-netcdf-fg)", "var(--curio-format-netcdf-bg)", "var(--curio-format-netcdf-on-tint)"),
  },
  json: {
    label: "JSON",
    glyph: faCode,
    ...tokens("var(--curio-format-json-fg)", "var(--curio-format-json-bg)", "var(--curio-format-json-on-tint)"),
  },
  osm: {
    label: "OSM",
    glyph: faMap,
    ...tokens("var(--curio-format-osm-fg)", "var(--curio-format-osm-bg)", "var(--curio-format-osm-on-tint)"),
  },
  collection: {
    label: "Images",
    glyph: faStreetView,
    ...tokens("var(--curio-format-collection-fg)", "var(--curio-format-collection-bg)", "var(--curio-format-collection-on-tint)"),
  },
  gtfs: {
    label: "GTFS",
    glyph: faBus,
    ...tokens("var(--curio-format-gtfs-fg)", "var(--curio-format-gtfs-bg)", "var(--curio-format-gtfs-on-tint)"),
  },
  bundle: {
    label: "Bundle",
    glyph: faBoxArchive,
    ...tokens("var(--curio-format-bundle-fg)", "var(--curio-format-bundle-bg)", "var(--curio-format-bundle-on-tint)"),
  },
  onnx: { label: "ONNX", glyph: faCube, ...NEUTRAL },
  dataframe: { label: "Table", glyph: faTable, ...CSV },
  geodataframe: { label: "Geo table", glyph: faDrawPolygon, ...GEOJSON },
  raster: { label: "Raster", glyph: faSatellite, ...GEOTIFF },
  unknown: { label: "Data", glyph: null, ...NEUTRAL },
};

export interface SourceKindVisual {
  label: string;
  glyph: IconDefinition;
}

export const SOURCE_KIND_VISUALS: Record<LoaderSourceKind, SourceKindVisual> = {
  catalog: { label: "Data Catalog", glyph: faBookOpen },
  disk: { label: "File", glyph: faHardDrive },
  api: { label: "API", glyph: faPlug },
  inline: { label: "Defined in code", glyph: faPenToSquare },
  unknown: { label: "Custom loader", glyph: faCode },
};

export function dataTypeVisual(type: LoaderDataType | null | undefined): DataTypeVisual {
  return (type && DATA_TYPE_VISUALS[type]) || DATA_TYPE_VISUALS.unknown;
}
