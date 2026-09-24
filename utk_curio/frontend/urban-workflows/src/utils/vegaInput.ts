/**
 * The one path from an input payload to the rows a Vega-Lite view renders.
 *
 * `useVega` and `vegaLiteAdapter` each had their own copy of this: validate the
 * dataType, fetch by path or read inline data, parse, stamp `__row_index__`.
 * Two copies of the data path is how the geometry handling would drift apart
 * again, so they share this one.
 *
 * **Geometry is gated on the spec, not on the dataType.** A spec that does not
 * draw geometry never enters the geo path and its rows stay exactly what they
 * are today -- which matters, because shipped dataflows chart multi-megabyte
 * GeoJSON as bar charts and attaching geometry unconditionally would inline all
 * of it into `spec.data.values` and re-ship it on every brush. Gating on the
 * spec is also what lets a plain DataFrame carrying shapely objects be drawn.
 *
 * No `vega` / `vega-lite` import here, so it stays testable under jest.
 */
import { fetchData } from "../services/api";
import { parseDataframe, parseGeoDataframeWithGeometry } from "./parsing";
import type { NodeEmptyReason } from "./nodeEmptyState";
import { normalizeGeoSpec, specNeedsGeometry } from "./vegaGeoSpec";

export type PreparedVegaInput = {
  values: any[];
  /** Set when the node has nothing to draw and should say why. */
  emptyReason?: NodeEmptyReason;
  /** A longer, spec-specific explanation, when there is one. */
  detail?: string;
};

const TABULAR_TYPES = ["dataframe", "geodataframe"];

/**
 * Turn `data.input` into render-ready rows for `spec`.
 *
 * Never throws for an input problem: a rejected input type comes back as an
 * `emptyReason` so the caller can render it in the node body. It used to be a
 * toast that the caller could not even catch, because `processData()` was not
 * awaited.
 */
export async function prepareVegaInput(
  input: any,
  spec: any,
): Promise<PreparedVegaInput> {
  if (input == null || input === "") return { values: [] };

  const dataType = input.dataType;
  if (!TABULAR_TYPES.includes(dataType)) {
    return {
      values: [],
      emptyReason: "input-type-rejected",
      detail: `${dataType} is not a valid input type for the 2D Plot (Vega-Lite).`,
    };
  }

  const payload = input.path ? (await fetchData(input.path)).data : input.data;
  if (payload == null) return { values: [] };

  const wantsGeometry = specNeedsGeometry(spec);
  let result: PreparedVegaInput;

  if (dataType === "geodataframe") {
    const parsed = parseGeoDataframeWithGeometry(payload, wantsGeometry);
    result = { values: parsed.values };
    if (wantsGeometry) {
      const geo = normalizeGeoSpec(spec, parsed.values, {
        geometryName: parsed.geometryName,
        crsName: parsed.crsName,
      });
      result.emptyReason = geo.emptyReason;
      result.detail = geo.detail;
    }
  } else {
    const values = parseDataframe(payload);
    result = { values };
    if (wantsGeometry) {
      // A plain DataFrame whose spec asks for geometry: the column is found by
      // sniffing the rows, since there is no declared geometry_name.
      const geo = normalizeGeoSpec(spec, values, { geometryName: null });
      result.emptyReason = geo.emptyReason;
      result.detail = geo.detail;
    }
  }

  // Positional, and stamped last so it survives the geo passes. The scenegraph
  // reads it back to map a vega tuple id to the original row.
  result.values.forEach((value: any, index: number) => {
    value.__row_index__ = index;
  });

  return result;
}
