/**
 * A node's references in its code (#662): chips dragged in from the strip
 * above its editor and stored as plain `[!! ... !!]` text.
 *
 * - `[!! season !!]` names one of the node's widgets;
 * - `[!! input_1 !!]` names one of its inputs, by circle, counted from 0;
 * - `[!! input_1.height !!]` names a column of that input;
 * - `[!! input_1:roads !!]` names a layer an input carries (an Autark node's
 *   tables), and `[!! input_1:roads.height !!]` a column of that layer;
 * - `[!! @season !!]` names a shared tag: the widget of the dataflow's
 *   Parameter node named `season`;
 * - `[!! selection picked !!]` names one of the node's selection tags: the ids
 *   of the rows a view's selection picks (`selectionTags.ts`);
 * - in a Vega-Lite or Autark spec, the scenario chips write the scenarios of the
 *   node's inputs, from the label each input's rows carry (`InputScope.scenario`:
 *   the box its feeding node is in, else that node's name):
 *   `[!! scenario colors !!]` the scale `{"domain": [names], "range": [colors]}`,
 *   each box once in the order the dataflow lists the boxes, in its color, then
 *   each input from no box, in a grey of its own; `[!! scenario text_colors !!]`
 *   the same scale in the shades a text mark reads in (`tableTextColor`);
 *   `[!! scenario order !!]` the names alone; and `[!! scenario input_1 !!]` the
 *   color of input_1 in that scale. With no input from a box, the two scales
 *   are the names alone, `{"domain": [names]}`, which the grammar's own palette
 *   colors;
 * - `[!! inputs !!]` names the dataset `inputs`, which stacks a Vega-Lite
 *   chart's inputs (`utils/scenarios/stackedInputs`): a spec writes its name,
 *   `"data": {"name": "[!! inputs !!]"}` reading `"data": {"name": "inputs"}`.
 *   It is refused in code, and on a node with no input, which has nothing to
 *   stack. An Autark spec, which stacks nothing, writes the name too;
 * - `[!! inputs.sunlight !!]` names a field of that dataset.
 *
 * A widget's name has no space and no dot, and an input's chip starts
 * `input_`, so neither `scenario colors` nor `inputs.sunlight` can name a
 * widget, an input or a column: `scenario_colors` would be a widget's name,
 * and `input_1.scenario_color` a column of input_1. No widget takes the name
 * `inputs` (`INPUT_NAME_ONLY_PATTERN` in `widgetModel.ts`), and beside one
 * saved under it `[!! inputs !!]` names the dataset.
 *
 * The browser (NodeEditor, before a run) and the headless runner
 * (`utk_curio/backend/app/execution/code_references.py`) must write the same
 * code, so both are pinned to one table of cases, `codeReferences.cases.json`,
 * read by Jest and by pytest.
 *
 * A widget, shared or selection reference standing on its own becomes a literal
 * of the editor's language: quoted text, a number, a list, a boolean (a
 * selection's ids are a list). Inside a string literal
 * it becomes the value's text, escaped for that string, so
 * `"Season: [!! season !!]"` reads `"Season: winter"`. Inside a comment it is
 * the plain text. A column reference is written the same way as a text value:
 * its name. In a Vega-Lite chart's spec, a reference where Vega-Lite reads a
 * field name (`vegaFieldPlaces`) writes each name it holds escaped for
 * Vega-Lite (`vegaFieldName`), since Vega-Lite reads a `.` or a `[` in a field
 * as a path into the row: `"field": [!! input_0.rain.mm !!]` reads
 * `"field": "rain\\.mm"`. Anywhere else in it, a title, a sort or an
 * expression, the name is written as it is. In Python and JavaScript an input reference becomes the name the
 * code reads that circle's input by, `input_<circle>` (the sandbox binds one
 * variable per wired circle, `util/input_names.py`), and a layer reference the
 * call that picks the layer out of it, `curio_layer(input_1, "roads", 1)` (the
 * sandbox's `util/input_layers.py`, and `js_wrapper.mjs`). In a Vega-Lite or
 * Autark spec an input reference is the name that input is read by,
 * `input_<i>`, and a layer reference the layer's name, written like a text
 * value too. An input of one frame with no layer name is that layer, whatever
 * the reference names, in a spec as in code: there its layer reference is
 * `input_<i>` too. One frame whose value names its layer is found by that name.
 *
 * A chip spelled the old way, `[!! input 1 !!]`, is refused with a message
 * naming its new spelling.
 */

import { WIDGET_NAME_RE, effectiveValue, type WidgetDef, type WidgetValue } from "../widgets/widgetModel";
import { inputTableName } from "../../generated/autkGrammar";
import { vegaFieldName } from "../vegaFieldNames";
import { isOverCap, overCapText, selectionSize, type SelectionTag } from "./selectionTags";
import {
  SCENARIO_FIELD,
  SCENARIO_NAME_FIELD,
  anyFromABox,
  scaleLabels,
  scenarioScale,
  tableTextColor,
  type ScenarioLabel,
} from "../scenarios/scenarioColors";
import { INPUT_FIELD } from "../scenarios/stackedInputs";
import { INPUTS_DATASET } from "../vegaDatasets";

export type CodeLanguage = "python" | "javascript" | "json";

/** A reference as written: `[!! ... !!]`. Kept in sync with `REFERENCE_RE`
 * in `code_references.py`. */
export const REFERENCE_PATTERN = String.raw`\[!!\s*(.*?)\s*!!\]`;

/** What stands inside an input, layer or column reference: `input_1`,
 * `input_1.height`, `input_1:roads`, `input_1:roads.height`, or `input_?`
 * once its edge was deleted. A layer name holds no dot; a column name is all
 * the text after the first one. Kept in sync with `INPUT_REFERENCE_RE` in
 * `code_references.py`. */
export const INPUT_REFERENCE_PATTERN = String.raw`^input_(\d+|\?)(?::([^.]+))?(?:\.(.+))?$`;
const INPUT_REFERENCE_RE = new RegExp(INPUT_REFERENCE_PATTERN);

/** What stood inside an input reference before, `input 1` with a space,
 * refused naming its new spelling. Kept in sync with
 * `LEGACY_INPUT_REFERENCE_RE` in `code_references.py` and the sandbox's
 * `util/input_names.py`. */
export const LEGACY_INPUT_REFERENCE_PATTERN = String.raw`^input\s+(\d+|\?)((?:[:.].*)?)$`;
const LEGACY_INPUT_REFERENCE_RE = new RegExp(LEGACY_INPUT_REFERENCE_PATTERN);

/** An input named in code by typing its name, `input_1`: a name of its own,
 * not a member (`x.input_1`) and not part of a longer one. */
export const INPUT_NAME_PATTERN = String.raw`(?<![\w.$])input_(\d+)(?![\w$])`;

/** The name an input is read by, `input_1`, or `input_?` for one whose edge
 * was deleted. */
export function inputName(slot: number | null): string {
  return `input_${slot === null ? "?" : slot}`;
}

