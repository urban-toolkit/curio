import {
  emptyRenderKind,
  partialRenderNote,
  renderOutcome,
} from "../../utils/renderOutcome";
import {
  DOCUMENT_AT_FAULT,
  EMPTY_RENDER_KIND,
  RENDER_CAUSES,
} from "../../generated/renderCauses";

/**
 * dev/136: the order of the rules IS the attribution, so the tests are mostly
 * about which cause wins — the fix for an empty plot depends entirely on what
 * emptied it.
 */

describe("renderOutcome", () => {
  it("blames the document when every layer it asks for was dropped", () => {
    const outcome = renderOutcome({
      rowsIn: 120,
      drawn: 0,
      layersRequested: 2,
      layersDrawn: 0,
      requestedRefs: ["population_density", "boundaries"],
      availableRefs: ["table_osm"],
    });
    expect(outcome.empty).toBe(true);
    expect(outcome.cause).toBe("no-layers");
    expect(outcome.message).toContain("population_density, boundaries");
    expect(outcome.message).toContain("available: table_osm");
  });

  it("blames the UPSTREAM when nothing arrived", () => {
    const outcome = renderOutcome({ rowsIn: 0, drawn: 0 });
    expect(outcome.cause).toBe("no-input-rows");
    expect(outcome.message).toContain("0 rows arrived");
    // dev/133's rule, said out loud: this document is not at fault.
    expect(outcome.message).toContain("not at fault");
  });

  it("blames the document when its OWN sources loaded zero rows", () => {
    const outcome = renderOutcome({ sourceRows: 0 });
    expect(outcome.empty).toBe(true);
    expect(outcome.cause).toBe("empty-source");
    expect(outcome.message).toContain("returned 0 rows");
    expect(outcome.message).not.toContain("not at fault");
  });

  it("an empty source outranks an empty input: the document names the source", () => {
    expect(renderOutcome({ sourceRows: 0, rowsIn: 0, drawn: 0 }).cause)
      .toBe("empty-source");
    // But every layer dangling is still the first thing to fix.
    expect(renderOutcome({
      sourceRows: 0, rowsIn: 0, layersRequested: 1, layersDrawn: 0,
    }).cause).toBe("no-layers");
  });

  it("an empty source is not an empty render when other rows arrived", () => {
    // Own sources came back empty, but the upstream fed the render rows.
    expect(renderOutcome({ sourceRows: 0, rowsIn: 5 }).empty).toBe(false);
    expect(renderOutcome({ sourceRows: 0, rowsIn: 5, drawn: 0 }).cause)
      .toBe("nothing-drawn");
  });

  it("some source rows with none arriving is the upstream's fault", () => {
    expect(renderOutcome({ sourceRows: 4, rowsIn: 0 }).cause).toBe("no-input-rows");
  });

  it("reports an all-null encoded field, whatever the scene graph drew", () => {
    // dev/137, the owner's `7a27b702`: the join left every `population` value
    // null, so the chart either drops those rows or draws zero-extent bars —
    // both are an empty picture, and the DATA is what says so.
    const outcome = renderOutcome({
      rowsIn: 2, usableRows: 0, usableFields: ["population"], drawn: 2,
    });
    expect(outcome.empty).toBe(true);
    expect(outcome.cause).toBe("nothing-drawn");
    expect(outcome.message).toContain("2 rows arrived");
    expect(outcome.message).toContain("every value of population is null");
    // The join that emptied it is upstream, and the message says so.
    expect(outcome.message).toContain("upstream node that produces those columns");
  });

  it("some usable values is not empty, even with few of them", () => {
    expect(renderOutcome({ rowsIn: 10, usableRows: 1, usableFields: ["x"], drawn: 1 }).empty)
      .toBe(false);
  });

  it("an uncounted usable set falls through to the mark count", () => {
    expect(renderOutcome({ rowsIn: 3, drawn: 0 }).cause).toBe("nothing-drawn");
    expect(renderOutcome({ rowsIn: 3, usableRows: undefined, drawn: 3 }).empty).toBe(false);
  });

  it("blames the document when rows arrived and no mark was drawn", () => {
    const outcome = renderOutcome({ rowsIn: 3, drawn: 0 });
    expect(outcome.cause).toBe("nothing-drawn");
    expect(outcome.message).toContain("3 rows arrived");
    expect(outcome.message).toContain("all null");
  });

  it("a known reason replaces the generic one for an empty picture", () => {
    const outcome = renderOutcome({ rowsIn: 3, drawn: 0, explanation: "no geometry column" });
    expect(outcome.cause).toBe("nothing-drawn");
    expect(outcome.message).toBe("rendered nothing: no geometry column");
    expect(
      renderOutcome({ rowsIn: 3, usableRows: 0, usableFields: ["v"], explanation: "why" }).message,
    ).toBe("rendered nothing: why");
  });

  it("a known reason never overrides who is at fault", () => {
    const outcome = renderOutcome({ rowsIn: 0, drawn: 0, explanation: "no geometry column" });
    expect(outcome.cause).toBe("no-input-rows");
    expect(outcome.message).toContain("0 rows arrived");
  });

  it("says one row in the singular", () => {
    expect(renderOutcome({ rowsIn: 1, drawn: 0 }).message).toContain("1 row arrived");
  });

  it("a render that drew something is not empty", () => {
    expect(renderOutcome({ rowsIn: 3, drawn: 3 })).toEqual({
      empty: false, cause: null, message: "",
    });
    expect(renderOutcome({ rowsIn: 0, drawn: 0, layersRequested: 2, layersDrawn: 2 }).cause)
      .toBe("no-input-rows");   // no layers dropped, but nothing arrived
  });

  it("a PARTIAL layer drop is not empty — something was drawn", () => {
    const outcome = renderOutcome({
      rowsIn: 10, drawn: 10, layersRequested: 3, layersDrawn: 1,
    });
    expect(outcome.empty).toBe(false);
  });

  it("a resolved ref is not a missing layer, even when nothing was drawn", () => {
    // Rule 1 reads the resolution count; the refs to empty tables resolved.
    expect(renderOutcome({ layersRequested: 1, layersResolved: 1, layersDrawn: 0 }).empty)
      .toBe(false);
    expect(renderOutcome({ layersRequested: 1, layersResolved: 0, layersDrawn: 0 }).cause)
      .toBe("no-layers");
  });

  it("makes no claim when it cannot count", () => {
    expect(renderOutcome({}).empty).toBe(false);
    expect(renderOutcome({ drawn: 0 }).empty).toBe(false);          // rows unknown
    expect(renderOutcome({ rowsIn: 5 }).empty).toBe(false);         // marks unknown
    expect(renderOutcome({ layersRequested: 2 }).empty).toBe(false); // drawn unknown
    expect(renderOutcome({ sourceRows: undefined }).empty).toBe(false); // sources unknown
    expect(renderOutcome({ rowsIn: undefined, sourceRows: undefined, drawn: undefined }))
      .toEqual({ empty: false, cause: null, message: "" });
  });

  it("every cause it reports is in the generated vocabulary", () => {
    const reported = [
      renderOutcome({ layersRequested: 1, layersDrawn: 0 }).cause,
      renderOutcome({ sourceRows: 0 }).cause,
      renderOutcome({ rowsIn: 0 }).cause,
      renderOutcome({ rowsIn: 1, drawn: 0 }).cause,
    ];
    expect([...reported].sort()).toEqual([...RENDER_CAUSES].sort());
    // Only an empty INPUT spares the document; the backend reads the same table.
    expect(DOCUMENT_AT_FAULT["no-input-rows"]).toBe(false);
    expect(DOCUMENT_AT_FAULT["empty-source"]).toBe(true);
  });

  it("bounds every message", () => {
    const outcome = renderOutcome({
      layersRequested: 1,
      layersDrawn: 0,
      requestedRefs: Array.from({ length: 40 }, (_, i) => `ref_${i}_${"x".repeat(40)}`),
      availableRefs: Array.from({ length: 40 }, (_, i) => `avail_${i}`),
    });
    expect(outcome.message.length).toBeLessThanOrEqual(400);
    expect(outcome.message.endsWith("…")).toBe(true);   // clipped, not dumped
  });

  it("counts the names it does not show rather than dumping them", () => {
    const outcome = renderOutcome({
      layersRequested: 1,
      layersDrawn: 0,
      requestedRefs: ["a", "b", "c", "d", "e", "f", "g", "h"],
      availableRefs: ["z"],
    });
    expect(outcome.message).toContain("a, b, c, d, e, f, … 2 more");
  });
});

