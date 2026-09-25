import { countedItem, describeAutkRun } from "../../../adapters/node/autkGrammarBehavior";
import { partialRenderNote, renderOutcome } from "../../../utils/renderOutcome";

/**
 * dev/136, the Autark half of the owner's report.
 *
 * `autkGrammarBehavior` resolves `layerRefs` against the tables the data
 * section produced and DROPS the ones it cannot find, with a `console.warn` as
 * the only trace. When every ref is dropped, `grammar.run` renders a map with
 * no layers (a grey canvas) and the node emitted `success`. A data/compute run
 * whose every table is empty did the same.
 *
 * The decision itself is `renderOutcome`'s (tested in full beside it); these
 * pin the Autark-specific readings that feed it. The counts ride as data, not
 * as text parsed back out of the summary line.
 */

describe("the run summary prints only the counts it has", () => {
  it("names the count when it is known", () => {
    expect(countedItem("roads", 12, "features")).toBe("roads (12 features)");
    expect(countedItem("roads", 0, "rows")).toBe("roads (0 rows)");
  });

  it("an unknown count is the bare name, never '(undefined features)'", () => {
    expect(countedItem("roads", undefined, "features")).toBe("roads");
    const line = describeAutkRun("Loaded", "table", [
      countedItem("a", undefined, "features"),
      countedItem("b", 3, "features"),
    ]);
    expect(line).toBe("Loaded 2 tables: a, b (3 features)");
    expect(line).not.toContain("undefined");
  });
});

describe("a data or compute run's own counts", () => {
  it("a data node whose sources loaded zero rows is the document's fault", () => {
    const outcome = renderOutcome({ sourceRows: 0 });
    expect(outcome.empty).toBe(true);
    expect(outcome.cause).toBe("empty-source");
  });

  it("a compute node fed zero rows is the upstream's fault", () => {
    expect(renderOutcome({ rowsIn: 0, drawn: 0 }).cause).toBe("no-input-rows");
  });

  it("uncounted sources, the default sandbox path, give no verdict", () => {
    expect(renderOutcome({ sourceRows: undefined }).empty).toBe(false);
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

  it("a ref to an EMPTY table resolved: its source is blamed, not the ref", () => {
    // The table exists with zero rows, so it is not "data the dataflow does
    // not produce"; the counts are kept from before empty sources are dropped.
    // Nothing reached the grammar, but the ref resolved.
    const outcome = renderOutcome({
      layersRequested: 1,
      layersResolved: 1,
      layersDrawn: 0,
      requestedRefs: ["parks"],
      availableRefs: ["parks"],
      rowsIn: 0,
      sourceRows: 0,
    });
    expect(outcome.cause).toBe("empty-source");
    // The same empty table arriving from UPSTREAM is the upstream's fault.
    expect(renderOutcome({ layersRequested: 1, layersResolved: 1, layersDrawn: 0, rowsIn: 0 }).cause)
      .toBe("no-input-rows");
  });

  it("a layer dropped for being empty is still noted on a render that drew", () => {
    // roads drew; parks resolved but held no rows, so it never reached the
    // grammar. Rule 1 does not fire, and the note names the empty table.
    const counts = {
      layersRequested: 2,
      layersResolved: 2,
      layersDrawn: 1,
      requestedRefs: ["roads", "parks"],
      availableRefs: ["roads", "parks"],
      emptyRefs: ["parks"],
      rowsIn: 12,
    };
    expect(renderOutcome(counts).empty).toBe(false);
    const note = partialRenderNote(counts);
    expect(note).toContain("drew 1 of 2 layers");
    expect(note).toContain("parks has no rows");
    expect(note).not.toContain("does not produce");
  });

  it("a map that asked for nothing is not reported as empty", () => {
    // A compute- or data-only spec has no layerRefs to drop.
    expect(renderOutcome({ layersRequested: 0, layersDrawn: 0 }).empty).toBe(false);
  });
});
