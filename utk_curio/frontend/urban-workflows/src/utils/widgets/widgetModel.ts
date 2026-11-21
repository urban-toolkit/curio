/**
 * A node's widgets: declared in its Widgets tab, saved at `metadata.widgets`,
 * and placed in its code as `[!! name !!]` references (#662).
 *
 * The value a run uses is `value` when the user set one, else `default`.
 */

import { INPUTS_DATASET } from "../vegaDatasets";
import catalogCode from "../../contracts/catalogCode.json";

/** The widget kinds. Kept in sync with `WIDGET_KINDS` in
 * `utk_curio/backend/app/execution/code_references.py`, which a package
 * manifest's template widgets are checked with too, and with the widget's
 * `type` enum in `docs/schemas/node-package.v4.json` and `docs/schemas/trill.v1.json`. */
export const WIDGET_KINDS = [
  "number",
  "slider",
  "text",
  "choice",
  "checkbox",
  "checkbox-group",
  "multi-select",
  "datetime",
  "date",
  "location",
  "number-list",
  "text-list",
  "range",
  "file",
  "dataset",
] as const;

export type WidgetKind = (typeof WIDGET_KINDS)[number];

/** A location widget's value: a WGS84 point, in SCOUT's shape. */
export interface LocationValue {
  lat: number;
  lon: number;
}

export type WidgetValue = number | string | boolean | number[] | string[] | LocationValue | null;

export interface WidgetOptions {
  /** A choice, checkbox group or multi-select widget's options; for a
   * dataset widget an input picks, the dataset each value of that input
   * picks, by its Data Catalog id (`PickedChoices`). */
  choices?: string[] | PickedChoices;
  /** The input that picks a dataset widget's dataset among its choices:
   * `input_<k>`, the value on circle k, or `input_<k>.<key>`, the value under
   * a key of the dict on it (`PICKED_BY_PATTERN`). */
  pickedBy?: string;
  /** How a choice widget is drawn; a dropdown when absent. */
  display?: "dropdown" | "radio";
  /** A number or slider widget's bounds and step; a slider needs both bounds. */
  min?: number;
  max?: number;
  step?: number;
  /** Shown after a number or slider widget's value, such as "m" or "%". */
  units?: string;
}

export interface WidgetDef {
  name: string;
  type: WidgetKind;
  label?: string;
  default: WidgetValue;
  value?: WidgetValue;
  options?: WidgetOptions;
}

export const WIDGET_KIND_LABELS: Record<WidgetKind, string> = {
  number: "Number",
  slider: "Slider",
  text: "Text",
  choice: "Choice",
  checkbox: "Checkbox",
  "checkbox-group": "Checkbox group",
  "multi-select": "Multi-select",
  datetime: "Date and time",
  date: "Date",
  location: "Location",
  "number-list": "List of numbers",
  "text-list": "List of texts",
  range: "Range",
  file: "Text file",
  dataset: "Dataset",
};

/** The kinds whose options list choices. */
export const CHOICE_KINDS: readonly WidgetKind[] = ["choice", "checkbox-group", "multi-select"];
/** The kinds that take bounds, a step and units. */
export const NUMERIC_KINDS: readonly WidgetKind[] = ["number", "slider"];

/** A widget name: what a reference names. Kept in sync with
 * `WIDGET_NAME_RE` in `utk_curio/backend/app/execution/code_references.py`,
 * which a package manifest's template widgets are checked with too. */
export const WIDGET_NAME_PATTERN = String.raw`^[A-Za-z_][A-Za-z0-9_]{0,63}$`;
export const WIDGET_NAME_RE = new RegExp(WIDGET_NAME_PATTERN);

/** The names of a node's inputs, which no widget takes: an input's,
 * `input_<k>`, in its code as in its chips, and `inputs`, the dataset a
 * Vega-Lite spec reads them stacked in (`INPUTS_DATASET`). Kept in sync with
 * `INPUT_NAME_ONLY_RE` in `utk_curio/backend/app/execution/code_references.py`,
 * which a package manifest's template widgets are checked with too. */