describe("partialRenderNote", () => {
  it("names what was dropped on a render that still drew", () => {
    const note = partialRenderNote({
      layersRequested: 3, layersDrawn: 1,
      requestedRefs: ["a", "b", "c"], availableRefs: ["a"],
    });
    expect(note).toContain("drew 1 of 3 layers");
    expect(note).toContain("available: a");
  });

  it("names empty tables apart from refs to data the dataflow does not produce", () => {
    const note = partialRenderNote({
      layersRequested: 3, layersDrawn: 1,
      requestedRefs: ["a", "b", "c"], availableRefs: ["a", "b"],
      emptyRefs: ["b"],
    });
    expect(note).toContain("drew 1 of 3 layers");
    expect(note).toContain("b has no rows");
    expect(note).toContain("the others name data the dataflow does not produce");
  });

  it("says nothing when nothing was dropped, or when nothing was drawn", () => {
    expect(partialRenderNote({ layersRequested: 2, layersDrawn: 2 })).toBe("");
    expect(partialRenderNote({ layersRequested: 2, layersDrawn: 0 })).toBe("");
    expect(partialRenderNote({})).toBe("");
  });
});

describe("emptyRenderKind", () => {
  it("stamps the generated prefix and the cause", () => {
    expect(emptyRenderKind("empty-source")).toBe(`${EMPTY_RENDER_KIND}:empty-source`);
    expect(emptyRenderKind("no-input-rows")).toBe("empty-render:no-input-rows");
  });

  it("a missing cause leaves the bare prefix", () => {
    expect(emptyRenderKind(null)).toBe(EMPTY_RENDER_KIND);
  });
});
