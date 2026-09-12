/**
 * Choosing a starter spec from the shape of the data.
 *
 * The safety property under all of this is that a wrong default locked into the
 * buffer is worse than no default: the user has to notice it and undo it. So
 * classification reads declared pandas dtypes rather than sniffing values, and
 * the ladder returns `null` rather than a half-built spec whenever nothing
 * usable is present.
 */
import {
  DEFAULT_SPEC_RULES,
  chooseDefaultSpec,
  classifyColumns,
  defaultSpecText,
  isEmptySpecBuffer,
} from "../../utils/vegaDefaultSpec";

const roles = (cols: ReturnType<typeof classifyColumns>) =>
  Object.fromEntries(cols.map((c) => [c.name, c.role]));

describe("classifyColumns", () => {
  test("maps pandas dtypes to roles", () => {
    const schema = {
      geom: "geometry",
      when: "datetime64[ns]",
      span: "timedelta64[ns]",
      quarter: "period[Q-DEC]",
      pop: "int64",
      density: "float64",
      count: "uint32",
      name: "object",
      label: "str",
      flag: "bool",
      bucket: "category",
    };

    expect(roles(classifyColumns(schema, []))).toEqual({
      geom: "geometry",
      when: "temporal",
      span: "temporal",
      quarter: "temporal",
      pop: "quantitative",
      density: "quantitative",
      count: "quantitative",
      name: "nominal",
      label: "nominal",
      flag: "nominal",
      bucket: "nominal",
    });
  });

  test("the declared geometry column wins over its dtype", () => {
    const cols = classifyColumns({ shape: "object" }, [], "shape");

    expect(roles(cols)).toEqual({ shape: "geometry" });
  });

  test("the declared geometry column is included even when no row carries it", () => {
    // A FeatureCollection keeps the active geometry on the feature, not among
    // its properties, so a schema-less payload's sample rows never mention it.
    // This is the shape /get-preview hands a node whose input is an artifact.
    const rows = Array.from({ length: 12 }, (_, i) => ({
      zip: String(60600 + (i % 11)),
      kind: "boundary",
    }));

    const cols = classifyColumns(null, rows, "geometry");

    expect(roles(cols)).toEqual({ zip: "nominal", kind: "nominal", geometry: "geometry" });
  });

  test("__row_index__ is never a chart field", () => {
    const cols = classifyColumns({ __row_index__: "int64", pop: "int64" }, []);

    expect(cols.map((c) => c.name)).toEqual(["pop"]);
  });

  test("a nominal column with one distinct value per row is an identifier", () => {
    // Charting it produces one bar per row, which is noise, not a start.
    const rows = Array.from({ length: 12 }, (_, i) => ({
      id: `id-${i}`,
      zone: i % 2 ? "N" : "S",
    }));
    const cols = classifyColumns({ id: "str", zone: "str" }, rows);

    expect(cols.map((c) => c.name)).toEqual(["zone"]);
  });

  test("the identifier heuristic needs enough rows to mean anything", () => {
    // On a two-row sample every nominal column has all-distinct values, and
    // dropping them would throw away the column the chart should group by.
    const rows = [{ zone: "N", pop: 1 }, { zone: "S", pop: 2 }];
    const cols = classifyColumns({ zone: "str", pop: "int64" }, rows);

    expect(cols.map((c) => c.name)).toEqual(["zone", "pop"]);
  });

  test("an unknown dtype is skipped rather than guessed at", () => {
    expect(classifyColumns({ weird: "complex128" }, [])).toEqual([]);
  });

  test("falls back to sniffing values when there is no schema", () => {
    const rows = [{ pop: 1, name: "a", geom: { type: "Polygon", coordinates: [] } }];

    expect(roles(classifyColumns(null, rows))).toEqual({
      pop: "quantitative",
      name: "nominal",
      geom: "geometry",
    });
  });
});

