/**
 * A node's widgets: declared in its Widgets tab, saved at `metadata.widgets`,
 * and placed in its code as `[!! name !!]` references (#662).
 *
 * The value a run uses is `value` when the user set one, else `default`.
 */

export const WIDGET_KINDS = [
  "number",
  "text",
  "choice",
  "checkbox",
  "number-list",
  "text-list",
  "range",
  "file",
] as const;

export type WidgetKind = (typeof WIDGET_KINDS)[number];

export type WidgetValue = number | string | boolean | number[] | string[] | null;

export interface WidgetDef {
  name: string;
  type: WidgetKind;
  label?: string;
  default: WidgetValue;
  value?: WidgetValue;
  options?: { choices?: string[] };
}

export const WIDGET_KIND_LABELS: Record<WidgetKind, string> = {
  number: "Number",
  text: "Text",
  choice: "Choice",
  checkbox: "Checkbox",
  "number-list": "List of numbers",
  "text-list": "List of texts",
  range: "Range",
  file: "Text file",
};

/** A widget name: what a reference names. Kept in sync with
 * `WIDGET_NAME_RE` in `utk_curio/backend/app/execution/widget_substitution.py`. */
export const WIDGET_NAME_PATTERN = String.raw`^[A-Za-z_][A-Za-z0-9_]{0,63}$`;
export const WIDGET_NAME_RE = new RegExp(WIDGET_NAME_PATTERN);

/** A text file widget keeps the file's text in the dataflow, so it is capped. */
export const FILE_WIDGET_MAX_CHARS = 1_000_000;

export function effectiveValue(widget: WidgetDef): WidgetValue {
  return widget.value !== undefined ? widget.value : widget.default;
}

export function defaultValueFor(kind: WidgetKind, choices?: string[]): WidgetValue {
  switch (kind) {
    case "number":
      return 0;
    case "checkbox":
      return false;
    case "choice":
      return choices && choices.length > 0 ? choices[0] : "";
    case "number-list":
    case "text-list":
      return [];
    case "range":
      return [0, 1];
    default:
      return "";
  }
}

const isFiniteNumber = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** What is wrong with *value* for *widget*, or null when it is fine. */
export function checkWidgetValue(
  widget: Pick<WidgetDef, "type" | "options">,
  value: unknown,
): string | null {
  switch (widget.type) {
    case "number":
      return isFiniteNumber(value) ? null : "Enter a number.";
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
  if (others.some((w) => w.name === def.name)) return `This node already has a widget named ${def.name}.`;
  if (!(WIDGET_KINDS as readonly string[]).includes(def.type)) return "Pick a widget type.";
  if (def.type === "choice") {
    const choices = def.options?.choices ?? [];
    if (choices.length === 0) return "Give at least one choice.";
    if (new Set(choices).size !== choices.length) return "Each choice can appear only once.";
  }
  return checkWidgetValue(def, def.default);
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
    const choices = Array.isArray((e.options as any)?.choices)
      ? ((e.options as any).choices as unknown[]).filter((c): c is string => typeof c === "string")
      : undefined;
    const def: WidgetDef = {
      name,
      type,
      default: (e.default ?? defaultValueFor(type, choices)) as WidgetValue,
    };
    if (typeof e.label === "string" && e.label) def.label = e.label;
    if (e.value !== undefined) def.value = e.value as WidgetValue;
    if (choices !== undefined) def.options = { choices };
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
