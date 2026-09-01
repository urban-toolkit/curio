import {
  catalogFetchKey,
  toStableCatalogQuery,
} from "../../services/datasetCatalog/datasetCatalogHooks";

/**
 * The Data Catalog's search is a SERVER query, so #231 had to be fixed on both
 * sides: `listing.py` strips the needle, and `toStableCatalogQuery` strips the
 * value that becomes both the wire `q` and the fetch-cache key. Without the
 * client half a padded query still minted a distinct key, so the cache missed
 * and a redundant request went out for a result set the server now returns
 * identically.
 *
 * Nothing asserted on the `search` leg of that key before.
 */
describe("toStableCatalogQuery / catalogFetchKey search normalization", () => {
  it("collapses a whitespace-only search to undefined, like the empty string", () => {
    expect(toStableCatalogQuery({ search: "   " }).search).toBeUndefined();
    expect(toStableCatalogQuery({ search: "" }).search).toBeUndefined();
    expect(toStableCatalogQuery({}).search).toBeUndefined();
  });

  it("strips surrounding whitespace but keeps the query itself", () => {
    expect(toStableCatalogQuery({ search: "  roads  " }).search).toBe("roads");
    // Internal whitespace is part of the needle and must survive.
    expect(toStableCatalogQuery({ search: " community areas " }).search).toBe(
      "community areas",
    );
  });

  it("gives a padded query the same cache key as the trimmed one", () => {
    const trimmed = catalogFetchKey(toStableCatalogQuery({ search: "roads" }));
    expect(catalogFetchKey(toStableCatalogQuery({ search: "roads " }))).toBe(trimmed);
    expect(catalogFetchKey(toStableCatalogQuery({ search: " roads" }))).toBe(trimmed);
    expect(catalogFetchKey(toStableCatalogQuery({ search: "  roads  " }))).toBe(trimmed);
  });

  it("still distinguishes genuinely different queries", () => {
    expect(catalogFetchKey(toStableCatalogQuery({ search: "roads" }))).not.toBe(
      catalogFetchKey(toStableCatalogQuery({ search: "rivers" })),
    );
  });
});
