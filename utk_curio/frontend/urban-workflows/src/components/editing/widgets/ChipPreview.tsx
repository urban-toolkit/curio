/**
 * What a chip's hover shows (#662): one preview of what the chip holds, the
 * same for a header tag above an editor and for the chip in the editor, drawn
 * in the one Curio tooltip. Pure: what the chip names, the node's scope and
 * what has been read for it go in, and the preview comes out.
 *
 * - An input: where it comes from (the scenario box with its swatch, else the
 *   node that feeds it, then that node's type when its title is another), its
 *   size and kind, and its first rows, each column with its dtype and a
 *   geometry as its type. A tuple says how code reads its values, then each
 *   one; layers, each layer's size and geometry type; a value, itself; a JSON
 *   list or dict, its first items; a raster, that it is one.
 * - A column: its dtype, its first values, and over the rows read its range
 *   (a number) or its distinct values (anything else), with the empty ones.
 *   A layer: its feature count, geometry type and first rows.
 * - The stacked `inputs` (utils/scenarios/stackedInputs): the inputs it stacks
 *   and its first rows, which begin with scenario_name, scenario and
 *   __input__; `inputs.<field>` reads like a column.
 * - A widget or a Parameter: its control, its value, its choices or range,
 *   and what the chip writes; a Parameter, its node and how many nodes read it.
 *   A selection: its view, its ids, and the rows they pick once the view has
 *   drawn. The scenario chips: each box's swatch, name and color, and what the
 *   chip writes.
 * - A chip with a problem shows the problem. An input not run, stale, failed
 *   or being read says so; a header tag ends with how to use it (*tag*).
 *
 * It shows 5 rows by 6 columns, cells cut at 24 characters, a tuple's or a
 * layer list's first 3 with 3 rows each; numbers with at most 4 decimals, and
 * an empty cell as a grey "null".
 */
import React, { useEffect, useSyncExternalStore } from "react";
import styles from "./ChipPreview.module.css";
import type { ChipPreviewSource } from "./chipPreviewSource";
import {
  STACKED_FIELDS,
  inputName,
  parseReference,
  referenceText,
  resolveReferences,
  scenarioColorScale,
  scenarioInputColor,
  widgetLiteral,
  type CodeLanguage,
  type InputScope,
  type ParsedReference,
  type ReferenceScope,
} from "../../../utils/references/codeReferences";
import {
  PREVIEW_ROWS,
  columnSummaryOf,
  type ColumnSummary,
  type InputPreview,
  type InputPreviewState,
  type InputSource,
  type PreviewTable,
} from "../../../utils/references/inputScope";
import { INPUT_FIELD, stackInputs, type StackEntry } from "../../../utils/scenarios/stackedInputs";
import {
  SCENARIO_FIELD,
  SCENARIO_NAME_FIELD,
  anyFromABox,
  tableTextColor,
  type ScenarioLabel,
} from "../../../utils/scenarios/scenarioColors";
import {
  CHOICE_KINDS,
  NUMERIC_KINDS,
  WIDGET_KIND_LABELS,
  effectiveValue,
  type WidgetDef,
  type WidgetValue,
} from "../../../utils/widgets/widgetModel";

/** The line a header tag's preview ends with. */
export const TAG_HOW = "Drag into the code, or click to insert it at the cursor";

/** The rows a tuple's value, a layer or a selection shows. */
const PART_ROWS = 3;
/** The columns a table shows. */
const TABLE_COLUMNS = 6;
/** The characters a cell shows. */
const CELL_CHARS = 24;
/** The characters a value on a line of its own shows. */
const VALUE_CHARS = 120;
/** The values of a tuple, and the layers of an input, a preview shows. */
const SHOWN_PARTS = 3;
/** The ids of a selection a preview lists. */
const SHOWN_IDS = 5;
/** The dtypes of the fields the stacking adds, as Python's stack_inputs gives them. */
const STACKED_DTYPES: Record<string, string> = {
  [SCENARIO_NAME_FIELD]: "str",
  [SCENARIO_FIELD]: "str",
  [INPUT_FIELD]: "int64",
};

type Row = Record<string, unknown>;

/** What has been read for a node's chips, beyond its scope. */
export interface ChipPreviewData {
  /** Each input's preview state, by its circle (hook/useInputScope). */
  inputs?: Record<number, InputPreviewState>;
  /** Each shared tag's Parameter node, by the tag's name (`parameterPreviewOf`). */
  parameters?: Record<string, { node: string; readers: number }>;
  /** Each selection tag's view, by the tag's name: its title, and the rows
   * the tag's ids pick once the view has drawn (`readSelectionRows`). */
  selections?: Record<string, { view: string; rows?: { columns: string[]; rows: Row[] } | null }>;
}

export interface ChipPreviewProps {
  /** What stands inside the chip: `input_1`, `input_0.accessibility`, `scenario colors`. */
  inner: string;
  /** What the node's chips can name. */
  scope: ReferenceScope;
  /** The editor's language: what a widget's chip writes, and whether a tuple is read in code. */
  language: CodeLanguage;
  data?: ChipPreviewData;
  /** Why the chip fails, when it does. */
  problem?: string | null;
  /** A header tag's preview, which ends with how to use the tag. */
  tag?: boolean;
}

const count = (n: number) => n.toLocaleString("en-US");

/** *n* things: "1 row", "79 rows". */
const countOf = (n: number, one: string, many: string) => `${count(n)} ${n === 1 ? one : many}`;