/** What a shared reference starts with: `[!! @season !!]`. Kept in sync with
 * `SHARED_PREFIX` in `code_references.py`. */
export const SHARED_PREFIX = "@";

/** What stands inside a selection reference: `selection picked`. Kept in sync
 * with `SELECTION_REFERENCE_RE` in `code_references.py`. */
export const SELECTION_REFERENCE_PATTERN = String.raw`^selection\s+(.+)$`;
const SELECTION_REFERENCE_RE = new RegExp(SELECTION_REFERENCE_PATTERN);

/** What stands inside a scenario chip: `scenario colors`, `scenario
 * text_colors`, `scenario order`, or `scenario input_1` (`scenario input_?`
 * once its edge was deleted). Kept in sync with `SCENARIO_REFERENCE_RE` in
 * `code_references.py`. */
export const SCENARIO_REFERENCE_PATTERN = String.raw`^scenario\s+(.+)$`;
const SCENARIO_REFERENCE_RE = new RegExp(SCENARIO_REFERENCE_PATTERN);

/** The scenario chips that list every input's scenario: the scale of their
 * colors, the same scale in text shades, and their names in order. */
export const SCENARIO_LISTS = ["colors", "text_colors", "order"] as const;
export type ScenarioList = (typeof SCENARIO_LISTS)[number];

/** What follows `scenario` in an input's scenario chip. */
const SCENARIO_INPUT_RE = /^input_(\d+|\?)$/;

/** What stands inside a chip of a field of the dataset `inputs`:
 * `inputs.sunlight`. Kept in sync with `STACKED_REFERENCE_RE` in
 * `code_references.py`. */
export const STACKED_REFERENCE_PATTERN = String.raw`^inputs\.(.+)$`;
const STACKED_REFERENCE_RE = new RegExp(STACKED_REFERENCE_PATTERN);

/** The fields the stacking adds to every row of `inputs`, before the inputs'
 * own columns: the label's name and id, and the circle. Kept in sync with
 * `STACKED_FIELDS` in `code_references.py`. */
export const STACKED_FIELDS = [SCENARIO_NAME_FIELD, SCENARIO_FIELD, INPUT_FIELD] as const;

/** What a layer reference in Python or JavaScript calls. Kept in sync with
 * `LAYER_HELPER` in `code_references.py` and the sandbox's
 * `util/input_layers.py`. */
export const LAYER_HELPER = "curio_layer";

/** The data types of an input that is one frame: a table, as `curio_layer`
 * counts one. Kept in sync with `ONE_FRAME_TYPES` in `code_references.py`. */
const ONE_FRAME_TYPES = new Set(["dataframe", "geodataframe"]);

/** The grammar of a Vega-Lite chart's spec, as a template names it
 * (`grammarId`): a JSON document of it writes a name where Vega-Lite reads a
 * field escaped. Kept in sync with `VEGA_LITE` in `code_references.py`. */
export const VEGA_LITE = "vega-lite";

export interface CodeReference {
  /** Offsets of the whole `[!! ... !!]` in the code. */
  start: number;
  end: number;
  /** What stands between the brackets, trimmed. */
  inner: string;
}

export interface ReferenceProblem {
  reference: string;
  message: string;
}

/** One of the node's wired inputs. */
export interface InputScope {
  /** Its circle, counted from 0. */
  slot: number;
  /** The node that feeds it, shown on its tag and in its chips' hover. */
  label?: string;
  /** Its data type, once it has arrived. */
  dataType?: string;
  /** Its column names, once known. Absent or null before: a column chip is
   * then not checked against them. */
  columns?: string[] | null;
  /** Each column's dtype, when the input names them. */
  dtypes?: Record<string, string>;
  /** The layers it carries, once known, when it carries several (an Autark
   * node's tables). */
  layers?: LayerScope[] | null;
  /** How many values it holds, once known, when it is a tuple: several frames
   * with no names, as a Python node's `return a, b` gives. */
  tuple?: number;
  /** The layer name of the one frame it carries, when its value names the
   * table it is read as (`layerName`, on a reference or an envelope): known
   * before the input is read. */
  layerName?: string;
  /** The label its rows carry, which the scenario chips write: the id, name,
   * color and rank of the box its feeding node is in, else that node's name in
   * `NO_SCENARIO_COLOR` (utils/scenarios/inputScenarios). Absent when it is
   * not known here, and a scenario chip that needs it says so. */
  scenario?: ScenarioLabel;
}

/** One layer an input carries. */
export interface LayerScope {
  name: string;
  columns?: string[] | null;
  dtypes?: Record<string, string>;
}

/** What a node's references can name: its widgets, its wired inputs, the
 * dataflow's shared tags, and its selection tags. */
export interface ReferenceScope {
  widgets: WidgetDef[];
  /** In circle order. */
  inputs: InputScope[];
  /** The widget of each Parameter node in the dataflow, one per node. Two
   * nodes with one name are both listed, so a reference to it says so. */
  shared: WidgetDef[];
  /** The node's selection tags, with the ids each holds. None when absent. */
  selections?: SelectionTag[];
}

export type ParsedReference =
  | { kind: "widget"; name: string }
  /** `slot` is null for `input_?`, the input whose edge was deleted. */
  | { kind: "input"; slot: number | null; layer?: string; column?: string }
  | { kind: "shared"; name: string }
  | { kind: "selection"; name: string }
  /** `chip` is null for a word no scenario chip is. */
  | { kind: "scenario"; chip: ScenarioList | null }
  /** `slot` is null for `scenario input_?`, the input whose edge was deleted. */
  | { kind: "scenario"; chip: "input"; slot: number | null }
  /** The dataset `inputs` itself, `[!! inputs !!]`. */
  | { kind: "dataset" }
  | { kind: "stacked"; column: string };

export type ReferenceContext = { kind: "code" } | { kind: "comment" } | { kind: "string"; quote: string };

/** What follows `scenario ` in a scenario chip, as the chip it names. */
function parseScenarioChip(rest: string): ParsedReference {
  if ((SCENARIO_LISTS as readonly string[]).includes(rest)) return { kind: "scenario", chip: rest as ScenarioList };
  const input = SCENARIO_INPUT_RE.exec(rest);
  if (input) return { kind: "scenario", chip: "input", slot: input[1] === "?" ? null : Number(input[1]) };
  return { kind: "scenario", chip: null };
}

export function parseReference(inner: string): ParsedReference {
  const m = INPUT_REFERENCE_RE.exec(inner);
  if (!m) {
    const selection = SELECTION_REFERENCE_RE.exec(inner);
    if (selection) return { kind: "selection", name: selection[1] };
    const scenario = SCENARIO_REFERENCE_RE.exec(inner);
    if (scenario) return parseScenarioChip(scenario[1]);
    const stacked = STACKED_REFERENCE_RE.exec(inner);
    if (stacked) return { kind: "stacked", column: stacked[1] };
    if (inner === INPUTS_DATASET) return { kind: "dataset" };
    if (inner.startsWith(SHARED_PREFIX)) return { kind: "shared", name: inner.slice(SHARED_PREFIX.length) };
    return { kind: "widget", name: inner };
  }
  const parsed: ParsedReference = { kind: "input", slot: m[1] === "?" ? null : Number(m[1]) };
  if (m[2] !== undefined) parsed.layer = m[2];
  if (m[3] !== undefined) parsed.column = m[3];
  return parsed;
}

