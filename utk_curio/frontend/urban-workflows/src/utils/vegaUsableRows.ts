/**
 * dev/137: the fields a Vega-Lite document plots, and how many input rows hold
 * a usable value in them. A chart handed rows that are all null in its encoded
 * field draws nothing whether the renderer drops those rows or draws
 * zero-extent marks, so the DATA decides, not the scene graph.
 *
 * Only a field the input actually carries can be judged. A field that no input
 * row has is made by the document itself (`calculate`, `fold`, `aggregate`,
 * `window`, `lookup`, ...) or is unknown, and the input cannot say whether it
 * will hold a value: that field is left out, and with nothing left no claim is
 * made (dev/137 R6).
 */

/** Every `encoding.<channel>.field` in the spec, in first-seen order. */
export function encodedFields(spec: any): string[] {
  const out: string[] = [];
  const walk = (node: any) => {
    if (!node || typeof node !== "object") return;
    if (Array.isArray(node)) { node.forEach(walk); return; }
    for (const [key, value] of Object.entries(node)) {
      if (key === "encoding" && value && typeof value === "object") {
        for (const channel of Object.values(value as Record<string, any>)) {
          const field = (channel as any)?.field;
          if (typeof field === "string" && field && !out.includes(field)) {
            out.push(field);
          }
        }
      }
      walk(value);
    }
  };
  walk(spec);
  return out;
}

/** The fields at least one input row carries as a key. */
export function deliveredFields(values: any[], fields: string[]): string[] {
  if (!Array.isArray(values)) return [];
  return fields.filter((field) =>
    values.some((row) => row != null && typeof row === "object" && field in row),
  );
}

/** Rows holding a usable value in at least one of `fields`; undefined = no claim. */
export function usableRowCount(values: any[], fields: string[]): number | undefined {
  if (!Array.isArray(values) || fields.length === 0) return undefined;
  return values.filter((row) =>
    fields.some((field) => {
      const value = row?.[field];
      return value !== null && value !== undefined && value !== ""
        && !(typeof value === "number" && Number.isNaN(value));
    }),
  ).length;
}

/** What `renderOutcome` needs from the data: the judged fields and their count. */
export function usableCounts(
  values: any[],
  spec: any,
): { usableRows: number | undefined; usableFields: string[] } {
  const usableFields = deliveredFields(values, encodedFields(spec));
  return { usableRows: usableRowCount(values, usableFields), usableFields };
}
