/**
 * A node's widgets: declared in its Widgets tab, saved at `metadata.widgets`,
 * and placed in its code as `[!! name !!]` references (#662).
 *
 * The value a run uses is `value` when the user set one, else `default`.
 */

export const WIDGET_KINDS = [
  "number",
  "slider",
  "text",
  "choice",
  "checkbox",
  "checkbox-group",
  "multi-select",
  "datetime",
  "location",
  "number-list",
  "text-list",
  "range",
  "file",
] as const;

export type WidgetKind = (typeof WIDGET_KINDS)[number];

/** A location widget's value: a WGS84 point, in SCOUT's shape. */
export interface LocationValue {
  lat: number;
  lon: number;
}

export type WidgetValue = number | string | boolean | number[] | string[] | LocationValue | null;

export interface WidgetOptions {
  /** A choice, checkbox group or multi-select widget's options. */
  choices?: string[];
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
  location: "Location",
  "number-list": "List of numbers",
  "text-list": "List of texts",
  range: "Range",
  file: "Text file",
};

/** The kinds whose options list choices. */
export const CHOICE_KINDS: readonly WidgetKind[] = ["choice", "checkbox-group", "multi-select"];
/** The kinds that take bounds, a step and units. */
export const NUMERIC_KINDS: readonly WidgetKind[] = ["number", "slider"];

/** A widget name: what a reference names. Kept in sync with
 * `WIDGET_NAME_RE` in `utk_curio/backend/app/execution/code_references.py`. */
export const WIDGET_NAME_PATTERN = String.raw`^[A-Za-z_][A-Za-z0-9_]{0,63}$`;
export const WIDGET_NAME_RE = new RegExp(WIDGET_NAME_PATTERN);

/** A text file widget keeps the file's text in the dataflow, so it is capped. */
export const FILE_WIDGET_MAX_CHARS = 1_000_000;

export function effectiveValue(widget: WidgetDef): WidgetValue {
  return widget.value !== undefined ? widget.value : widget.default;
}

/** A date-time widget's value when its widget gives none. Kept in sync with
 * `DATETIME_FALLBACK` in `code_references.py`. */
export const DATETIME_FALLBACK = "1970-01-01T00:00:00";

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
    case "choice":
      return options?.choices && options.choices.length > 0 ? options.choices[0] : "";
    case "checkbox-group":
    case "multi-select":
    case "number-list":
    case "text-list":
      return [];
    case "range":
      return [0, 1];
    case "datetime":
      return DATETIME_FALLBACK;
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
    case "checkbox":
      return typeof value === "boolean" ? null : "Choose true or false.";
    case "choice": {
      const choices = widget.options?.choices ?? [];
      if (typeof value !== "string") return "Pick one of the choices.";
      return choices.includes(value) ? null : "Pick one of the choices.";
    }
    case "checkbox-group":
    case "multi-select": {
      const choices = widget.options?.choices ?? [];
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
 * the node's other widgets, whose names it must not reuse; for a Parameter
 * node's widget (*parameter*), the other Parameter nodes' widgets. */
export function checkWidgetDef(def: WidgetDef, others: WidgetDef[], parameter = false): string | null {
  if (!WIDGET_NAME_RE.test(def.name)) {
    return "A name is letters, digits and underscores, and does not start with a digit.";
  }
  // `input_<i>` names a node's input, in code as in its chips.
  if (/^input_\d+$/.test(def.name)) return `${def.name} names one of the node's inputs. Pick another name.`;
  if (others.some((w) => w.name === def.name)) {
    return parameter
      ? `Another Parameter node is named ${def.name}.`
      : `This node already has a widget named ${def.name}.`;
  }
  if (!(WIDGET_KINDS as readonly string[]).includes(def.type)) return "Pick a widget type.";
  if (CHOICE_KINDS.includes(def.type)) {
    const choices = def.options?.choices ?? [];
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