/** The text of a reference to *inner*. */
export function referenceText(inner: string): string {
  return `[!! ${inner} !!]`;
}

/** What stands inside a reference to input *slot*, to one of its layers, or to
 * a column of either. */
export function inputReferenceInner(slot: number | null, column?: string, layer?: string): string {
  return (
    inputName(slot)
    + (layer !== undefined ? `:${layer}` : "")
    + (column !== undefined ? `.${column}` : "")
  );
}

/** Why *reference*, whose inside is *inner*, is refused when it names an input
 * the old way, `input 1` with a space, naming its new spelling; else null.
 * Kept in sync with `legacy_reference_message` in `code_references.py` and
 * the sandbox's `util/input_names.py`. */
export function legacyReferenceMessage(reference: string, inner: string): string | null {
  const m = LEGACY_INPUT_REFERENCE_RE.exec(inner);
  if (!m) return null;
  return (
    `${reference} names an input the old way, which Curio no longer reads. `
    + `Write ${referenceText(`input_${m[1]}${m[2]}`)}: each input circle is its own variable, input_0, input_1, and so on.`
  );
}

/** What stands inside a reference to the shared tag *name*. */
export function sharedReferenceInner(name: string): string {
  return SHARED_PREFIX + name;
}

/** What stands inside a reference to the selection tag *name*. */
export function selectionReferenceInner(name: string): string {
  return `selection ${name}`;
}

/** What stands inside the scenario chip *chip*: `scenario colors`. */
export function scenarioReferenceInner(chip: ScenarioList): string {
  return `scenario ${chip}`;
}

/** What stands inside the scenario chip of input *slot*: `scenario input_1`,
 * or `scenario input_?` for one whose edge was deleted. */
export function scenarioInputReferenceInner(slot: number | null): string {
  return `scenario ${inputName(slot)}`;
}

/** What stands inside a chip of the field *column* of the dataset `inputs`. */
export function stackedReferenceInner(column: string): string {
  return `inputs.${column}`;
}

/** The data types of a frame the stacking reads as a table, its rows' columns
 * known from its own. Kept in sync with `TABLE_TYPES` in `code_references.py`. */
const TABLE_TYPES = new Set(["dataframe", "geodataframe"]);

/** *input*'s columns as the rows of `inputs` carry them: a GeoDataFrame's
 * geometry is left out, as the stacking leaves it out. */
function stackedColumnsOf(input: InputScope): string[] {
  return (input.columns ?? []).filter((column) => input.dtypes?.[column] !== "geometry");
}

/**
 * The fields of the dataset `inputs` that *inputs* are known to give: the three
 * the stacking adds, then each column of an input whose columns are known, once
 * each, in circle order. Its fields' dtypes are its inputs', each column's
 * distinct ones listed. The `inputs` tag lists these.
 */
export function stackedFields(inputs: readonly InputScope[]): { fields: string[]; dtypes: Record<string, string> } {
  const fields: string[] = [...STACKED_FIELDS];
  const seen: Record<string, string[]> = {};
  for (const input of inputs) {
    if (Array.isArray(input.layers) && input.layers.length > 0) continue;
    for (const column of stackedColumnsOf(input)) {
      if (!fields.includes(column)) fields.push(column);
      const dtype = input.dtypes?.[column];
      if (dtype && !(seen[column] ??= []).includes(dtype)) seen[column].push(dtype);
    }
  }
  const dtypes: Record<string, string> = {};
  for (const [column, kinds] of Object.entries(seen)) dtypes[column] = kinds.join(" or ");
  return { fields, dtypes };
}

/**
 * Every field of the dataset `inputs`, when every input is a table whose
 * columns are known: then a field chip must name one of them. Null otherwise,
 * and a field chip is not checked. Kept in sync with `_known_stacked_fields` in
 * `code_references.py`.
 */
function knownStackedFields(inputs: readonly InputScope[]): string[] | null {
  const known = inputs.every(
    (input) => TABLE_TYPES.has(input.dataType ?? "") && Array.isArray(input.columns) && !Array.isArray(input.layers),
  );
  return known ? stackedFields(inputs).fields : null;
}

/** The first of *inputs* whose scenario label is not known, or undefined. */
const unlabelled = (inputs: readonly InputScope[]) => inputs.find((input) => input.scenario == null);

/** The labels of *inputs*, in circle order: each input's must be known. */
const labelsOf = (inputs: readonly InputScope[]): ScenarioLabel[] =>
  [...inputs].sort((a, b) => a.slot - b.slot).map((input) => input.scenario as ScenarioLabel);

/**
 * The scenarios of *inputs*, each input's label known, as the scenario chips
 * write them: each name once, the boxes in the dataflow's order, then each input
 * from no box, with their colors (`scenarioScale`). `[!! scenario colors !!]`
 * writes this scale when an input comes from a box. The header's swatches show
 * it.
 */
export function scenarioColorScale(inputs: readonly InputScope[]): { domain: string[]; range: string[] } {
  return scenarioScale(scaleLabels(labelsOf(inputs)));
}

/**
 * The color `[!! scenario input_<slot> !!]` writes over *inputs*, each input's
 * label known: its box's, else its grey in `scenarioColorScale`. The header's
 * tag of that chip shows it.
 */
export function scenarioInputColor(slot: number, inputs: readonly InputScope[]): string {
  const label = inputs.find((input) => input.slot === slot)?.scenario as ScenarioLabel;
  if (label.scenario != null) return label.color;
  const { domain, range } = scenarioColorScale(inputs);
  return range[domain.indexOf(label.name)];
}

/**
 * What the scenario chip *parsed* (one that resolves) writes over *inputs*: an
 * input's color (its box's, else its grey in the scale), the names in order,
 * or a scale. With no input from a box the scale is the names alone, so the
 * grammar's own palette colors them. Kept in sync with `_scenario_value` in
 * `code_references.py`.
 */
function scenarioValue(parsed: Extract<ParsedReference, { kind: "scenario" }>, inputs: readonly InputScope[]): WidgetValue {
  if (parsed.chip === "input") return scenarioInputColor(parsed.slot as number, inputs);
  const { domain, range } = scenarioColorScale(inputs);
  if (parsed.chip === "order") return domain;
  if (!anyFromABox(labelsOf(inputs))) return { domain } as unknown as WidgetValue;
  const scale = { domain, range: parsed.chip === "text_colors" ? range.map(tableTextColor) : range };
  return scale as unknown as WidgetValue;
}

/** Whether *name* can ride a layer reference and read back as itself. */
export function isReferenceableLayer(name: string): boolean {
  return isReferenceableColumn(name) && !name.includes(".");
}