/** *names* as a list in words: `a`, `a and b`, `a, b and c`. */
const inWords = (names: readonly string[]) =>
  names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;

const articleOf = (word: string) => (/^[aeiou]/i.test(word) ? "an" : "a");

const unique = (items: readonly string[]) => [...new Set(items)];

/** A number with at most 4 decimals, its trailing zeros dropped: 8.041667 is 8.0417, 11.0 is 11. */
export function formatNumber(n: number): string {
  if (!Number.isFinite(n) || Number.isInteger(n)) return String(n);
  return String(Number(n.toFixed(4)));
}

const isEmptyCell = (value: unknown) =>
  value === null || value === undefined || (typeof value === "number" && Number.isNaN(value));

function textOfValue(value: unknown): string {
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return String(value);
  return JSON.stringify(value) ?? String(value);
}

const cut = (text: string, limit: number) => (text.length > limit ? `${text.slice(0, limit - 1)}…` : text);

/** One value as a cell shows it: cut, and an empty one as a grey "null". */
function Cell({ value, limit = CELL_CHARS }: { value: unknown; limit?: number }) {
  if (isEmptyCell(value)) {
    return (
      <span className={styles.null} data-null="true">
        null
      </span>
    );
  }
  return <>{cut(textOfValue(value), limit)}</>;
}

function Swatch({ color }: { color: string }) {
  return <span className={styles.swatch} data-swatch={color} style={{ background: color }} aria-hidden="true" />;
}

function Text({ children, muted = false }: { children: React.ReactNode; muted?: boolean }) {
  return <span className={muted ? `${styles.segment} ${styles.muted}` : styles.segment}>{children}</span>;
}

function Head({ chip, chipClass, children }: { chip: string; chipClass: string; children?: React.ReactNode }) {
  return (
    <div className={styles.head} data-preview-head="true">
      <span className={`${styles.chip} ${chipClass}`} data-preview-chip="true">
        {chip}
      </span>
      {children}
    </div>
  );
}

type Tone = "muted" | "mono" | "problem";

function Line({ children, tone }: { children: React.ReactNode; tone?: Tone }) {
  return (
    <div className={tone ? `${styles.line} ${styles[tone]}` : styles.line} data-preview-line="true">
      {children}
    </div>
  );
}

function isNumericColumn(dtype: string | undefined, rows: readonly Row[], column: string): boolean {
  if (dtype) return /^(u?int|float)/i.test(dtype);
  const cells = rows.map((row) => row[column]).filter((cell) => !isEmptyCell(cell));
  return cells.length > 0 && cells.every((cell) => typeof cell === "number");
}

/** A table: its first *maxRows* rows by TABLE_COLUMNS columns, each column's
 * name over its dtype; *swatchOf* gives a cell the swatch of its color. */