export const INPUT_NAME_ONLY_PATTERN = String.raw`^(?:input_\d+|inputs)$`;
const INPUT_NAME_ONLY_RE = new RegExp(INPUT_NAME_ONLY_PATTERN);

/** A text file widget keeps the file's text in the dataflow, so it is capped. */
export const FILE_WIDGET_MAX_CHARS = 1_000_000;

/** A dataset widget's value: the id of a Data Catalog dataset, a layer group
 * or a collection, as node code names one in `curio_load_data("<id>")`; empty
 * until one is dropped on it. The id is `contracts/catalogCode.json`'s, which
 * `DATASET_ID_RE` in `utk_curio/backend/app/execution/code_references.py` and
 * `services/datasetCatalog/datasetLoaderSnippets.ts` read too. */
export const DATASET_ID_PATTERN = `^${catalogCode.itemId}$`;
const DATASET_ID_RE = new RegExp(DATASET_ID_PATTERN);

/** What a run refuses when code reads an empty dataset widget. Kept in sync
 * with `empty_dataset_message` in `code_references.py`. */
export function emptyDatasetMessage(reference: string, widget: Pick<WidgetDef, "name" | "label">): string {
  return `${reference}: drop a file or a Data Catalog dataset on ${widget.label || widget.name} first.`;
}

/** A picked dataset widget's choices: each value its input may hold, and the
 * Data Catalog id of the dataset that value picks. */
export type PickedChoices = Record<string, string>;

/** How a dataset widget names the input that picks its dataset
 * (`options.pickedBy`). Kept in sync with `PICKED_BY_RE` in
 * `code_references.py`. */
export const PICKED_BY_PATTERN = String.raw`^input_(\d{1,3})(?:\.(.+))?$`;
const PICKED_BY_RE = new RegExp(PICKED_BY_PATTERN);
/** The most circles a node has. Kept in sync with `MAX_PICKED_SLOT`. */
const MAX_PICKED_SLOT = 255;
/** The most choices a picked dataset widget gives, as many datasets as a scan
 * of a node names. Kept in sync with `MAX_PICKED_CHOICES`. */
export const MAX_PICKED_CHOICES = 32;

/** The choices a choice, checkbox group or multi-select widget lists. */
export function listedChoices(options?: WidgetOptions): string[] {
  const choices = options?.choices;
  return Array.isArray(choices) ? choices : [];
}

/** A picked dataset widget's choices, or an empty map. */
export function pickedChoices(widget: Pick<WidgetDef, "options">): PickedChoices {
  const choices = widget.options?.choices;
  return choices && typeof choices === "object" && !Array.isArray(choices) ? choices : {};
}

/** Whether *widget* says an input picks its value (`options.pickedBy`). */
export function isPicked(widget: Pick<WidgetDef, "options">): boolean {
  return widget.options !== undefined && "pickedBy" in widget.options;
}

/** The circle and the key a picked dataset widget reads, or null when its
 * `pickedBy` names no circle. Kept in sync with `picked_by`. */
export function pickedBy(widget: Pick<WidgetDef, "options">): { slot: number; key: string | null } | null {
  const by = widget.options?.pickedBy;
  const match = typeof by === "string" ? PICKED_BY_RE.exec(by) : null;
  if (!match || match[0] !== by || Number(match[1]) > MAX_PICKED_SLOT) return null;
  return { slot: Number(match[1]), key: match[2] ?? null };
}

/** What is wrong with how *def* says an input picks its value, or null. Kept
 * in sync with `pick_problem` in `code_references.py`. */
