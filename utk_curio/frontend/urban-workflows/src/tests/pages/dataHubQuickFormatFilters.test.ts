import { quickFormatFilters } from "../../pages/dataHub/dataHubBrowseConstants";

/**
 * #232: the Data Catalog rendered its format filters twice from two different
 * sources - the sidebar rail off the live ``facets.format`` counts, and the chip
 * row off a hardcoded ``["geojson", "csv", "json"]``. So the chips advertised
 * JSON with zero datasets while hiding Parquet and GeoTIFF, which the rail beside
 * them was counting.
 */
describe("quickFormatFilters", () => {
  // The counts the shipped `datasets/` folder actually produces, so this case is
  // the reported bug stated as data: JSON and SHP out, Parquet and GeoTIFF in.
  const SHIPPED = {
    geojson: 3,
    csv: 4,
    json: 0,
    parquet: 3,
    geotiff: 1,
    shp: 0,
  } as const;

  it("offers every populated format and no empty one", () => {
    expect(quickFormatFilters(SHIPPED)).toEqual([
      "geojson",
      "csv",
      "parquet",
      "geotiff",
    ]);
  });

  it("keeps the rail's canonical order rather than ranking by count", () => {
    // csv has the highest count and geojson still leads: ordering by count would
    // reshuffle the chips on every search keystroke, because the facets recompute
    // with the query.
    const order = quickFormatFilters(SHIPPED);
    expect(order.indexOf("geojson")).toBeLessThan(order.indexOf("csv"));
    expect(order.indexOf("parquet")).toBeLessThan(order.indexOf("geotiff"));
  });

  it("keeps the active format even when its count drops to zero", () => {
    // A search that excludes every GeoJSON row must not remove the very chip the
    // user is filtering by.
    expect(quickFormatFilters({ geojson: 0, csv: 2 }, "geojson")).toContain("geojson");
    expect(quickFormatFilters({ geojson: 0, csv: 2 }, "")).not.toContain("geojson");
  });

  it("returns nothing for an all-zero catalog instead of throwing", () => {
    expect(quickFormatFilters({ geojson: 0, csv: 0, json: 0 })).toEqual([]);
    expect(quickFormatFilters({})).toEqual([]);
  });

  it("tolerates a payload missing format keys entirely", () => {
    // An older/partial facets object must not produce NaN comparisons.
    expect(quickFormatFilters({ parquet: 2 })).toEqual(["parquet"]);
  });

  it("never chips a format the rail cannot filter on", () => {
    // `bundle` and `osm` are real facet keys with real counts, but FORMAT_FILTERS
    // has no row for them, so a chip would filter to a rail state that does not
    // exist. (That gap is its own issue; this pins that #232 did not widen it.)
    expect(quickFormatFilters({ bundle: 5, osm: 7 })).toEqual([]);
  });
});
