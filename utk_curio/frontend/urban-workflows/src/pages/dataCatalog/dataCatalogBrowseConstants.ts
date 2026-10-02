import type { DatasetFormat, DatasetOrigin } from "../../services/datasetCatalog";

/** Browse rail: two provenance buckets (API maps ``imported`` filter to hub/imported/source_node). */
export const ORIGIN_FILTERS: DatasetOrigin[] = ["computed", "imported"];

/**
 * Every ``DatasetFormat``, in the order the rail shows them.
 *
 * It used to list six of the eight (#348). ``bundle`` (a computed multi-output
 * node's result) and ``osm`` (a synthetic OSM PBF layer group) were left out
 * even though the backend counts both - ``catalog_facets`` seeds them
 * explicitly - so saving a multi-output node or importing a PBF produced
 * datasets that inflated the rail's "All formats" total while having no row of
 * their own and no chip: not filterable, and not visible as a category at all.
 *
 * Both already have a label (``DATASET_FORMAT_LABEL``) and dot/chip/card colour
 * tokens, so nothing else was needed to show them.
 */
export const FORMAT_FILTERS: DatasetFormat[] = [
  "geojson",
  "csv",
  "json",
  "parquet",
  "geotiff",
  "shp",
  "bundle",
  "osm",
  "gpkg",
  "collection",
];

/**
 * The rail's format rows: the formats that actually hold datasets, in the
 * rail's own order.
 *
 * Until the chip row above the cards was removed, it showed these too. It was a
 * hardcoded ``["geojson", "csv", "json"]`` (#232), which advertised JSON with
 * zero datasets while hiding the Parquet and GeoTIFF rows the rail beside it was
 * busy counting. Deriving the rows from ``facets.format`` means a format added
 * to ``FORMAT_FILTERS`` reaches the rail as soon as it holds a dataset.
 *
 * Canonical order rather than count-descending: the facets recompute on every
 * search keystroke, so ranking by count would reshuffle the rows under the
 * user's cursor.
 *
 * ``active`` is kept even at zero. The facets narrow with the search box
 * (``listing.py`` computes them after ``q`` and before the format filter), so a
 * search excluding every dataset of the selected format would otherwise make the
 * very row you are filtering by vanish.
 */
export function quickFormatFilters(
  counts: Partial<Record<DatasetFormat, number>>,
  active: DatasetFormat | "" = "",
): DatasetFormat[] {
  return FORMAT_FILTERS.filter((fmt) => (counts[fmt] ?? 0) > 0 || fmt === active);
}