export function pickProblem(def: Pick<WidgetDef, "type" | "options">): string | null {
  const options = def.options ?? {};
  const named = "pickedBy" in options;
  const choices = options.choices as unknown;
  const mapped = choices !== null && typeof choices === "object" && !Array.isArray(choices);
  if (!named) {
    return def.type === "dataset" && mapped
      ? "A dataset widget's choices go with pickedBy, the input that picks one of them."
      : null;
  }
  if (def.type !== "dataset") return "Only a dataset widget is picked by an input.";
  if (pickedBy(def) === null) {
    return "pickedBy names an input circle, such as input_0, or a key of the dict on it, such as input_0.camera.";
  }
  const entries = mapped ? Object.entries(choices as Record<string, unknown>) : [];
  if (entries.length === 0 || entries.some(([key]) => key === "")) {
    return "A dataset widget an input picks gives its choices: each value the input may hold, and the dataset that value picks.";
  }
  if (entries.length > MAX_PICKED_CHOICES) {
    return `A dataset widget an input picks gives at most ${MAX_PICKED_CHOICES} choices.`;
  }
  if (entries.some(([, id]) => typeof id !== "string" || !DATASET_ID_RE.test(id))) {
    return "Each choice names a Data Catalog dataset, layer group or collection by its id.";
  }
  return null;
}

export function effectiveValue(widget: WidgetDef): WidgetValue {
  return widget.value !== undefined ? widget.value : widget.default;
}

/** A date-time widget's value when its widget gives none. Kept in sync with
 * `DATETIME_FALLBACK` in `code_references.py`. */
export const DATETIME_FALLBACK = "1970-01-01T00:00:00";
/** A date widget's value when its widget gives none. Kept in sync with
 * `DATE_FALLBACK` in `code_references.py`. */
export const DATE_FALLBACK = "1970-01-01";

/**
 * A kind's value when a widget gives no default. Kept in sync with
 * `default_value_for` in `code_references.py`, so the browser and the
 * runner write the same value for such a widget.
 */
export function defaultValueFor(kind: WidgetKind, options?: WidgetOptions): WidgetValue {
  switch (kind) {
    case "number":
    case "slider":
      return isFiniteNumber(options?.min) ? options!.min! : 0;
    case "checkbox":
      return false;
    case "choice": {
      const choices = listedChoices(options);
      return choices.length > 0 ? choices[0] : "";
    }
    case "checkbox-group":
    case "multi-select":
    case "number-list":
    case "text-list":
      return [];
    case "range":
      return [0, 1];
    case "datetime":
      return DATETIME_FALLBACK;
    case "date":
      return DATE_FALLBACK;
    case "location":
      return { lat: 0, lon: 0 };
    default:
      return "";
  }
}

const isFiniteNumber = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

const DATETIME_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/;

/**
 * *text* as a date-time widget's value, `YYYY-MM-DDTHH:mm:ss`, or null when it
 * is not a real date and time. A browser's date-time field leaves the seconds
 * out when they are zero, so both lengths are taken.
 */
export function normalizeDateTime(text: string): string | null {
  const m = DATETIME_RE.exec(text);
  if (!m) return null;
  const [y, mo, d, h, mi, s] = [m[1], m[2], m[3], m[4], m[5], m[6] ?? "00"].map(Number);
  const t = new Date(Date.UTC(y, mo - 1, d, h, mi, s));
  const real =
    t.getUTCFullYear() === y &&
    t.getUTCMonth() === mo - 1 &&
    t.getUTCDate() === d &&
    t.getUTCHours() === h &&
    t.getUTCMinutes() === mi &&
    t.getUTCSeconds() === s;
  return real ? `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6] ?? "00"}` : null;
}

const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** *text* as a date widget's value, `YYYY-MM-DD`, or null when it is not a real date. */
export function normalizeDate(text: string): string | null {
  const m = DATE_RE.exec(text);
  if (!m) return null;
  const [y, mo, d] = [m[1], m[2], m[3]].map(Number);
  const t = new Date(Date.UTC(y, mo - 1, d));
  const real = t.getUTCFullYear() === y && t.getUTCMonth() === mo - 1 && t.getUTCDate() === d;
  return real ? text : null;
}

