/**
 * The sandbox wraps every value it returns as `{data, dataType}` (`parseOutput`
 * in sandbox/util/parsers.py), and a list or a tuple of outputs wraps each of
 * its elements too, so `[2, 4, 6]` arrives as three `{data: 2, dataType:
 * "int"}` objects. A dict's values are left as they are.
 */

/** The dataType names of the envelopes around plain values. */
const VALUE_ENVELOPES = new Set(["int", "float", "bool", "str", "list", "dict", "outputs"]);

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