/** Whether *name* can ride a column reference and read back as itself. */
export function isReferenceableColumn(name: string): boolean {
  return name !== "" && name.trim() === name && !/[\r\n]/.test(name) && !name.includes("!!]");
}

export function findReferences(code: string): CodeReference[] {
  const re = new RegExp(REFERENCE_PATTERN, "g");
  const out: CodeReference[] = [];
  let match: RegExpExecArray | null;
  while ((match = re.exec(code)) !== null) {
    out.push({ start: match.index, end: match.index + match[0].length, inner: match[1] });
  }
  return out;
}

/** Where each reference sits: in code, in a comment, or in a string literal. */
export function referenceContexts(code: string, refs: CodeReference[], language: CodeLanguage): ReferenceContext[] {
  const contexts: ReferenceContext[] = [];
  let state: "code" | "comment" | "block" | "string" = "code";
  let quote = "";
  let i = 0;
  let r = 0;
  const current = (): ReferenceContext =>
    state === "string" ? { kind: "string", quote } : state === "code" ? { kind: "code" } : { kind: "comment" };

  while (i < code.length || r < refs.length) {
    if (r < refs.length && i >= refs[r].start) {
      contexts.push(current());
      i = Math.max(i, refs[r].end);
      r += 1;
      continue;
    }
    if (i >= code.length) break;
    const ch = code[i];
    if (state === "code") {
      if (language === "python" && ch === "#") {
        state = "comment";
      } else if (language === "javascript" && code.startsWith("//", i)) {
        state = "comment";
        i += 2;
        continue;
      } else if (language === "javascript" && code.startsWith("/*", i)) {
        state = "block";
        i += 2;
        continue;
      } else if (ch === '"' || (language !== "json" && (ch === "'" || (language === "javascript" && ch === "`")))) {
        if (language === "python" && code.startsWith(ch.repeat(3), i)) {
          quote = ch.repeat(3);
          state = "string";
          i += 3;
          continue;
        }
        quote = ch;
        state = "string";
      }
    } else if (state === "comment") {
      if (ch === "\n") state = "code";
    } else if (state === "block") {
      if (code.startsWith("*/", i)) {
        state = "code";
        i += 2;
        continue;
      }
    } else {
      if (ch === "\\") {
        i += 2;
        continue;
      }
      if (quote.length === 3) {
        if (code.startsWith(quote, i)) {
          state = "code";
          i += 3;
          continue;
        }
      } else if (ch === quote) {
        state = "code";
      } else if (ch === "\n" && quote !== "`") {
        // An unterminated one-line string ends with its line.
        state = "code";
      }
    }
    i += 1;
  }
  return contexts;
}

/**
 * *spec*, a JSON document, with each chip that stands outside a string held by
 * a string of its own text, so a reader that wants only the document's shape
 * (what an Autark document declares, `utils/autkSpecKind`) can parse it before
 * its chips are resolved: `"color": [!! scenario input_1 !!]` or
 * `"scale": [!! scenario colors !!]` is no JSON until then. A chip inside a
 * string is JSON already and is left as written. Kept in sync with
 * `with_chip_placeholders` in `code_references.py`.
 */
export function withChipPlaceholders(spec: string): string {
  const refs = findReferences(spec);
  if (refs.length === 0) return spec;
  const contexts = referenceContexts(spec, refs, "json");
  let out = "";
  let last = 0;
  refs.forEach((ref, i) => {
    if (contexts[i].kind === "string") return;
    out += spec.slice(last, ref.start) + JSON.stringify(spec.slice(ref.start, ref.end));
    last = ref.end;
  });
  return out + spec.slice(last);
}

/** *value* as a literal of *language*. */
export function widgetLiteral(value: WidgetValue | undefined, language: CodeLanguage): string {
  if (value === null || value === undefined) return language === "python" ? "None" : "null";
  if (typeof value === "boolean") {
    if (language === "python") return value ? "True" : "False";
    return value ? "true" : "false";
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return language === "python" ? "None" : "null";
    return String(value);
  }
  if (typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) {
    return "[" + (value as WidgetValue[]).map((v) => widgetLiteral(v, language)).join(", ") + "]";
  }
  if (typeof value === "object") {
    // A location's {"lat": ..., "lon": ...}: a dict in Python, an object in
    // JavaScript and JSON.
    return (
      "{" +
      Object.entries(value as unknown as Record<string, WidgetValue>)
        .map(([k, v]) => JSON.stringify(k) + ": " + widgetLiteral(v, language))
        .join(", ") +
      "}"
    );
  }
  return JSON.stringify(value);
}

function textOf(value: WidgetValue | undefined, language: CodeLanguage): string {
  return typeof value === "string" ? value : widgetLiteral(value, language);
}

function escapeFor(text: string, context: ReferenceContext, language: CodeLanguage): string {
  if (context.kind === "comment") return text.split("\r\n").join(" ").split("\n").join(" ");
  if (context.kind === "code") return text;
  if (language === "json") return JSON.stringify(text).slice(1, -1);
  const quote = context.quote;
  let out = text.split("\\").join("\\\\");
  if (quote === "`") return out.split("`").join("\\`").split("${").join("\\${");
  if (quote.length === 3) return out.split(quote[0]).join("\\" + quote[0]);
  out = out.split(quote).join("\\" + quote);
  return out.split("\n").join("\\n").split("\r").join("\\r");
}

/** Why *reference* fails: input *slot* has no layer *layer*. It names the
 * layers the input has. The resolver says it when the layers are known, and
 * the sandbox's `curio_layer` says the same of a layer reference when the node
 * runs. Kept in sync with `missing_layer_message` in `code_references.py`. */
export function missingLayerMessage(reference: string, slot: number, layer: string, names: string[]): string {
  const has = names.length > 0 ? `Its layers are ${names.join(", ")}.` : "It carries no named layers.";
  return `${reference}: input_${slot} has no layer ${layer}. ${has}`;
}

/** *text* as a reference standing in *context* writes it. */
function writeText(text: string, context: ReferenceContext, language: CodeLanguage): string {
  return context.kind === "code" ? widgetLiteral(text, language) : escapeFor(text, context, language);
}

/** Where a reference stands in a Vega-Lite spec: whether Vega-Lite reads a
 * text there as a field name (`text`), and, for a reference that is a whole
 * value, whether it reads each text of a list there as one (`items`). */
interface FieldPlace {
  text: boolean;
  items: boolean;
}

/** What an object of a Vega-Lite spec is, where that decides which of its
 * keys hold fields: a transform (an item of `transform`), a lookup's `from`,
 * a parameter (an item of `params`) or its `select`, an encoding's
 * `aggregate`, or a `repeat` mapping. */
type FieldHolder = "transform" | "lookup" | "param" | "select" | "aggregate" | "repeat" | null;

/** The transforms whose own key holds the field they read. */
const TRANSFORM_FIELD_KEYS = new Set(["pivot", "lookup", "impute", "stack", "density", "loess", "regression", "quantile"]);
/** The lists of fields a transform reads. */
const TRANSFORM_FIELD_LISTS = new Set(["groupby", "fold", "flatten"]);

