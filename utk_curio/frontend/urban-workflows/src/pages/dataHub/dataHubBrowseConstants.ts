import type { DatasetFormat, DatasetOrigin } from "../../services/datasetCatalog";

/** Browse rail: two provenance buckets (API maps ``imported`` filter to hub/imported/source_node). */
export const ORIGIN_FILTERS: DatasetOrigin[] = ["computed", "imported"];

export const FORMAT_FILTERS: DatasetFormat[] = [
  "geojson",
  "csv",
  "json",
  "parquet",
  "geotiff",
  "shp",
];

export const QUICK_FORMAT_FILTERS: DatasetFormat[] = ["geojson", "csv", "json"];
