/**
 * The rows of a Vega-Lite chart's `inputs` dataset (#662): every input's rows,
 * stacked in circle order, each with its circle under `__input__`, the id of
 * the scenario box its node is in under `scenario` (null for a node in no box)
 * and that box's name under `scenario_name` (else the node's name).
 *
 * The rules are `stack_inputs`'s in `utk_curio/sandbox/util/scenario_stack.py`,
 * which an exported notebook calls; both twins read `stackedInputs.cases.json`:
 *
 * - a table (a list of records, a dict of columns, or a dict of values, which
 *   is one row) keeps its rows, and a column one input lacks is empty (null)
 *   in its rows;
 * - a value (a number, a text, true or false, or a list of them) is one row
 *   each under `value`;
 * - inputs of different kinds, an input with no value, one that cannot be read
 *   as rows, and one that already has a `scenario` or `scenario_name` column
 *   are refused, with a message naming the input. A refusal is returned, never
 *   thrown, so the chart can show it.
 *
 * Python's rules for GeoDataFrames, coordinate systems and rasters have no
 * JSON form; they stay its own. Pure: no input is changed.
 */
import { SCENARIO_FIELD, SCENARIO_NAME_FIELD } from "./scenarioColors";

/** The column each stacked row holds its circle in. */
export const INPUT_FIELD = "__input__";
/** The column a value is one row under. */
export const VALUE_FIELD = "value";

/** What a refusal names the stacking by: the dataset it makes. */
const WHO = 'The dataset "inputs"';

/** One input, in circle order. */
export interface StackEntry {
  /** The id of the box its node is in, or null for a node in no box. */
  scenario: string | null;
  /** The box's name, or the node's. */
  name: string;
  /** Its value: records, a dict of columns or of values, a value or a list of them. */
  value: unknown;
}

export type StackedInputs = { rows: Record<string, unknown>[] } | { refusal: string };

type Row = Record<string, unknown>;
type Kind = "table" | "value" | "empty";
type Part = { kind: Kind; rows: Row[]; columns: string[] };

const KIND_WORDS: Record<Exclude<Kind, "empty">, string> = { table: "a table", value: "a value" };

const isRecord = (value: unknown): value is Row =>
  value !== null && typeof value === "object" && !Array.isArray(value);

const isScalar = (value: unknown): boolean =>
  typeof value === "string" || typeof value === "number" || typeof value === "boolean";

const has = (row: Row, column: string): boolean => Object.prototype.hasOwnProperty.call(row, column);

function labelOf(position: number, name: string): string {
  return name ? `input_${position} (${name})` : `input_${position}`;
}

/** Each column once, in the order the rows first hold it. */
function columnsOf(rows: readonly Row[]): string[] {
  const columns: string[] = [];
  for (const row of rows) for (const column of Object.keys(row)) if (!columns.includes(column)) columns.push(column);
  return columns;
}

/** The rows *value* adds, with its kind and its columns, or why it adds none. */
function partOf(label: string, value: unknown): Part | { refusal: string } {
  if (value === null || value === undefined) {
    return {
      refusal: `${WHO}: ${label} has no value. Run the node that feeds it, and check that its code returns its result.`,
    };
  }
  if (isRecord(value)) {
    const entries = Object.entries(value);
    if (entries.length === 0) return { kind: "empty", rows: [], columns: [] };
    const columns = entries.map(([key]) => key);
    if (entries.every(([, cell]) => cell === null || isScalar(cell))) return { kind: "table", rows: [value], columns };
    const lengths = new Set(entries.map(([, cell]) => (Array.isArray(cell) ? cell.length : -1)));
    if (!lengths.has(-1) && lengths.size === 1) {
      const [length] = [...lengths];
      const rows = Array.from({ length }, (_, i) =>
        Object.fromEntries(entries.map(([key, cell]) => [key, (cell as unknown[])[i]])),
      );
      return { kind: "table", rows, columns };
    }
    return {
      refusal: `${WHO}: ${label} is a dict it cannot read as rows. Return one value per key (one row), or lists of one length per key (one column each).`,
    };
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return { kind: "empty", rows: [], columns: [] };
    if (value.every(isRecord)) return { kind: "table", rows: value as Row[], columns: columnsOf(value as Row[]) };
    if (value.every(isScalar)) {
      return { kind: "value", rows: value.map((item) => ({ [VALUE_FIELD]: item })), columns: [VALUE_FIELD] };
    }
    return {
      refusal: `${WHO}: ${label} is a list that mixes records and values. Return records (one dict per row) or values.`,
    };
  }
  if (isScalar(value)) return { kind: "value", rows: [{ [VALUE_FIELD]: value }], columns: [VALUE_FIELD] };
  return {
    refusal: `${WHO}: ${label} is a ${typeof value}, which it cannot stack. Connect a table, a value, or a list of them.`,
  };
}

/** A cell as the stacked rows hold it: a missing one, or a number that is none, is null. */
const cellOf = (row: Row, column: string): unknown => {
  if (!has(row, column)) return null;
  const cell = row[column];
  return cell === undefined || (typeof cell === "number" && Number.isNaN(cell)) ? null : cell;
};

/**
 * The rows one input adds by these rules, before any scenario names them: the
 * input as a chart reading `inputs` reads it by itself, `input_<k>`. A column
 * one of its rows lacks is empty there; none when it cannot be read as rows.
 * Python's `input_rows` is its twin.
 */
export function inputRows(value: unknown): Record<string, unknown>[] {
  const part = partOf("input", value);
  if ("refusal" in part) return [];
  return part.rows.map((row) => Object.fromEntries(part.columns.map((column) => [column, cellOf(row, column)])));
}

/** Every input's rows stacked under its scenario, or why they cannot be. */
export function stackInputs(entries: readonly StackEntry[]): StackedInputs {
  const parts: Array<Part & { label: string; position: number; entry: StackEntry }> = [];
  for (const [position, entry] of entries.entries()) {
    const name = entry.name == null ? "" : String(entry.name);
    const label = labelOf(position, name);
    const part = partOf(label, entry.value);
    if ("refusal" in part) return part;
    for (const column of [SCENARIO_FIELD, SCENARIO_NAME_FIELD]) {
      if (part.columns.includes(column)) {
        return {
          refusal: `${WHO}: ${label} already has a column named ${column}. Rename it in the node that feeds it: the stacked table adds its own.`,
        };
      }
    }
    // The circle is the stacking's own: an input's column of that name gives way.
    const columns = part.columns.filter((column) => column !== INPUT_FIELD);
    parts.push({ ...part, columns, label, position, entry: { ...entry, name } });
  }

  const shown = parts.filter((part) => part.kind !== "empty");
  if (new Set(shown.map((part) => part.kind)).size > 1) {
    const described = shown
      .map((part) => `${part.label} is ${KIND_WORDS[part.kind as Exclude<Kind, "empty">]}`)
      .join(", ");
    return {
      refusal: `${WHO} stacks inputs of one kind, and these differ: ${described}. Connect outcomes of the same kind.`,
    };
  }

  const columns: string[] = [];
  for (const part of parts) for (const column of part.columns) if (!columns.includes(column)) columns.push(column);

  const rows: Row[] = [];
  for (const part of shown) {
    for (const row of part.rows) {
      const stacked: Row = {};
      for (const column of columns) stacked[column] = cellOf(row, column);
      stacked[INPUT_FIELD] = part.position;
      stacked[SCENARIO_FIELD] = part.entry.scenario ?? null;
      stacked[SCENARIO_NAME_FIELD] = part.entry.name;
      rows.push(stacked);
    }
  }
  return { rows };
}