const hasKey = (holder: Record<string, unknown>, key: string) => Object.prototype.hasOwnProperty.call(holder, key);

/**
 * Whether Vega-Lite reads a text at *key* of *holder*, an object that is
 * *kind*, as a field name; *item* for a text that is an item of a list there.
 * The keys Vega-Lite's schema types as a field name, but an output's `as`,
 * which names a new column as it is written; and a transform's `lookup` and a
 * `repeat`'s lists, which Vega-Lite reads as fields too. A key that is a field
 * only in one transform counts in that one: `extent` beside `param`, `value`
 * beside `pivot`, `key` beside `impute`, and `on` beside `loess` or
 * `regression`, where a parameter's `on` is an event. Kept in sync with
 * `_is_vega_field` in `code_references.py`.
 */
function isVegaField(holder: Record<string, unknown>, kind: FieldHolder, key: string, item: boolean): boolean {
  if (item) {
    if (kind === "transform") return TRANSFORM_FIELD_LISTS.has(key);
    if (kind === "lookup" || kind === "select") return key === "fields";
    if (kind === "repeat") return key === "row" || key === "column" || key === "layer";
    return key === "repeat";
  }
  if (key === "field") return true;
  if (kind === "transform") {
    if (TRANSFORM_FIELD_KEYS.has(key)) return true;
    if (key === "extent") return hasKey(holder, "param");
    if (key === "value") return hasKey(holder, "pivot");
    if (key === "key") return hasKey(holder, "impute");
    if (key === "on") return hasKey(holder, "loess") || hasKey(holder, "regression");
    return false;
  }
  if (kind === "lookup") return key === "key";
  if (kind === "aggregate") return key === "argmax" || key === "argmin";
  return false;
}

/** What the object at *key* of *holder*, an object that is *kind*, is; *item*
 * for an object that is an item of a list there. */
function fieldHolderAt(holder: Record<string, unknown>, kind: FieldHolder, key: string, item: boolean): FieldHolder {
  if (item) {
    if (key === "transform") return "transform";
    if (key === "params") return "param";
    return null;
  }
  if (key === "from" && kind === "transform" && hasKey(holder, "lookup")) return "lookup";
  if (key === "select" && kind === "param") return "select";
  if (key === "aggregate") return "aggregate";
  if (key === "repeat") return "repeat";
  return null;
}

/** The keys whose values hold rows or the author's own notes, never a field:
 * a `field` there is a value. Kept in sync with `_NOT_SPEC_KEYS` in
 * `code_references.py`. */
const NOT_SPEC_KEYS = new Set(["data", "datasets", "usermeta"]);

/** How deep a Vega-Lite spec's objects and lists may nest, its rows and notes
 * included, for its places to be read; a deeper spec writes its names as they
 * are. Kept in sync with `_MAX_SPEC_DEPTH` in `code_references.py`. */
const MAX_SPEC_DEPTH = 100;

/** How many objects and lists *spec* nests, itself counted as one, measured
 * without recursion and no further than past *limit*. Kept in sync with
 * `_spec_depth` in `code_references.py`. */
function specDepth(spec: unknown, limit: number): number {
  let deepest = 0;
  const stack: [unknown, number][] = [[spec, 1]];
  while (stack.length > 0) {
    const [node, depth] = stack.pop() as [unknown, number];
    if (node === null || typeof node !== "object") continue;
    if (depth > deepest) deepest = depth;
    if (deepest > limit) break;
    const children = Array.isArray(node) ? node : Object.values(node as Record<string, unknown>);
    for (const child of children) {
      if (child !== null && typeof child === "object") stack.push([child, depth + 1]);
    }
  }
  return deepest;
}

/** The first and last code points of Unicode's private use area. */
const PRIVATE_USE_FIRST = 0xe000;
const PRIVATE_USE_LAST = 0xf8ff;

/**
 * Two characters of Unicode's private use area that *code* holds neither as
 * they are nor as a JSON escape, to stand around a reference's number while
 * the spec is read for its places; null when it holds every pair. Kept in sync
 * with `_place_marks` in `code_references.py`.
 */
function placeMarks(code: string): [string, string] | null {
  const lower = code.toLowerCase();
  const escape = String.fromCharCode(92) + "u";
  const free = (point: number) =>
    !code.includes(String.fromCharCode(point)) && !lower.includes(escape + point.toString(16));
  for (let point = PRIVATE_USE_FIRST; point < PRIVATE_USE_LAST; point += 2) {
    if (free(point) && free(point + 1)) return [String.fromCharCode(point), String.fromCharCode(point + 1)];
  }
  return null;
}

/**
 * Where each of *refs* (in *contexts*) stands in the Vega-Lite spec *code*.
 * The spec is read as JSON with each reference replaced by a mark, its number
 * between two characters the spec's text does not hold (`placeMarks`): a text
 * of its own where the reference is a value, a run of a string where it is
 * inside one. Each mark is found where the spec holds it, outside the rows and
 * notes of `NOT_SPEC_KEYS`. A spec that does not read as JSON, or nests deeper
 * than `MAX_SPEC_DEPTH`, holds no field. Kept in sync with
 * `_vega_field_places` in `code_references.py`.
 */
function vegaFieldPlaces(code: string, refs: CodeReference[], contexts: ReferenceContext[]): FieldPlace[] {
  const unplaced = () => refs.map(() => ({ text: false, items: false }));
  const marks = placeMarks(code);
  if (marks === null) return unplaced();
  const [open, close] = marks;
  const markRe = new RegExp(open + "([0-9]+)" + close, "g");
  let marked = "";
  let last = 0;
  refs.forEach((ref, index) => {
    const mark = open + index + close;
    marked += code.slice(last, ref.start) + (contexts[index].kind === "code" ? `"${mark}"` : mark);
    last = ref.end;
  });
  marked += code.slice(last);
  let spec: unknown;
  try {
    spec = JSON.parse(marked);
  } catch {
    return unplaced();
  }
  if (specDepth(spec, MAX_SPEC_DEPTH) > MAX_SPEC_DEPTH) return unplaced();
  const places = unplaced();
  const place = (text: string, field: boolean, items: boolean) => {
    for (const match of text.matchAll(markRe)) {
      const found = places[Number(match[1])];
      if (found === undefined) continue;
      found.text = field;
      // Only a reference that is the whole value can hold a list.
      found.items = match[0] === text && items;
    }
  };
  // The spec nests no deeper than MAX_SPEC_DEPTH, so neither does this walk.
  const visit = (node: unknown, kind: FieldHolder) => {
    if (Array.isArray(node)) {
      for (const item of node) visit(item, null);
      return;
    }
    if (node === null || typeof node !== "object") return;
    const holder = node as Record<string, unknown>;
    for (const [key, value] of Object.entries(holder)) {
      if (NOT_SPEC_KEYS.has(key)) continue;
      if (typeof value === "string") {
        place(value, isVegaField(holder, kind, key, false), isVegaField(holder, kind, key, true));
      } else if (Array.isArray(value)) {
        for (const item of value) {
          if (typeof item === "string") place(item, isVegaField(holder, kind, key, true), false);
          else if (!Array.isArray(item)) visit(item, fieldHolderAt(holder, kind, key, true));
          else visit(item, null);
        }
      } else {
        visit(value, fieldHolderAt(holder, kind, key, false));
      }
    }
  };
  visit(spec, null);
  return places;
}