describe("the ladder", () => {
  const pick = (schema: Record<string, string>, geometryName?: string | null) =>
    chooseDefaultSpec(classifyColumns(schema, [], geometryName)) as any;

  test("geometry + quantitative gives a choropleth", () => {
    const spec = pick({ geom: "geometry", pop: "int64" });

    expect(spec.mark).toBe("geoshape");
    expect(spec.encoding.shape).toEqual({ field: "geom", type: "geojson" });
    expect(spec.encoding.color.field).toBe("pop");
  });

  test("a GeoDataFrame that arrives without a schema still gives a map", () => {
    // Every attribute a string and the geometry named but not carried in the
    // rows: before the geometry column was included by name this came out as
    // the last ladder row, a bar of counts by zip.
    const rows = Array.from({ length: 12 }, (_, i) => ({ zip: String(60600 + (i % 11)) }));

    const spec = chooseDefaultSpec(classifyColumns(null, rows, "geometry")) as any;

    expect(spec.mark).toBe("geoshape");
    expect(spec.encoding.shape).toEqual({ field: "geometry", type: "geojson" });
  });

  test("geometry alone gives an uncoloured map", () => {
    const spec = pick({ geom: "geometry" });

    expect(spec.mark).toBe("geoshape");
    expect(spec.encoding.color).toBeUndefined();
  });

  test("the generated geo spec is self-contained", () => {
    // It writes out shape and projection rather than leaning on the injection
    // in vegaGeoSpec: the node is a teaching surface, and a spec that works by
    // magic teaches nothing.
    const spec = pick({ geom: "geometry", pop: "int64" });

    expect(spec.projection).toEqual({ type: "mercator" });
    expect(spec.encoding.shape.type).toBe("geojson");
  });

  test("temporal + quantitative gives a line", () => {
    const spec = pick({ when: "datetime64[ns]", pop: "int64" });

    expect(spec.mark).toBe("line");
    expect(spec.encoding.x).toEqual({ field: "when", type: "temporal" });
    expect(spec.encoding.y.field).toBe("pop");
  });

  test("nominal + quantitative gives an explicitly aggregated bar", () => {
    // Without a stated aggregate, vega-lite silently overplots one bar per row.
    const spec = pick({ zone: "str", pop: "int64" });

    expect(spec.mark).toBe("bar");
    expect(spec.encoding.y.aggregate).toBe("mean");
  });

  test("two quantitative columns give a scatter", () => {
    const spec = pick({ a: "float64", b: "float64" });

    expect(spec.mark).toBe("point");
    expect(spec.encoding.x.field).toBe("a");
    expect(spec.encoding.y.field).toBe("b");
  });

  test("one quantitative column gives a histogram", () => {
    const spec = pick({ a: "float64" });

    expect(spec.mark).toBe("bar");
    expect(spec.encoding.x.bin).toBe(true);
    expect(spec.encoding.y.aggregate).toBe("count");
  });

  test("one nominal column gives a count bar", () => {
    const spec = pick({ zone: "str" });

    expect(spec.mark).toBe("bar");
    expect(spec.encoding.x.field).toBe("zone");
    expect(spec.encoding.y.aggregate).toBe("count");
  });

  test("nothing usable gives null, never a half-built spec", () => {
    expect(chooseDefaultSpec([])).toBeNull();
    expect(pick({ __row_index__: "int64" })).toBeNull();
    expect(defaultSpecText({ weird: "complex128" }, [])).toBeNull();
  });

  test("geometry outranks every other shape of data", () => {
    const spec = pick({ geom: "geometry", when: "datetime64[ns]", pop: "int64", zone: "str" });

    expect(spec.mark).toBe("geoshape");
  });

  test("ties break on column order", () => {
    expect(pick({ b: "float64", a: "float64" }).encoding.x.field).toBe("b");
  });

  test("every spec is complete enough to run", () => {
    const schemas: Record<string, string>[] = [
      { geom: "geometry", pop: "int64" },
      { when: "datetime64[ns]", pop: "int64" },
      { zone: "str", pop: "int64" },
      { a: "float64", b: "float64" },
      { a: "float64" },
      { zone: "str" },
    ];
    for (const schema of schemas) {
      const spec = pick(schema);
      expect(spec.$schema).toContain("vega-lite");
      expect(spec.data).toEqual({ name: "data" });
      expect(spec.mark).toBeTruthy();
    }
  });
});

describe("DEFAULT_SPEC_RULES", () => {
  test("the ids and their order match the table in docs/USAGE.md", () => {
    // First match wins, so the order *is* the behaviour. If you add or reorder
    // a rule, update the ladder table in docs/USAGE.md to match.
    expect(DEFAULT_SPEC_RULES.map((r) => r.id)).toEqual([
      "geometry+quantitative",
      "geometry",
      "temporal+quantitative",
      "nominal+quantitative",
      "two-quantitative",
      "one-quantitative",
      "one-nominal",
    ]);
  });
});

describe("isEmptySpecBuffer", () => {
  test("empty, whitespace and a bare object count as empty", () => {
    expect(isEmptySpecBuffer("")).toBe(true);
    expect(isEmptySpecBuffer("   \n ")).toBe(true);
    expect(isEmptySpecBuffer("{}")).toBe(true);
    expect(isEmptySpecBuffer(null)).toBe(true);
    expect(isEmptySpecBuffer(undefined)).toBe(true);
  });

  test("anything the user might have typed does not", () => {
    // The whole safety property: this gate is what stops a default overwriting
    // real work.
    expect(isEmptySpecBuffer('{"mark": "bar"}')).toBe(false);
    expect(isEmptySpecBuffer("{ ")).toBe(false);
  });
});
