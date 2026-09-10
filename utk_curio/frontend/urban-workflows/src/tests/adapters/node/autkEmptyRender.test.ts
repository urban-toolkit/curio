import { emptyRunRows } from "../../../adapters/node/autkGrammarBehavior";
import { partialRenderNote, renderOutcome } from "../../../utils/renderOutcome";

/**
 * dev/136, the Autark half of the owner's report.
 *
 * `autkGrammarBehavior` resolves `layerRefs` against the tables the data
 * section produced and DROPS the ones it cannot find, with a `console.warn` as
 * the only trace. When every ref is dropped, `grammar.run` renders a map with
 * no layers — a grey canvas — and the node emitted `success`. A data/compute
 * run whose every table is empty did the same: `describeAutkRun` had the
 * counts in its sentence and nothing read them.
 *
 * The decision itself is `renderOutcome`'s (tested in full beside it); these
 * pin the two Autark-specific readings that feed it.
 */

describe("emptyRunRows — the counts describeAutkRun already wrote", () => {
  it("totals the rows a load reports", () => {
    expect(emptyRunRows("Loaded 2 tables: a (12 rows), b (3 rows)")).toBe(15);
  });

  it("is 0 when every table came back empty", () => {
    expect(emptyRunRows("Loaded 3 tables: a (0 rows), b (0 rows), c (0 rows)")).toBe(0);
  });

  it("reads features as well as rows (a layer's own word)", () => {
    expect(emptyRunRows("Loaded 2 tables: roads (0 features), parks (4 features)")).toBe(4);
  });

  it("makes no claim when the summary names no counts", () => {
    // "Loaded nothing - the spec names no tables." and a render node's summary
    // carry no counts: undefined, so nothing is reported as empty.
    expect(emptyRunRows("Loaded nothing - the spec names no tables.")).toBeUndefined();
    expect(emptyRunRows("")).toBeUndefined();
    expect(emptyRunRows("Rendered the map")).toBeUndefined();
  });
});

describe("the map's own reading of what survived resolution", () => {
  const requested = ["population_density", "boundaries"];

  it("every layerRef dropped is an empty render naming the tables", () => {
    const outcome = renderOutcome({
      layersRequested: requested.length,
      layersDrawn: 0,
      requestedRefs: requested,
      availableRefs: ["table_osm_roads"],
    });
    expect(outcome.empty).toBe(true);
    expect(outcome.cause).toBe("no-layers");
    expect(outcome.message).toContain("population_density, boundaries");
    expect(outcome.message).toContain("table_osm_roads");
  });

  it("one surviving layer is not an empty render, and says what it lost", () => {
    const counts = {
      layersRequested: 2,
      layersDrawn: 1,
      requestedRefs: requested,
      availableRefs: ["population_density"],
    };
    expect(renderOutcome(counts).empty).toBe(false);
    expect(partialRenderNote(counts)).toContain("drew 1 of 2 layers");
  });

  it("a map that asked for nothing is not reported as empty", () => {
    // A compute- or data-only spec has no layerRefs to drop.
    expect(renderOutcome({ layersRequested: 0, layersDrawn: 0 }).empty).toBe(false);
  });
});