/** *value*, a reference's value standing on its own at *place*, as it is
 * written there: a text Vega-Lite reads as a field escaped, and each text of a
 * list whose texts it reads as fields. */
function fieldValue(value: WidgetValue | undefined, place: FieldPlace): WidgetValue | undefined {
  if (typeof value === "string") return place.text ? vegaFieldName(value) : value;
  if (Array.isArray(value) && place.items) {
    return (value as WidgetValue[]).map((item) => (typeof item === "string" ? vegaFieldName(item) : item)) as WidgetValue;
  }
  return value;
}

/**
 * Whether *input* is one frame that lists no layers, which a layer reference
 * reads whatever it names (#761). In code `curio_layer` looks at the value when
 * the node runs. A spec is written before the run, so the input's data type
 * decides, which the input carries before any of its columns is read. Kept in
 * sync with `_is_one_frame_input` in `code_references.py`.
 */
function isOneFrameInput(input: InputScope): boolean {
  return !Array.isArray(input.layers) && ONE_FRAME_TYPES.has(input.dataType ?? "");
}

/**
 * The layers *input* is known to carry, by name: the ones it lists, or the one
 * frame its value names, with the input's columns; null when it names none.
 * A layer reference must name one of them, as `curio_layer` requires. Kept in
 * sync with `_known_layers` in `code_references.py`.
 */
function knownLayers(input: InputScope): LayerScope[] | null {
  if (Array.isArray(input.layers)) return input.layers;
  if (input.layerName !== undefined) {
    return [{ name: input.layerName, columns: input.columns, dtypes: input.dtypes }];
  }
  return null;
}

/** Why the scenario chip *reference* (*parsed*) cannot be written over
 * *inputs*, standing in *context*, or null. Kept in sync with
 * `_scenario_problem` in `code_references.py`. */
function scenarioProblem(
  reference: string,
  parsed: Extract<ParsedReference, { kind: "scenario" }>,
  inputs: readonly InputScope[],
  context: ReferenceContext,
  language: CodeLanguage,
): string | null {
  if (language !== "json") return `${reference} is for a Vega-Lite or Autark spec, not for code.`;
  if (parsed.chip === null) {
    return `${reference} names no scenario chip. The scenario chips are scenario colors, scenario text_colors, `
      + "scenario order and scenario input_<k>.";
  }
  if (parsed.chip === "input") {
    const slot = parsed.slot;
    if (slot === null) {
      return `${reference}: the edge for this input was deleted. Drag the swatch of one of this node's input tags here.`;
    }
    const input = inputs.find((i) => i.slot === slot);
    if (input === undefined) {
      return `${reference}: input_${slot} has no edge. Connect one to that circle, `
        + "or drag the swatch of one of this node's input tags here.";
    }
    if (input.scenario == null) return `${reference}: the scenario box input_${slot} comes from is not known here.`;
    return null;
  }
  if (context.kind !== "code") {
    const what = parsed.chip === "order" ? "a list of names" : "a scale";
    return `${reference} is ${what}, not text. Use it outside quotes.`;
  }
  const unknown = unlabelled(inputs);
  if (unknown) return `${reference}: the scenario box input_${unknown.slot} comes from is not known here.`;
  return null;
}

/** Why the chip of the dataset `inputs`, *reference*, cannot be written over
 * *inputs*, or null: it is for a spec, never for code, and a node with no
 * input has nothing to stack. Kept in sync with `_dataset_problem` in
 * `code_references.py`. */
function datasetProblem(reference: string, inputs: readonly InputScope[], language: CodeLanguage): string | null {
  if (language !== "json") return `${reference} is for a Vega-Lite spec, not for code.`;
  if (inputs.length === 0) return `${reference}: this node has no input to stack. Connect one to an input circle.`;
  return null;
}

/** Why *reference* cannot be resolved in *scope*, standing in *context*, or null. */
export function referenceProblem(
  reference: string,
  inner: string,
  scope: ReferenceScope,
  context: ReferenceContext,
  language: CodeLanguage,
): string | null {
  const legacy = legacyReferenceMessage(reference, inner);
  if (legacy !== null) return legacy;
  const parsed = parseReference(inner);
  if (parsed.kind === "input") {
    if (parsed.slot === null) {
      return `${reference}: the edge for this input was deleted. Drag one of this node's input chips here.`;
    }
    const input = scope.inputs.find((i) => i.slot === parsed.slot);
    if (input === undefined) {
      return `${reference}: input_${parsed.slot} has no edge. Connect one to that circle, or drag one of this node's input chips here.`;
    }
    if (parsed.layer !== undefined) {
      const layers = knownLayers(input);
      const layer = layers?.find((l) => l.name === parsed.layer);
      if (layers !== null && layer === undefined) {
        return missingLayerMessage(reference, parsed.slot, parsed.layer, layers.map((l) => l.name));
      }
      // An input of one frame (no list of layers) is that layer: its columns
      // are the frame's.
      const columns = layer ? layer.columns : layers === null ? input.columns : undefined;
      if (parsed.column !== undefined && Array.isArray(columns) && !columns.includes(parsed.column)) {
        return `${reference}: layer ${parsed.layer} of input_${parsed.slot} has no column ${parsed.column}.`;
      }
      if (parsed.column === undefined && language !== "json" && context.kind !== "code") {
        return `${reference} is an input, not text. Use it outside quotes and comments.`;
      }
      return null;
    }
    if (parsed.column === undefined) {
      if (language === "json") {
        if (Array.isArray(input.layers) && input.layers.length > 1) {
          const names = input.layers.map((l) => l.name).join(", ");
          return `${reference}: input_${parsed.slot} carries several layers (${names}). Drag one of its layer chips here.`;
        }
        return null;
      }
      if (context.kind !== "code") {
        return `${reference} is an input, not text. Use it outside quotes and comments.`;
      }
      return null;
    }
    if (Array.isArray(input.columns) && !input.columns.includes(parsed.column)) {
      return `${reference}: input_${parsed.slot} has no column ${parsed.column}.`;
    }
    return null;
  }
  if (parsed.kind === "shared") {
    if (!WIDGET_NAME_RE.test(parsed.name)) {
      return `${reference} does not name a Parameter node. Parameter names are letters, digits and underscores.`;
    }
    const named = scope.shared.filter((w) => w.name === parsed.name).length;
    if (named === 0) {
      return `${reference}: no Parameter node is named ${parsed.name}. Add one, or drag a tag from Shared.`;
    }
    if (named > 1) {
      return `${reference}: ${named} Parameter nodes are named ${parsed.name}. Rename all but one.`;
    }
    return null;
  }
  if (parsed.kind === "selection") {
    if (!WIDGET_NAME_RE.test(parsed.name)) {
      return `${reference} does not name a selection tag. Selection tag names are letters, digits and underscores.`;
    }
    const tag = (scope.selections ?? []).find((t) => t.name === parsed.name);
    if (tag === undefined) {
      return `${reference}: this node has no selection tag named ${parsed.name}. Add it in the Widgets tab.`;
    }
    if (isOverCap(tag)) return `${reference}: ${overCapText(selectionSize(tag))}`;
    return null;
  }
  if (parsed.kind === "scenario") return scenarioProblem(reference, parsed, scope.inputs, context, language);
  if (parsed.kind === "dataset") return datasetProblem(reference, scope.inputs, language);
  if (parsed.kind === "stacked") {
    if (language !== "json") return `${reference} is for a Vega-Lite spec, not for code.`;
    const fields = knownStackedFields(scope.inputs);
    if (fields !== null && !fields.includes(parsed.column)) {
      return `${reference}: the dataset inputs has no field ${parsed.column}.`;
    }
    return null;
  }
  if (inner.includes("$")) {
    return `${reference} is an old widget marker. Add the widget in the node's Widgets tab and drag its tag into the code.`;
  }
  if (!WIDGET_NAME_RE.test(inner)) {
    return `${reference} does not name a widget. Widget names are letters, digits and underscores.`;
  }
  if (!scope.widgets.some((w) => w.name === inner)) {
    return `${reference}: this node has no widget named ${inner}. Add it in the Widgets tab.`;
  }
  return null;
}

