import type { DatasetFormat, DatasetOrigin } from "../../services/datasetCatalog";

/** Browse rail: two provenance buckets (API maps ``imported`` filter to hub/imported/source_node). */
export const ORIGIN_FILTERS: DatasetOrigin[] = ["computed", "imported"];

/**
 * Every ``DatasetFormat``, in the order the rail and the chip row show them.
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
];

/**
 * Quick-filter chips above the dataset cards: the rail's format rows that
 * actually hold datasets, in the rail's own order.
 *
 * Was a hardcoded ``["geojson", "csv", "json"]`` (#232). That list advertised
 * JSON with zero datasets while hiding the Parquet and GeoTIFF rows the rail
 * immediately to its left was busy counting - two filter surfaces on one page,
 * disagreeing about what you could filter by. Deriving both from the same
 * ``facets.format`` is what keeps them in step, and means a format added to
 * ``FORMAT_FILTERS`` reaches both at once.
 *
 * Canonical order rather than count-descending: the facets recompute on every
 * search keystroke, so ranking by count would reshuffle the chips under the
 * user's cursor and break the visual correspondence with the rail rows beside
 * them.
 *
 * ``active`` is kept even at zero. The facets narrow with the search box
 * (``listing.py`` computes them after ``q`` and before the format filter), so a
 * search excluding every dataset of the selected format would otherwise make the
 * very chip you are filtering by vanish.
 *
 * No numeric cap: the domain is closed at these formats and ``.filterBar``
 * wraps, so the row cannot overflow.
 */
export function quickFormatFilters(
  counts: Partial<Record<DatasetFormat, number>>,
  active: DatasetFormat | "" = "",
): DatasetFormat[] {
  return FORMAT_FILTERS.filter((fmt) => (counts[fmt] ?? 0) > 0 || fmt === active);
}
