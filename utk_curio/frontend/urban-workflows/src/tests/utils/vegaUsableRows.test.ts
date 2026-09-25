/**
 * dev/137 counts the rows whose ENCODED fields hold a value. A field the
 * document derives itself (`calculate`, `fold`, ...) is on no input row, so
 * counting it read every row as null and failed examples 02 and 09 with
 * "every value of ... is null" over data that renders fine.
 *
 * The rows here come through the real Arrow path (IPC -> tableToEnvelope ->
 * prepareVegaInput), the one #405 made the default, to pin that the count does
 * not depend on the transport.
 */
import { tableFromArrays, tableFromIPC, tableToIPC } from "apache-arrow";

import { tableToEnvelope } from "../../services/arrowEnvelope";
import { prepareVegaInput } from "../../utils/vegaInput";
import { renderOutcome } from "../../utils/renderOutcome";
import { usableCounts } from "../../utils/vegaUsableRows";

async function rowsViaArrow(arrays: Record<string, any>) {
  const table = tableFromIPC(tableToIPC(tableFromArrays(arrays)));
  const envelope = tableToEnvelope(table, { "X-Curio-Kind": "dataframe" });
  return prepareVegaInput({ dataType: "dataframe", data: envelope.data }, {});
}

function verdict(values: any[], spec: any, drawn: number) {
  return renderOutcome({ rowsIn: values.length, drawn, ...usableCounts(values, spec) });
}

// docs/examples/02-vega-lite-spatial-density.json, node 4226b7ed.
const SPEC_02 = {
  transform: [
    { filter: "datum.TOTAL_ROOF_SQFT > 0" },
    { calculate: "log(datum.TOTAL_ROOF_SQFT) / log(10)", as: "log_roof_size" },
  ],
  mark: "bar",
  encoding: {
    x: { field: "log_roof_size", bin: { maxbins: 30 } },
    y: { aggregate: "count", type: "quantitative" },
  },
};

// docs/examples/09-heterogeneous-data-linked-views.json, node bcded943.
const SPEC_09 = {
  transform: [{ fold: ["gt_65"], as: ["Variable", "Value"] }],
  mark: { type: "boxplot", size: 60 },
  encoding: {
    x: { field: "Variable", type: "nominal" },
    y: { field: "Value", type: "quantitative" },
  },
};

describe("usable rows are counted over the fields the input carries", () => {
  test("a calculate-derived field is not read as null (example 02)", async () => {
    const { values } = await rowsViaArrow({
      TOTAL_ROOF_SQFT: BigInt64Array.from([1200n, 5400n, 88000n]),
    });
    expect(values).toHaveLength(3);
    expect(values[0].TOTAL_ROOF_SQFT).toBe(1200);

    const outcome = verdict(values, SPEC_02, 12);
    expect(outcome.empty).toBe(false);
    expect(outcome.message).not.toContain("log_roof_size is null");
  });

  test("fold-derived fields are not read as null (example 09)", async () => {
    const { values } = await rowsViaArrow({
      gt_65: Float64Array.from([0.12, 0.3, 0.07]),
    });
    const outcome = verdict(values, SPEC_09, 5);
    expect(outcome.empty).toBe(false);
  });

  test("a delivered column of nulls is still an empty render (dev/137 R4)", async () => {
    const { values } = await rowsViaArrow({
      zip: ["60601", "60602"],
      population: Float64Array.from([NaN, NaN]),   // Arrow NaN -> null in the envelope
    });
    const outcome = verdict(values, {
      mark: "bar",
      encoding: { x: { field: "zip" }, y: { field: "population" } },
    }, 2);
    // `zip` has values, so rows ARE usable: nothing to report.
    expect(outcome.empty).toBe(false);

    const onlyNulls = verdict(values, {
      mark: "bar",
      encoding: { y: { field: "population" } },
    }, 2);
    expect(onlyNulls.empty).toBe(true);
    expect(onlyNulls.message).toContain("every value of population is null");
  });

  test("a derived field beside an all-null delivered one still reports the delivered one", async () => {
    const { values } = await rowsViaArrow({ v: Float64Array.from([NaN, NaN]) });
    const outcome = verdict(values, {
      transform: [{ calculate: "1", as: "one" }],
      mark: "point",
      encoding: { x: { field: "one" }, y: { field: "v" } },
    }, 2);
    expect(outcome.empty).toBe(true);
    expect(outcome.message).toContain("every value of v is null");
  });
});