/** What a reference without a problem writes, standing in *context*, and at
 * *place* in a Vega-Lite spec. */
function resolvedText(
  inner: string,
  scope: ReferenceScope,
  context: ReferenceContext,
  language: CodeLanguage,
  place?: FieldPlace,
): string {
  const named = (name: string) => (place?.text ? vegaFieldName(name) : name);
  const parsed = parseReference(inner);
  if (parsed.kind === "input") {
    if (parsed.column !== undefined) return writeText(named(parsed.column), context, language);
    const position = scope.inputs.findIndex((i) => i.slot === parsed.slot);
    if (language === "json") {
      // A spec reads a layer by its name, and an input, or the one frame it
      // carries, by the name the input is read by.
      const layer = isOneFrameInput(scope.inputs[position]) ? undefined : parsed.layer;
      return writeText(named(layer ?? inputTableName(position)), context, language);
    }
    const value = inputName(parsed.slot);
    if (parsed.layer !== undefined) {
      return `${LAYER_HELPER}(${value}, ${widgetLiteral(parsed.layer, language)}, ${parsed.slot})`;
    }
    return value;
  }
  // A field of inputs is written as a column is: its name. The dataset itself
  // is its name too, which no place reads as a field.
  if (parsed.kind === "stacked") return writeText(named(parsed.column), context, language);
  if (parsed.kind === "dataset") return writeText(INPUTS_DATASET, context, language);
  const value =
    parsed.kind === "scenario"
      ? scenarioValue(parsed, scope.inputs)
      : parsed.kind === "selection"
        ? ((scope.selections ?? []).find((t) => t.name === parsed.name) as SelectionTag).ids as WidgetValue
        : effectiveValue(
            (parsed.kind === "shared" ? scope.shared : scope.widgets).find((w) => w.name === parsed.name) as WidgetDef,
          );
  if (context.kind === "code") return widgetLiteral(place ? fieldValue(value, place) : value, language);
  return escapeFor(named(textOf(value, language)), context, language);
}

/** *code* with every reference replaced, and what could not be replaced. A
 * reference with a problem is left as written. *grammar* is the grammar of a
 * JSON document: in a Vega-Lite spec (`VEGA_LITE`), a reference where
 * Vega-Lite reads a field name writes each name escaped (`vegaFieldName`). */
export function resolveReferences(
  code: string,
  scope: ReferenceScope,
  language: CodeLanguage,
  grammar?: string | null,
): { code: string; problems: ReferenceProblem[] } {
  const refs = findReferences(code);
  if (refs.length === 0) return { code, problems: [] };
  const ordered: ReferenceScope = { ...scope, inputs: [...scope.inputs].sort((a, b) => a.slot - b.slot) };
  const contexts = referenceContexts(code, refs, language);
  const places = language === "json" && grammar === VEGA_LITE ? vegaFieldPlaces(code, refs, contexts) : null;
  const problems: ReferenceProblem[] = [];
  let out = "";
  let last = 0;
  refs.forEach((ref, index) => {
    out += code.slice(last, ref.start);
    const written = code.slice(ref.start, ref.end);
    const problem = referenceProblem(written, ref.inner, ordered, contexts[index], language);
    if (problem !== null) {
      problems.push({ reference: written, message: problem });
      out += written;
    } else {
      out += resolvedText(ref.inner, ordered, contexts[index], language, places?.[index]);
    }
    last = ref.end;
  });
  out += code.slice(last);
  return { code: out, problems };
}

/** One message for a failed run, one line per problem. */
export function describeReferenceProblems(problems: ReferenceProblem[]): string {
  return problems.map((p) => p.message).join("\n");
}

/** Why a node with several inputs cannot run yet: the circles in *slots* hold
 * nothing. One line per input. */
export function describeEmptyInputs(slots: number[], inputs: InputScope[]): string {
  return slots
    .map((slot) => {
      const label = inputs.find((i) => i.slot === slot)?.label;
      return `${inputName(slot)}${label ? ` (from ${label})` : ""} has no value yet. Run the node that feeds it.`;
    })
    .join("\n");
}

/** Where Python or JavaScript *code* names an input by typing its name,
 * `input_1`: outside strings, comments and references, or inside the braces
 * of a Python f-string or a JavaScript template literal, where it is code. */
export function inputNamesIn(code: string, language: CodeLanguage): { start: number; end: number; slot: number }[] {
  if (language === "json") return [];
  const refs = findReferences(code);
  const found: CodeReference[] = [];
  const re = new RegExp(INPUT_NAME_PATTERN, "g");
  let match: RegExpExecArray | null;
  while ((match = re.exec(code)) !== null) {
    const start = match.index;
    const end = start + match[0].length;
    if (refs.some((r) => start < r.end && end > r.start)) continue;
    found.push({ start, end, inner: match[1] });
  }
  const inCode = readsNamesAt(code, found.map((f) => f.start), language);
  return found
    .filter((_, index) => inCode[index])
    .map((f) => ({ start: f.start, end: f.end, slot: Number(f.inner) }));
}

type ScanFrame =
  | { kind: "code" | "comment" | "block" | "spec" }
  | { kind: "string"; quote: string; interpolates: boolean }
  | { kind: "expression"; depth: number };

/** The prefix of the Python string whose quote is at *quoteAt*: `f`, `rf`,
 * `b`, ..., or "" for none. */
