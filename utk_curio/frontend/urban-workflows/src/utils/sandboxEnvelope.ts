/**
 * The sandbox wraps every value it returns as `{data, dataType}` (`parseOutput`
 * in sandbox/util/parsers.py), and a list or a tuple of outputs wraps each of
 * its elements too, so `[2, 4, 6]` arrives as three `{data: 2, dataType:
 * "int"}` objects. A dict's values are left as they are, unless the dict holds
 * frames: then each value is wrapped as well, under its key.
 */

/** The dataType names of the envelopes around plain values. */
const VALUE_ENVELOPES = new Set(["int", "float", "bool", "str", "list", "dict", "outputs"]);

/** The dataType names of the envelopes around frames. */
const FRAME_ENVELOPES = new Set(["dataframe", "geodataframe"]);

function isEnvelope(value: unknown): value is { dataType: string; data: unknown } {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    && typeof (value as { dataType?: unknown }).dataType === "string" && "data" in value;
}

/**
 * A dict of frames, as `/get` answers one once its `dict` envelope is peeled
 * (`{key: envelope}`, every value in its own envelope), read as the `outputs`
 * envelope a tuple of frames is: each value keeps its envelope and is named
 * after its key (`layerName`), so whatever draws a tuple's frames draws these.
 * `null` for anything else, a JSON dict among them.
 */
export function keyedFramesAsOutputs(value: unknown): { dataType: "outputs"; data: any[] } | null {
  if (value === null || typeof value !== "object" || Array.isArray(value) || isEnvelope(value)) return null;
  const entries = Object.entries(value);
  if (entries.length === 0 || !entries.every(([, item]) => isEnvelope(item))) return null;
  if (!entries.some(([, item]) => FRAME_ENVELOPES.has((item as { dataType: string }).dataType))) return null;
  return {
    dataType: "outputs",
    data: entries.map(([key, item]) => ({ ...(item as object), layerName: key })),
  };
}

/**
 * *value* with the sandbox's value envelopes peeled off, through lists and
 * tuples. Frames and rasters keep theirs, since what reads them needs the
 * dataType; an object whose dataType is anything else is user data that
 * happens to have those keys, and is left alone.
 */
export function unwrapValueEnvelopes(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(unwrapValueEnvelopes);
  if (value === null || typeof value !== "object") return value;
  const envelope = value as { data?: unknown; dataType?: unknown };
  if (typeof envelope.dataType === "string" && "data" in envelope
      && VALUE_ENVELOPES.has(envelope.dataType)) {
    return unwrapValueEnvelopes(envelope.data);
  }
  return value;
}
