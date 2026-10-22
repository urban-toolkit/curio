/**
 * A column's name as a Vega-Lite field, and the column a field names (issue
 * 1042). Vega-Lite reads a `.` or a `[` in a field as a path into the row, so
 * the column `rain.mm` is the field `rain\.mm`: a backslash keeps the
 * character after it as it is. Where Vega-Lite escapes a field itself (an
 * aggregate, a bin transform, a condition's test) it reads `rain.mm` as that
 * column too, so a field names a column when its text, or its text unescaped,
 * is the column's name.
 *
 * Pure, with no imports.
 */

/**
 * *name* as a Vega-Lite field that names that column: each `.`, `[` and `]`
 * behind a backslash. A name that already holds a backslash is taken as
 * escaped by hand and kept as it is: Vega-Lite reads no column whose name
 * holds one anyway. Kept in sync with `vega_field_name` in
 * `execution/code_references.py`.
 */
export function vegaFieldName(name: string): string {
  return name.includes("\\") ? name : name.replace(/[.[\]]/g, (ch) => "\\" + ch);
}

/** The text *field* spells, each backslash keeping the character after it as
 * it is: `rain\.mm` is `rain.mm`. Kept in sync with `unescaped_field` in
 * `agents/domain/document_validation.py`. */
export function unescapedVegaField(field: string): string {
  let out = "";
  for (let i = 0; i < field.length; i += 1) {
    if (field[i] === "\\") {
      i += 1;
      if (i < field.length) out += field[i];
    } else {
      out += field[i];
    }
  }
  return out;
}

/** The column of *rows* that *field* names: the field as it is written when a
 * row holds it, else its text unescaped when a row holds that; null when no
 * row holds either. */
export function vegaFieldColumn(rows: readonly unknown[], field: string): string | null {
  const holds = (name: string) =>
    rows.some((row) => row !== null && typeof row === "object" && name in (row as Record<string, unknown>));
  if (holds(field)) return field;
  const plain = unescapedVegaField(field);
  return plain !== field && holds(plain) ? plain : null;
}