function pythonStringPrefix(code: string, quoteAt: number): string {
  let start = quoteAt;
  while (start > 0 && quoteAt - start < 2 && /[A-Za-z]/.test(code[start - 1])) start -= 1;
  if (start > 0 && /[\w$]/.test(code[start - 1])) return "";
  const prefix = code.slice(start, quoteAt);
  return /^(?:[rRbBuUfF]|[fF][rR]|[rR][fF]|[bB][rR]|[rR][bB])$/.test(prefix) ? prefix : "";
}

/**
 * Whether each of *offsets* (ascending) in *code* is where the code reads
 * names: outside strings and comments, or inside the `{...}` of a Python
 * f-string (its format spec's own `{...}` included) or the `${...}` of a
 * JavaScript template literal, at any depth. An f-string's `{{` and `}}`
 * are text.
 */
function readsNamesAt(code: string, offsets: number[], language: CodeLanguage): boolean[] {
  const result: boolean[] = [];
  const stack: ScanFrame[] = [{ kind: "code" }];
  let i = 0;
  while (result.length < offsets.length) {
    const top = stack[stack.length - 1];
    while (result.length < offsets.length && offsets[result.length] <= i) {
      result.push(top.kind === "code" || top.kind === "expression");
    }
    if (i >= code.length) break;
    const ch = code[i];
    if (top.kind === "code" || top.kind === "expression") {
      if (language === "python" && ch === "#") {
        stack.push({ kind: "comment" });
      } else if (language === "javascript" && (code.startsWith("//", i) || code.startsWith("/*", i))) {
        stack.push({ kind: code[i + 1] === "/" ? "comment" : "block" });
        i += 1;
      } else if (ch === '"' || ch === "'" || (language === "javascript" && ch === "`")) {
        const triple = language === "python" && code.startsWith(ch.repeat(3), i);
        const quote = triple ? ch.repeat(3) : ch;
        const interpolates = language === "python" ? /f/i.test(pythonStringPrefix(code, i)) : ch === "`";
        stack.push({ kind: "string", quote, interpolates });
        i += quote.length;
        continue;
      } else if (top.kind === "expression") {
        if (ch === "(" || ch === "[" || ch === "{") {
          top.depth += 1;
        } else if ((ch === ")" || ch === "]") && top.depth > 0) {
          top.depth -= 1;
        } else if (ch === "}") {
          if (top.depth > 0) top.depth -= 1;
          else stack.pop();
        } else if (language === "python" && ch === ":" && top.depth === 0) {
          stack.push({ kind: "spec" });
        }
      }
      i += 1;
      continue;
    }
    if (top.kind === "comment") {
      if (ch === "\n") stack.pop();
    } else if (top.kind === "block") {
      if (code.startsWith("*/", i)) {
        stack.pop();
        i += 1;
      }
    } else if (top.kind === "spec") {
      if (ch === "{") {
        stack.push({ kind: "expression", depth: 0 });
      } else if (ch === "}") {
        // The end of the spec is the end of its replacement field.
        stack.pop();
        stack.pop();
      }
    } else if (top.kind === "string") {
      if (ch === "\\") {
        // A backslash keeps the next character in the string, but not a brace
        // that opens a replacement field.
        i += top.interpolates && (code[i + 1] === "{" || code[i + 1] === "}") ? 1 : 2;
        continue;
      }
      if (top.interpolates && language === "python" && (code.startsWith("{{", i) || code.startsWith("}}", i))) {
        i += 2;
        continue;
      }
      if (top.interpolates && (language === "python" ? ch === "{" : code.startsWith("${", i))) {
        stack.push({ kind: "expression", depth: 0 });
        i += language === "python" ? 1 : 2;
        continue;
      }
      if (code.startsWith(top.quote, i)) {
        stack.pop();
        i += top.quote.length;
        continue;
      }
      // An unterminated one-line string ends with its line.
      if (ch === "\n" && top.quote.length === 1 && top.quote !== "`") stack.pop();
    }
    i += 1;
  }
  while (result.length < offsets.length) result.push(false);
  return result;
}

/**
 * *code* after circle *removedSlot* lost its edge and the circles below it
 * moved up one: references, an input's scenario chip among them, and typed
 * input names (in *language*) to later inputs count one less, and those to the
 * removed input become `[!! input_? !!]` (`[!! scenario input_? !!]`), which
 * reports itself. Other references, and the text around them, are kept as
 * written.
 */
export function renumberInputReferences(code: string, removedSlot: number, language: CodeLanguage = "python"): string {
  const edits: { start: number; end: number; text: string }[] = [];
  const moved = (slot: number) => (slot === removedSlot ? null : slot - 1);
  for (const ref of findReferences(code)) {
    const parsed = parseReference(ref.inner);
    if (parsed.kind === "scenario" && parsed.chip === "input") {
      if (parsed.slot === null || parsed.slot < removedSlot) continue;
      edits.push({ start: ref.start, end: ref.end, text: referenceText(scenarioInputReferenceInner(moved(parsed.slot))) });
      continue;
    }
    if (parsed.kind !== "input" || parsed.slot === null || parsed.slot < removedSlot) continue;
    const slot = moved(parsed.slot);
    edits.push({ start: ref.start, end: ref.end, text: referenceText(inputReferenceInner(slot, parsed.column, parsed.layer)) });
  }
  for (const name of inputNamesIn(code, language)) {
    if (name.slot < removedSlot) continue;
    const text = name.slot === removedSlot ? referenceText(inputName(null)) : inputName(name.slot - 1);
    edits.push({ start: name.start, end: name.end, text });
  }
  edits.sort((a, b) => a.start - b.start);
  let out = "";
  let last = 0;
  for (const edit of edits) {
    out += code.slice(last, edit.start) + edit.text;
    last = edit.end;
  }
  return edits.length === 0 ? code : out + code.slice(last);
}

/** The names of the shared tags *code* references, each once, in order. */
export function sharedNamesIn(code: string): string[] {
  return namesOfKindIn(code, "shared");
}

/** The names of the selection tags *code* references, each once, in order.
 * Kept in sync with `selection_names_in` in `code_references.py`. */
export function selectionNamesIn(code: string): string[] {
  return namesOfKindIn(code, "selection");
}

function namesOfKindIn(code: string, kind: "shared" | "selection"): string[] {
  const names: string[] = [];
  for (const ref of findReferences(code)) {
    const parsed = parseReference(ref.inner);
    if (parsed.kind === kind && !names.includes(parsed.name)) names.push(parsed.name);
  }
  return names;
}

/**
 * *code* after the Parameter node named *from* was renamed *to*: its shared
 * references follow the new name. Other references, and the text around
 * them, are kept as written.
 */
export function renameSharedReferences(code: string, from: string, to: string): string {
  let out = "";
  let last = 0;
  for (const ref of findReferences(code)) {
    const parsed = parseReference(ref.inner);
    if (parsed.kind !== "shared" || parsed.name !== from) continue;
    out += code.slice(last, ref.start) + referenceText(sharedReferenceInner(to));
    last = ref.end;
  }
  return last === 0 ? code : out + code.slice(last);
}