/** *date*'s local time to the minute, as a date-time widget's value. */
export function dateTimeValue(date: Date): string {
  const two = (n: number) => String(n).padStart(2, "0");
  return (
    `${String(date.getFullYear()).padStart(4, "0")}-${two(date.getMonth() + 1)}-${two(date.getDate())}` +
    `T${two(date.getHours())}:${two(date.getMinutes())}:00`
  );
}

function boundsProblem(value: number, options?: WidgetOptions): string | null {
  const min = isFiniteNumber(options?.min) ? options!.min! : undefined;
  const max = isFiniteNumber(options?.max) ? options!.max! : undefined;
  if (min !== undefined && max !== undefined && (value < min || value > max)) {
    return `Enter a number from ${min} to ${max}.`;
  }
  if (min !== undefined && value < min) return `Enter a number of at least ${min}.`;
  if (max !== undefined && value > max) return `Enter a number of at most ${max}.`;
  return null;
}

/** What is wrong with *value* for *widget*, or null when it is fine. */
export function checkWidgetValue(
  widget: Pick<WidgetDef, "type" | "options">,
  value: unknown,
): string | null {
  switch (widget.type) {
    case "number":
    case "slider":
      return isFiniteNumber(value) ? boundsProblem(value, widget.options) : "Enter a number.";
    case "text":
      return typeof value === "string" ? null : "Enter a text.";
    case "file":
      if (typeof value !== "string") return "Choose a text file.";
      return value.length > FILE_WIDGET_MAX_CHARS
        ? `The file is longer than ${FILE_WIDGET_MAX_CHARS.toLocaleString("en-US")} characters. Add it to the Data Catalog instead.`
        : null;
    case "dataset":
      return typeof value === "string" && (value === "" || DATASET_ID_RE.test(value))
        ? null
        : "Drop a file or a Data Catalog dataset.";
    case "checkbox":
      return typeof value === "boolean" ? null : "Choose true or false.";
    case "choice": {
      const choices = listedChoices(widget.options);
      if (typeof value !== "string") return "Pick one of the choices.";
      return choices.includes(value) ? null : "Pick one of the choices.";
    }
    case "checkbox-group":
    case "multi-select": {
      const choices = listedChoices(widget.options);
      return Array.isArray(value) &&
        value.every((v) => typeof v === "string" && choices.includes(v)) &&
        new Set(value).size === value.length
        ? null
        : "Pick among the choices, each at most once.";
    }
    case "datetime":
      return typeof value === "string" && normalizeDateTime(value) === value
        ? null
        : "Enter a date and time.";
    case "date":
      return typeof value === "string" && normalizeDate(value) === value ? null : "Enter a date.";
    case "location": {
      const v = value as Partial<LocationValue> | null;
      return v !== null &&
        typeof v === "object" &&
        !Array.isArray(v) &&
        Object.keys(v).length === 2 &&
        isFiniteNumber(v.lat) &&
        isFiniteNumber(v.lon) &&
        Math.abs(v.lat) <= 90 &&
        Math.abs(v.lon) <= 180
        ? null
        : "Enter a latitude from -90 to 90 and a longitude from -180 to 180.";
    }
    case "number-list":
      return Array.isArray(value) && value.every(isFiniteNumber) ? null : "Enter a list of numbers, such as [1, 2.5].";
    case "text-list":
      return Array.isArray(value) && value.every((v) => typeof v === "string")
        ? null
        : 'Enter a list of texts, such as ["a", "b"].';
    case "range":
      return Array.isArray(value) &&
        value.length === 2 &&
        isFiniteNumber(value[0]) &&
        isFiniteNumber(value[1]) &&
        value[0] <= value[1]
        ? null
        : "Enter two numbers, the first not larger than the second.";
    default:
      return "Unknown widget type.";
  }
}

/** What is wrong with a widget being added or edited, or null. *others* are
 * the node's other widgets, whose names it must not reuse. */
