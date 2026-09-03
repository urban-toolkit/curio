import type { PackagePayload } from "../../api/packagesApi";
import { matchesSearch } from "../../components/packages/publishing/packageUtils";

/**
 * `matchesSearch` is the Node Catalog's search predicate and the convention every
 * other search surface in the app is written to mirror -- `agentListUtils`' own
 * docstring says it "Mirrors packageUtils.matchesSearch". It had no direct test,
 * so the convention it defines was unpinned while #231 was fixed against it.
 */
function pkg(over: Partial<PackagePayload> = {}): PackagePayload {
  return {
    packageId: "curio.weather",
    major: 1,
    version: "1.0.0",
    name: "Weather Analysis",
    publisher: "urbanlab",
    description: "Temperature and precipitation summaries for a city boundary.",
    license: null,
    permissions: [],
    dependencies: {} as PackagePayload["dependencies"],
    templates: [],
    dirName: "curio.weather@1",
    lineage: null,
    familyKey: "curio.weather@1",
    channel: "stable",
    ...over,
  } as PackagePayload;
}

describe("matchesSearch", () => {
  it("passes every package for an empty or whitespace-only query", () => {
    expect(matchesSearch(pkg(), "")).toBe(true);
    expect(matchesSearch(pkg(), "   ")).toBe(true);
  });

  it("matches each promised field, case-insensitively", () => {
    expect(matchesSearch(pkg(), "WEATHER ANALYSIS")).toBe(true); // name
    expect(matchesSearch(pkg(), "UrbanLab")).toBe(true); // publisher
    expect(matchesSearch(pkg(), "precipitation")).toBe(true); // description
    expect(matchesSearch(pkg(), "curio.weather")).toBe(true); // packageId
  });

  it("rejects a package matching no field", () => {
    expect(matchesSearch(pkg(), "spatial join")).toBe(false);
  });

  // The behaviour #231 aligned the Projects list to: surrounding whitespace is not
  // part of the needle. The reporter noted this surface already did it right.
  it("trims the query before matching", () => {
    expect(matchesSearch(pkg(), "  Weather Analysis  ")).toBe(true);
    expect(matchesSearch(pkg(), "\tprecipitation\n")).toBe(true);
  });
});