function Table({
  caption,
  columns,
  dtypes,
  rows,
  maxRows,
  swatchOf,
}: {
  caption?: string;
  columns: readonly string[];
  dtypes: Record<string, string>;
  rows: readonly Row[];
  maxRows: number;
  swatchOf?: (column: string, value: unknown) => string | undefined;
}) {
  const shownColumns = columns.slice(0, TABLE_COLUMNS);
  const shownRows = rows.slice(0, maxRows);
  const numeric = new Set(shownColumns.filter((column) => isNumericColumn(dtypes[column], shownRows, column)));
  return (
    <table className={styles.table}>
      {caption ? <caption className={styles.caption}>{caption}</caption> : null}
      <thead>
        <tr>
          {shownColumns.map((column) => (
            <th key={column} scope="col" className={numeric.has(column) ? styles.number : undefined}>
              <span className={styles.columnName} data-column-name="true">
                {cut(column, CELL_CHARS)}
              </span>
              {dtypes[column] ? (
                <span className={styles.columnDtype} data-column-dtype="true">
                  {dtypes[column]}
                </span>
              ) : null}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {shownRows.map((row, index) => (
          <tr key={index}>
            {shownColumns.map((column) => {
              const color = swatchOf?.(column, row[column]);
              return (
                <td key={column} className={numeric.has(column) ? styles.number : undefined}>
                  {color ? <Swatch color={color} /> : null}
                  <Cell value={row[column]} />
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** What a preview says it left out of a table, or null when it shows it whole:
 * "first 5 of 79 rows", "2 rows, 6 of 8 fields". */
function cutText(total: number, shown: number, columns: number, word: string): string | null {
  const rowsCut = total > shown;
  const columnsCut = columns > TABLE_COLUMNS;
  if (!rowsCut && !columnsCut) return null;
  const rows = rowsCut ? `first ${count(shown)} of ${count(total)} rows` : countOf(total, "row", "rows");
  return columnsCut ? `${rows}, ${TABLE_COLUMNS} of ${count(columns)} ${word}` : rows;
}

/** A column's first values, then "..." when it has more. */
function ValuesLine({ values, more, swatchOf }: { values: unknown[]; more: boolean; swatchOf?: (value: unknown) => string | undefined }) {
  return (
    <Line tone="mono">
      {values.map((value, index) => {
        const color = swatchOf?.(value);
        return (
          <React.Fragment key={index}>
            {index > 0 ? ", " : null}
            {color ? <Swatch color={color} /> : null}
            <Cell value={value} />
          </React.Fragment>
        );
      })}
      {more ? ", ..." : null}
    </Line>
  );
}

/** A column over the rows read: "range 0 to 1 in all 79 rows · no empty values". */
function summaryText(summary: ColumnSummary, readRows: number, totalRows: number): string {
  const over =
    readRows < totalRows ? `in the first ${count(readRows)} rows` : totalRows === 1 ? "in its 1 row" : `in all ${count(totalRows)} rows`;
  const empties = summary.empty === 0 ? "no empty values" : countOf(summary.empty, "empty value", "empty values");
  if (summary.min !== undefined && summary.max !== undefined) {
    return `range ${formatNumber(summary.min)} to ${formatNumber(summary.max)} ${over} · ${empties}`;
  }
  if (summary.distinct) return `${countOf(summary.distinct.length, "distinct value", "distinct values")} ${over} · ${empties}`;
  return `no values ${over} · ${empties}`;
}

/** What a preview's parts are: its kind, its head, its body and its foot. */
interface Parts {
  kind: string;
  head: React.ReactNode;
  body?: React.ReactNode;
  foot?: string[];
}

/** Where an input comes from: its box, with its swatch, then the node that
 * feeds it; else that node, then its type when its title is another. */
function SourceText({ input, source }: { input?: InputScope; source?: InputSource }) {
  const box = input?.scenario?.scenario != null ? input.scenario : null;
  const title = source?.title ?? input?.label;
  if (box) {
    return (
      <>
        {" "}
        <Text>from</Text>{" "}
        <Text>
          <Swatch color={box.color} />
          {box.name}
        </Text>
        {title ? (
          <>
            {" "}
            <Text muted>· {title}</Text>
          </>
        ) : null}
      </>
    );
  }
  if (!title) return null;
  return (
    <>
      {" "}
      <Text>from {title}</Text>
      {source?.type ? (
        <>
          {" "}
          <Text muted>
            · {articleOf(source.type)} {source.type} node
          </Text>
        </>
      ) : null}
    </>
  );
}

/** What stands in for an input's rows until they can be shown: why, or null
 * once they can. *columnText* is a column's, which waits for its type too. */
function waitingLine(name: string, state: InputPreviewState | undefined, column = false): React.ReactNode {
  if (state?.source.status === "errored") return <Line>The node that feeds {name} failed.</Line>;
  if (state?.source.status === "not-run") {
    return column ? (
      <Line>Not run yet. Its type and values come after a run of {state.source.title}.</Line>
    ) : (
      <Line>Not run yet. Run {state.source.title} to see its rows.</Line>
    );
  }
  if (!state?.preview) return <Line>Reading {name}...</Line>;
  if (state.preview.kind === "unreadable") return <Line>Curio could not read {name}.</Line>;
  return null;
}

function staleLine(state: InputPreviewState | undefined): React.ReactNode {
  return state?.source.status === "stale" ? (
    <Line tone="muted">From the last run of {state.source.title}, which has changed since</Line>
  ) : null;
}

const VALUE_WORDS: Record<string, string> = {
  int: "A number",
  float: "A number",
  str: "A text",
  bool: "True or false",
  list: "A list",
  dict: "A dict",
};

/** What an input that has been read holds, under its head. */
function holdingOf(name: string, preview: InputPreview, language: CodeLanguage): { body: React.ReactNode; foot: string[] } {
  if (preview.kind === "frame") {
    const { table } = preview;
    const kind = table.frameType === "geodataframe" ? ["GeoDataFrame", table.crs].filter(Boolean).join(", ") : "DataFrame";
    const shown = Math.min(table.rows.length, PREVIEW_ROWS);
    const left = cutText(table.totalRows, shown, table.columns.length, "columns");
    return {
      body: (
        <>
          <Line tone="muted">
            {countOf(table.totalRows, "row", "rows")} × {countOf(table.columns.length, "column", "columns")} · {kind}
          </Line>
          {table.columns.length > 0 ? (
            <Table columns={table.columns} dtypes={table.dtypes} rows={table.rows} maxRows={PREVIEW_ROWS} />
          ) : null}
        </>
      ),
      foot: left ? [left] : [],
    };
  }
  if (preview.kind === "tuple") {
    const names = Array.from({ length: preview.size }, (_, i) => `${name}[${i}]`);
    const holds = `A tuple of ${countOf(preview.size, "value", "values")}.`;
    return {
      body: (
        <>
          <Line>{language === "json" ? holds : `${holds} Read them in code as ${inWords(names)}.`}</Line>
          {preview.parts.slice(0, SHOWN_PARTS).map((part, i) =>
            "table" in part ? (
              <Table
                key={i}
                caption={`${name}[${i}] · ${countOf(part.table.totalRows, "row", "rows")} × ${countOf(part.table.columns.length, "column", "columns")}`}
                columns={part.table.columns}
                dtypes={part.table.dtypes}
                rows={part.table.rows}
                maxRows={PART_ROWS}
              />
            ) : (
              <Line key={i} tone="mono">
                {name}[{i}] = <Cell value={part.value} limit={VALUE_CHARS} />
              </Line>
            ),
          )}
        </>
      ),
      foot: preview.parts.length > SHOWN_PARTS ? [`first ${SHOWN_PARTS} of ${count(preview.size)} values`] : [],
    };
  }
  if (preview.kind === "layers") {
    return {
      body: (
        <>
          <Line>{countOf(preview.layers.length, "layer", "layers")}</Line>
          {preview.layers.slice(0, SHOWN_PARTS).map(({ name: layer, table }) => (
            <Table
              key={layer}
              caption={`${layer} · ${countOf(table.totalRows, "feature", "features")}${table.geometryType ? `, ${table.geometryType}` : ""}`}
              columns={table.columns}
              dtypes={table.dtypes}
              rows={table.rows}
              maxRows={PART_ROWS}
            />
          ))}
        </>
      ),
      foot: preview.layers.length > SHOWN_PARTS ? [`first ${SHOWN_PARTS} of ${count(preview.layers.length)} layers`] : [],
    };
  }
  if (preview.kind === "value") {
    return {
      body: (
        <Line>
          {VALUE_WORDS[preview.dataType] ?? "A value"}:{" "}
          <span className={styles.mono}>
            <Cell value={preview.value} limit={VALUE_CHARS} />
          </span>
        </Line>
      ),
      foot: [],
    };
  }
  if (preview.kind === "json") {
    const word = preview.shape === "list" ? "items" : "keys";
    return {
      body: (
        <>
          <Line>
            {preview.shape === "list" ? `A list of ${countOf(preview.total, "item", "items")}` : `A dict of ${countOf(preview.total, "key", "keys")}`}
          </Line>
          {preview.items.map(({ key, value }) => (
            <Line key={key} tone="mono">
              {key}: <Cell value={value} limit={VALUE_CHARS} />
            </Line>
          ))}
        </>
      ),
      foot: preview.total > preview.items.length ? [`first ${preview.items.length} of ${count(preview.total)} ${word}`] : [],
    };
  }
  if (preview.kind === "raster") return { body: <Line>A raster</Line>, foot: [] };
  if (preview.kind === "unreadable") return { body: <Line>Curio could not read {name}.</Line>, foot: [] };
  return { body: <Line>It holds no value.</Line>, foot: [] };
}

function inputParts(slot: number | null, scope: ReferenceScope, language: CodeLanguage, data?: ChipPreviewData): Parts {
  const name = inputName(slot);
  const input = scope.inputs.find((i) => i.slot === slot);
  const state = slot === null ? undefined : data?.inputs?.[slot];
  const head = (
    <Head chip={name} chipClass={styles.chipInput}>
      <SourceText input={input} source={state?.source} />
    </Head>
  );
  const waiting = waitingLine(name, state);
  if (waiting || !state?.preview) return { kind: "input", head, body: waiting };
  const { body, foot } = holdingOf(name, state.preview, language);
  return {
    kind: "input",
    head,
    body: (
      <>
        {staleLine(state)}
        {body}
      </>
    ),
    foot,
  };
}

/** The table of *preview* a column or layer chip reads: the one frame it
 * holds, or its layer *layer*. */
function tableFor(preview: InputPreview | undefined, layer?: string): PreviewTable | undefined {
  if (preview?.kind === "frame") return preview.table;
  if (preview?.kind === "layers" && layer !== undefined) return preview.layers.find((one) => one.name === layer)?.table;
  return undefined;
}

function columnParts(
  slot: number | null,
  layer: string | undefined,
  column: string,
  scope: ReferenceScope,
  data?: ChipPreviewData,
): Parts {
  const name = inputName(slot);
  const input = scope.inputs.find((i) => i.slot === slot);
  const state = slot === null ? undefined : data?.inputs?.[slot];
  const table = tableFor(state?.preview, layer);
  const declared = layer !== undefined ? input?.layers?.find((one) => one.name === layer)?.dtypes : input?.dtypes;
  const dtype = table?.dtypes[column] ?? declared?.[column];
  const owner = layer !== undefined ? `layer ${layer}, ${name}` : name;
  const head = (
    <Head chip={column} chipClass={styles.chipColumn}>
      {" "}
      <Text>column of {owner}</Text>
      {dtype ? (
        <>
          {" "}
          <Text muted>· {dtype}</Text>
        </>
      ) : null}
    </Head>
  );
  const waiting = waitingLine(name, state, true);
  if (waiting) return { kind: "column", head, body: waiting };
  if (!table || !table.columns.includes(column)) {
    return { kind: "column", head, body: <Line>{owner} has no column {column}.</Line> };
  }
  const values = table.rows.slice(0, PREVIEW_ROWS).map((row) => row[column]);
  return {
    kind: "column",
    head,
    body: (
      <>
        {staleLine(state)}
        <ValuesLine values={values} more={table.totalRows > values.length} />
        <Line>{summaryText(table.summaries[column] ?? { empty: 0 }, table.readRows, table.totalRows)}</Line>
      </>
    ),
  };
}

function layerParts(slot: number | null, layer: string, data?: ChipPreviewData): Parts {
  const name = inputName(slot);
  const state = slot === null ? undefined : data?.inputs?.[slot];
  const head = (
    <Head chip={layer} chipClass={styles.chipInput}>
      {" "}
      <Text>layer of {name}</Text>
    </Head>
  );
  const waiting = waitingLine(name, state);
  if (waiting) return { kind: "layer", head, body: waiting };
  const table = tableFor(state?.preview, layer);
  if (!table) return { kind: "layer", head, body: <Line>{name} has no layer {layer}.</Line> };
  const shown = Math.min(table.rows.length, PART_ROWS);
  const left = cutText(table.totalRows, shown, table.columns.length, "columns");
  return {
    kind: "layer",
    head,
    body: (
      <>
        {staleLine(state)}
        <Line tone="muted">
          {countOf(table.totalRows, "feature", "features")}
          {table.geometryType ? ` · ${table.geometryType}` : ""}
        </Line>
        {table.columns.length > 0 ? (
          <Table columns={table.columns} dtypes={table.dtypes} rows={table.rows} maxRows={PART_ROWS} />
        ) : null}
      </>
    ),
    foot: left ? [left] : [],
  };
}

/** The stacked `inputs`, as far as what has been read lets it be built. */
type Stacked =
  | { lines: string[] }
  | {
      stale: string[];
      fields: string[];
      dtypes: Record<string, string>;
      rows: Row[];
      totalRows: number;
      readRows: number;
      colors: Record<string, string>;
      summaryOf: (field: string) => ColumnSummary;
    };

/** One input as the stacking reads it: its rows, as the preview kept them. */
function stackValueOf(preview: InputPreview): unknown {
  const rowsOf = (table: PreviewTable) => {
    // A GeoDataFrame's rows leave its geometry out, as the stacking does.
    const columns = table.columns.filter((column) => table.dtypes[column] !== "geometry");
    return table.rows.map((row) => Object.fromEntries(columns.map((column) => [column, row[column]])));
  };
  if (preview.kind === "frame") return rowsOf(preview.table);
  if (preview.kind === "layers") {
    return preview.layers.length === 1
      ? rowsOf(preview.layers[0].table)
      : { dataType: "outputs", data: preview.layers.map((layer) => ({ layerName: layer.name })) };
  }
  if (preview.kind === "tuple") return { dataType: "outputs", data: Array.from({ length: preview.size }, () => ({})) };
  if (preview.kind === "value") return preview.value;
  if (preview.kind === "json") {
    return preview.shape === "list"
      ? preview.items.map((item) => item.value)
      : Object.fromEntries(preview.items.map((item) => [item.key, item.value]));
  }
  return null;
}

/** How many rows one input adds to the stack, and how many of them were read. */
function stackSizeOf(preview: InputPreview, rows: number): { total: number; read: number } {
  const table = preview.kind === "frame" ? preview.table : preview.kind === "layers" && preview.layers.length === 1 ? preview.layers[0].table : null;
  if (table) return { total: table.totalRows, read: table.readRows };
  if (preview.kind === "json" && preview.shape === "list") return { total: preview.total, read: rows };
  return { total: rows, read: rows };
}

function stackedOf(scope: ReferenceScope, data?: ChipPreviewData): Stacked {
  const inputs = [...scope.inputs].sort((a, b) => a.slot - b.slot);
  const states = inputs.map((input) => data?.inputs?.[input.slot]);
  const failed = inputs.filter((_, i) => states[i]?.source.status === "errored").map((input) => inputName(input.slot));
  if (failed.length === 1) return { lines: [`The node that feeds ${failed[0]} failed.`] };
  if (failed.length > 1) return { lines: [`The nodes that feed ${inWords(failed)} failed.`] };
  const notRun = unique(states.flatMap((state) => (state?.source.status === "not-run" ? [state.source.title] : [])));
  if (notRun.length > 0) {
    return {
      lines: [`Not run yet. Run ${inWords(notRun)} to see its rows.`, `Its rows begin with ${inWords([...STACKED_FIELDS])}.`],
    };
  }
  const reading = inputs.filter((_, i) => !states[i]?.preview).map((input) => inputName(input.slot));
  if (reading.length > 0) return { lines: [`Reading ${inWords(reading)}...`] };
  const unreadable = inputs.filter((_, i) => states[i]?.preview?.kind === "unreadable").map((input) => inputName(input.slot));
  if (unreadable.length > 0) return { lines: [`Curio could not read ${inWords(unreadable)}.`] };

  const previews = states.map((state) => state?.preview as InputPreview);
  const entries: StackEntry[] = inputs.map((input, i) => ({
    scenario: input.scenario?.scenario ?? null,
    name: input.scenario?.name ?? states[i]?.source.title ?? "",
    value: stackValueOf(previews[i]),
  }));
  const raster = previews.findIndex((preview) => preview.kind === "raster");
  if (raster >= 0) {
    const label = entries[raster].name ? `${inputName(raster)} (${entries[raster].name})` : inputName(raster);
    return { lines: [`The dataset "inputs": ${label} is a raster, which a chart does not read.`] };
  }
  const stacked = stackInputs(entries);
  if ("refusal" in stacked) return { lines: [stacked.refusal] };

  const fields: string[] = [...STACKED_FIELDS];
  const dtypes: Record<string, string> = { ...STACKED_DTYPES };
  const kinds: Record<string, string[]> = {};
  for (const row of stacked.rows) for (const field of Object.keys(row)) if (!fields.includes(field)) fields.push(field);
  previews.forEach((preview) => {
    const table = tableFor(preview, preview.kind === "layers" ? preview.layers[0]?.name : undefined);
    if (!table) return;
    for (const column of table.columns) {
      if (table.dtypes[column] === "geometry") continue;
      if (!fields.includes(column)) fields.push(column);
      const dtype = table.dtypes[column];
      if (dtype && !(kinds[column] ??= []).includes(dtype)) kinds[column].push(dtype);
    }
  });
  for (const [column, names] of Object.entries(kinds)) dtypes[column] = names.join(" or ");

  const sizes = previews.map((preview, i) =>
    stackSizeOf(preview, stacked.rows.filter((row) => row[INPUT_FIELD] === i).length),
  );
  const labels = inputs.map((input) => input.scenario);
  const colors: Record<string, string> = {};
  if (labels.every((label): label is ScenarioLabel => label != null)) {
    const { domain, range } = scenarioColorScale(inputs);
    domain.forEach((name, i) => {
      colors[name] = range[i];
    });
  }
  const summaryOf = (field: string): ColumnSummary => {
    const read = (i: number) => sizes[i].read;
    if (field === SCENARIO_NAME_FIELD) {
      return { empty: 0, distinct: unique(entries.filter((_, i) => read(i) > 0).map((entry) => entry.name)) };
    }
    if (field === SCENARIO_FIELD) {
      const boxed = entries.filter((entry, i) => read(i) > 0 && entry.scenario != null);
      const empty = entries.reduce((sum, entry, i) => sum + (entry.scenario == null ? read(i) : 0), 0);
      return boxed.length > 0 ? { empty, distinct: unique(boxed.map((entry) => entry.scenario as string)) } : { empty };
    }
    if (field === INPUT_FIELD) {
      const circles = entries.map((_, i) => i).filter((i) => read(i) > 0);
      return circles.length > 0 ? { empty: 0, min: Math.min(...circles), max: Math.max(...circles) } : { empty: 0 };
    }
    const parts = previews.map((preview, i): ColumnSummary => {
      const table = tableFor(preview, preview.kind === "layers" ? preview.layers[0]?.name : undefined);
      if (table) return table.columns.includes(field) ? table.summaries[field] ?? { empty: 0 } : { empty: table.readRows };
      return columnSummaryOf(stacked.rows.filter((row) => row[INPUT_FIELD] === i).map((row) => row[field]));
    });
    const empty = parts.reduce((sum, part) => sum + part.empty, 0);
    const held = parts.filter((part) => part.min !== undefined || part.distinct !== undefined);
    if (held.length > 0 && held.every((part) => part.min !== undefined && part.max !== undefined)) {
      return { empty, min: Math.min(...held.map((part) => part.min as number)), max: Math.max(...held.map((part) => part.max as number)) };
    }
    if (held.length > 0) return { empty, distinct: unique(held.flatMap((part) => part.distinct ?? [])) };
    return { empty };
  };
  return {
    stale: unique(states.flatMap((state) => (state?.source.status === "stale" ? [state.source.title] : []))),
    fields,
    dtypes,
    rows: stacked.rows,
    totalRows: sizes.reduce((sum, size) => sum + size.total, 0),
    readRows: sizes.reduce((sum, size) => sum + size.read, 0),
    colors,
    summaryOf,
  };
}

function staleStackLine(titles: string[]): React.ReactNode {
  return titles.length > 0 ? <Line tone="muted">From the last run of {inWords(titles)}, which has changed since</Line> : null;
}

function datasetParts(scope: ReferenceScope, data?: ChipPreviewData): Parts {
  const names = [...scope.inputs].sort((a, b) => a.slot - b.slot).map((input) => inputName(input.slot));
  const stacked = stackedOf(scope, data);
  const built = "fields" in stacked ? stacked : null;
  const head = (
    <Head chip="inputs" chipClass={styles.chipInput}>
      {" "}
      <Text>{inWords(names)}, stacked</Text>
      {built ? (
        <>
          {" "}
          <Text muted>
            · {countOf(built.totalRows, "row", "rows")} × {countOf(built.fields.length, "field", "fields")}
          </Text>
        </>
      ) : null}
    </Head>
  );
  if (!built) {
    const lines = (stacked as { lines: string[] }).lines;
    return { kind: "dataset", head, body: lines.map((line) => <Line key={line}>{line}</Line>) };
  }
  const shown = Math.min(built.rows.length, PREVIEW_ROWS);
  const left = cutText(built.totalRows, shown, built.fields.length, "fields");
  return {
    kind: "dataset",
    head,
    body: (
      <>
        {staleStackLine(built.stale)}
        <Table
          columns={built.fields}
          dtypes={built.dtypes}
          rows={built.rows}
          maxRows={PREVIEW_ROWS}
          swatchOf={(column, value) => (column === SCENARIO_NAME_FIELD ? built.colors[String(value)] : undefined)}
        />
      </>
    ),
    foot: left ? [left] : [],
  };
}

function stackedFieldParts(field: string, scope: ReferenceScope, data?: ChipPreviewData): Parts {
  const stacked = stackedOf(scope, data);
  const built = "fields" in stacked ? stacked : null;
  const dtype = built?.dtypes[field] ?? STACKED_DTYPES[field];
  const head = (
    <Head chip={field} chipClass={styles.chipColumn}>
      {" "}
      <Text>field of inputs</Text>
      {dtype ? (
        <>
          {" "}
          <Text muted>· {dtype}</Text>
        </>
      ) : null}
    </Head>
  );
  if (!built) {
    const lines = (stacked as { lines: string[] }).lines;
    return { kind: "stacked", head, body: lines.map((line) => <Line key={line}>{line}</Line>) };
  }
  if (!built.fields.includes(field)) return { kind: "stacked", head, body: <Line>The dataset inputs has no field {field}.</Line> };
  const values = built.rows.slice(0, PREVIEW_ROWS).map((row) => row[field]);
  return {
    kind: "stacked",
    head,
    body: (
      <>
        {staleStackLine(built.stale)}
        <ValuesLine
          values={values}
          more={built.totalRows > values.length}
          swatchOf={field === SCENARIO_NAME_FIELD ? (value) => built.colors[String(value)] : undefined}
        />
        <Line>{summaryText(built.summaryOf(field), built.readRows, built.totalRows)}</Line>
      </>
    ),
  };
}

/** A widget's value as its control shows it. */
function widgetValueText(value: WidgetValue | undefined, units?: string): string {
  if (value === null || value === undefined) return "none";
  if (typeof value === "number") return units ? `${formatNumber(value)} ${units}` : formatNumber(value);
  if (typeof value === "string") return cut(value, VALUE_CHARS);
  if (typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return cut((value as Array<string | number>).map((item) => textOfValue(item)).join(", "), VALUE_CHARS);
  return `${formatNumber(value.lat)}, ${formatNumber(value.lon)}`;
}

/** A number widget's bounds and step: "Range 1 to 20, step 1". */
function rangeText(options: WidgetDef["options"]): string | null {
  const min = options?.min;
  const max = options?.max;
  const bounds =
    min !== undefined && max !== undefined
      ? `Range ${formatNumber(min)} to ${formatNumber(max)}`
      : min !== undefined
        ? `From ${formatNumber(min)}`
        : max !== undefined
          ? `Up to ${formatNumber(max)}`
          : null;
  const step = options?.step !== undefined ? `step ${formatNumber(options.step)}` : null;
  if (bounds && step) return `${bounds}, ${step}`;
  return bounds ?? (step ? `Step ${formatNumber(options?.step as number)}` : null);
}

/** A widget's control and value, its choices or range, and what its chip writes. */
function widgetLines(widget: WidgetDef, language: CodeLanguage): React.ReactNode {
  const value = effectiveValue(widget);
  const control = WIDGET_KIND_LABELS[widget.type] ?? widget.type;
  const choices = CHOICE_KINDS.includes(widget.type) ? widget.options?.choices ?? [] : [];
  const range = NUMERIC_KINDS.includes(widget.type) ? rangeText(widget.options) : null;
  return (
    <>
      <Line>
        {control}: {widgetValueText(value, widget.options?.units)}
      </Line>
      {choices.length > 0 ? <Line tone="muted">Choices: {choices.join(", ")}</Line> : null}
      {range ? <Line tone="muted">{range}</Line> : null}
      <Line tone="mono">writes {widgetLiteral(value, language)}</Line>
    </>
  );
}

function widgetParts(name: string, scope: ReferenceScope, language: CodeLanguage): Parts {
  const widget = scope.widgets.find((w) => w.name === name);
  const control = widget ? WIDGET_KIND_LABELS[widget.type] ?? widget.type : null;
  const head = (
    <Head chip={name} chipClass={styles.chipWidget}>
      {control ? (
        <>
          {" "}
          <Text muted>
            {articleOf(control)} {control} widget
          </Text>
        </>
      ) : null}
    </Head>
  );
  if (!widget) return { kind: "widget", head, body: <Line>This node has no widget named {name}.</Line> };
  return { kind: "widget", head, body: widgetLines(widget, language) };
}

function sharedParts(inner: string, name: string, scope: ReferenceScope, language: CodeLanguage, data?: ChipPreviewData): Parts {
  const widget = scope.shared.find((w) => w.name === name);
  const parameter = data?.parameters?.[name];
  const head = (
    <Head chip={inner} chipClass={styles.chipShared}>
      {" "}
      <Text>{parameter ? `from the Parameter node ${parameter.node}` : "from its Parameter node"}</Text>
    </Head>
  );
  if (!widget) return { kind: "shared", head, body: <Line>No Parameter node holds a widget named {name}.</Line> };
  return {
    kind: "shared",
    head,
    body: (
      <>
        {widgetLines(widget, language)}
        {parameter ? <Line>Read by {countOf(parameter.readers, "node", "nodes")}</Line> : null}
      </>
    ),
  };
}

function selectionParts(inner: string, name: string, scope: ReferenceScope, data?: ChipPreviewData): Parts {
  const tag = (scope.selections ?? []).find((t) => t.name === name);
  const view = data?.selections?.[name];
  const head = (
    <Head chip={inner} chipClass={styles.chipSelection}>
      {" "}
      <Text>{view ? `from the view ${view.view}` : "from its view"}</Text>
    </Head>
  );
  if (!tag) return { kind: "selection", head, body: <Line>This node has no selection tag named {name}.</Line> };
  const ids = Array.isArray(tag.ids) ? tag.ids : null;
  const size = ids ? ids.length : tag.count ?? 0;
  const rows = view?.rows;
  return {
    kind: "selection",
    head,
    body: (
      <>
        <Line>{countOf(size, `${tag.column} value`, `${tag.column} values`)} selected</Line>
        {ids && ids.length > 0 ? (
          <Line tone="mono">
            {ids.slice(0, SHOWN_IDS).map((id) => cut(textOfValue(id), CELL_CHARS)).join(", ")}
            {ids.length > SHOWN_IDS ? ", ..." : ""}
          </Line>
        ) : null}
        {rows && rows.rows.length > 0 ? (
          <Table columns={rows.columns} dtypes={{}} rows={rows.rows} maxRows={PART_ROWS} />
        ) : rows ? null : (
          <Line tone="muted">The selected rows show once {view?.view ?? "its view"} has drawn.</Line>
        )}
      </>
    ),
  };
}

function scenarioParts(
  inner: string,
  parsed: Extract<ParsedReference, { kind: "scenario" }>,
  scope: ReferenceScope,
): Parts {
  const chip = (text: string | null, body: React.ReactNode): Parts => ({
    kind: "scenario",
    head: (
      <Head chip={inner} chipClass={styles.chipScenario}>
        {text ? (
          <>
            {" "}
            <Text>{text}</Text>
          </>
        ) : null}
      </Head>
    ),
    body,
  });
  const labels = scope.inputs.map((input) => input.scenario);
  if (parsed.chip === null || labels.some((label) => label == null)) {
    return chip(null, <Line>The scenario boxes of this node's inputs are not known here.</Line>);
  }
  const fromBox = anyFromABox(labels as ScenarioLabel[]);
  const writes = <Line tone="mono">writes {resolveReferences(referenceText(inner), scope, "json").code}</Line>;
  const entry = (name: string, color: string | null, hex = true) => (
    <Line key={name}>
      {color ? <Swatch color={color} /> : null}
      {name}
      {color && hex ? (
        <>
          {" "}
          <span className={styles.mono}>{color}</span>
        </>
      ) : null}
    </Line>
  );
  if (parsed.chip === "input") {
    const slot = parsed.slot as number;
    const label = scope.inputs.find((input) => input.slot === slot)?.scenario as ScenarioLabel;
    const color = scenarioInputColor(slot, scope.inputs);
    const boxed = label.scenario != null;
    return chip(
      boxed ? `the color of ${label.name}` : `the gray of ${inputName(slot)}`,
      <>
        {entry(label.name, color)}
        <Line tone="muted">{boxed ? `the box ${inputName(slot)} comes from` : `${inputName(slot)} comes from no scenario box`}</Line>
        {writes}
      </>,
    );
  }
  const { domain, range } = scenarioColorScale(scope.inputs);
  if (parsed.chip === "order") {
    return chip(
      "the names in order",
      <>
        {domain.map((name, i) => entry(name, range[i], false))}
        {writes}
      </>,
    );
  }
  const shades = parsed.chip === "text_colors" ? range.map(tableTextColor) : range;
  const what = parsed.chip === "text_colors" ? "a color scale for a text mark" : "a color scale";
  return chip(
    fromBox ? what : "no input of this node comes from a scenario box",
    <>
      {domain.map((name, i) => entry(name, fromBox ? shades[i] : null))}
      {writes}
    </>,
  );
}

/** The text of the chip a preview's head shows: what the header's tag reads. */
function chipTextOf(parsed: ParsedReference, inner: string): string {
  if (parsed.kind === "input") return parsed.column ?? parsed.layer ?? inputName(parsed.slot);
  if (parsed.kind === "stacked") return parsed.column;
  if (parsed.kind === "dataset") return "inputs";
  return inner;
}

function partsOf({ inner, scope, language, data, problem }: ChipPreviewProps): Parts {
  const parsed = parseReference(inner);
  if (problem) {
    return {
      kind: "problem",
      head: <Head chip={chipTextOf(parsed, inner)} chipClass={styles.chipProblem} />,
      body: <Line tone="problem">{problem}</Line>,
    };
  }
  switch (parsed.kind) {
    case "input":
      if (parsed.column !== undefined) return columnParts(parsed.slot, parsed.layer, parsed.column, scope, data);
      if (parsed.layer !== undefined) return layerParts(parsed.slot, parsed.layer, data);
      return inputParts(parsed.slot, scope, language, data);
    case "dataset":
      return datasetParts(scope, data);
    case "stacked":
      return stackedFieldParts(parsed.column, scope, data);
    case "widget":
      return widgetParts(parsed.name, scope, language);
    case "shared":
      return sharedParts(inner, parsed.name, scope, language, data);
    case "selection":
      return selectionParts(inner, parsed.name, scope, data);
    case "scenario":
      return scenarioParts(inner, parsed, scope);
  }
}

/** What the chip *inner* holds, as its hover shows it. */
export function ChipPreview(props: ChipPreviewProps) {
  const parts = partsOf(props);
  return (
    <div className={styles.preview} data-chip-preview={parts.kind}>
      {parts.head}
      {parts.body}
      {(parts.foot ?? []).map((text) => (
        <div key={text} className={styles.foot} data-preview-foot="true">
          {text}
        </div>
      ))}
      {props.tag ? (
        <div className={styles.foot} data-preview-foot="true">
          {TAG_HOW}
        </div>
      ) : null}
    </div>
  );
}

/**
 * A chip's preview in the one Curio tooltip, for a header tag or a chip in an
 * editor: it follows its node's *source* as reads come back, and asks it to
 * read what the chip shows as it mounts, which is when the tooltip first
 * shows. *messages* come first: the markers' at an editor's chip (a JSON
 * error), as Monaco's hover put them.
 */
export function ChipPreviewTip({
  source,
  inner,
  problem,
  tag,
  messages,
}: {
  source: ChipPreviewSource;
  inner: string;
  problem?: string | null;
  tag?: boolean;
  messages?: string[];
}) {
  const { scope, language, data } = useSyncExternalStore(source.subscribe, source.get, source.get);
  useEffect(() => {
    if (!problem) source.load(inner);
  }, [source, inner, problem]);
  const preview = (
    <ChipPreview inner={inner} scope={scope} language={language} data={data} problem={problem} tag={tag} />
  );
  if (!messages || messages.length === 0) return preview;
  return (
    <div className={styles.tip}>
      {messages.map((message, index) => (
        <div key={index} className={styles.message} data-preview-message="true">
          {message}
        </div>
      ))}
      {preview}
    </div>
  );
}

export default ChipPreview;