export function checkWidgetDef(def: WidgetDef, others: WidgetDef[]): string | null {
  if (!WIDGET_NAME_RE.test(def.name)) {
    return "A name is letters, digits and underscores, and does not start with a digit.";
  }
  if (def.name === INPUTS_DATASET) return `${def.name} names the node's stacked inputs. Pick another name.`;
  if (INPUT_NAME_ONLY_RE.test(def.name)) return `${def.name} names one of the node's inputs. Pick another name.`;
  if (others.some((w) => w.name === def.name)) return `This node already has a widget named ${def.name}.`;
  if (!(WIDGET_KINDS as readonly string[]).includes(def.type)) return "Pick a widget type.";
  const picking = pickProblem(def);
  if (picking) return picking;
  if (CHOICE_KINDS.includes(def.type)) {
    const choices = listedChoices(def.options);
    if (choices.length === 0) return "Give at least one choice.";
    if (new Set(choices).size !== choices.length) return "Each choice can appear only once.";
  }
  if (NUMERIC_KINDS.includes(def.type)) {
    const { min, max, step } = def.options ?? {};
    if (def.type === "slider" && (min === undefined || max === undefined)) {
      return "A slider needs a minimum and a maximum.";
    }
    if (min !== undefined && max !== undefined && !(min < max)) return "The minimum must be below the maximum.";
    if (step !== undefined && !(step > 0)) return "The step must be above 0.";
  }
  return checkWidgetValue(def, def.default);
}

/** The well-formed options in *raw*, or undefined when there are none. */
function normalizeOptions(raw: unknown): WidgetOptions | undefined {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const o = raw as Record<string, unknown>;
  const out: WidgetOptions = {};
  if (Array.isArray(o.choices)) out.choices = o.choices.filter((c): c is string => typeof c === "string");
  // A picked dataset widget's choices and the input that picks among them
  // are kept as written, so its check (pickProblem) and its save see them.
  else if (o.choices && typeof o.choices === "object") out.choices = { ...(o.choices as PickedChoices) };
  if ("pickedBy" in o) out.pickedBy = o.pickedBy as string;
  if (o.display === "dropdown" || o.display === "radio") out.display = o.display;
  if (isFiniteNumber(o.min)) out.min = o.min;
  if (isFiniteNumber(o.max)) out.max = o.max;
  if (isFiniteNumber(o.step)) out.step = o.step;
  if (typeof o.units === "string" && o.units) out.units = o.units;
  return Object.keys(out).length > 0 ? out : undefined;
}

/** The widgets in *raw* (a spec's `metadata.widgets`, a manifest's template
 * `widgets`, or node data), keeping only well-formed entries. */
export function normalizeWidgets(raw: unknown): WidgetDef[] {
  if (!Array.isArray(raw)) return [];
  const out: WidgetDef[] = [];
  const seen = new Set<string>();
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const e = entry as Record<string, unknown>;
    const name = typeof e.name === "string" ? e.name : "";
    const type = e.type as WidgetKind;
    if (!WIDGET_NAME_RE.test(name) || seen.has(name)) continue;
    if (!(WIDGET_KINDS as readonly string[]).includes(type)) continue;
    const options = normalizeOptions(e.options);
    const def: WidgetDef = {
      name,
      type,
      default: (e.default ?? defaultValueFor(type, options)) as WidgetValue,
    };
    if (typeof e.label === "string" && e.label) def.label = e.label;
    if (e.value !== undefined) def.value = e.value as WidgetValue;
    if (options !== undefined) def.options = options;
    seen.add(name);
    out.push(def);
  }
  return out;
}

/**
 * What a run of this node depends on: its code, and its widgets' values.
 *
 * `playNodesUpTo` compares this with the key recorded when the node last
 * succeeded, so a node whose widget value changed runs again. Without widgets
 * the key is the code itself, as it was before widgets were saved.
 */
export function nodeRunKey(code: string, widgets?: unknown): string {
  const list = normalizeWidgets(widgets);
  if (list.length === 0) return code;
  return code + "\u0000" + JSON.stringify(list.map((w) => [w.name, effectiveValue(w)]));
}
