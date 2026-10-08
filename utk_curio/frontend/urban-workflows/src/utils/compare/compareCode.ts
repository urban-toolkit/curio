/**
 * The code a Compare Scenarios node (#662) writes for itself: one line per
 * input circle, each reading the input through its chip and naming the
 * scenario it comes from, handed to the sandbox's stacking step, or, in
 * Difference, to its difference step. A run in the browser and a run on the
 * server both run it as any Python node's code.
 */
import { inputReferenceInner, referenceText, widgetLiteral } from "../references/codeReferences";
import type { CompareDifference, CompareInputLabel, CompareMode } from "./compareSettings";

/** What the node's code calls; `curio_stack_scenarios` in the sandbox's
 * namespace (`utk_curio/sandbox/util/scenario_stack.py`). */
export const STACK_HELPER = "curio_stack_scenarios";

/** What it calls in Difference (`utk_curio/sandbox/util/scenario_difference.py`). */
export const DIFFERENCE_HELPER = "curio_difference_scenarios";

export const STACK_CODE_NOTE = [
  "# Compare Scenarios writes this code from its inputs: each input, under the",
  "# id and the name of its scenario. It is written again when they change.",
];

export const DIFFERENCE_CODE_NOTE = [
  "# Compare Scenarios writes this code from its inputs: input 1 minus input 0,",
  "# each under the id and the name of its scenario. It is written again when",
  "# they change.",
];

type CodeInput = { slot: number; label: CompareInputLabel };

function entryLine(input: CodeInput): string {
  const scenario = widgetLiteral(input.label.scenario ?? null, "python");
  const name = widgetLiteral(input.label.name, "python");
  return `    (${scenario}, ${name}, ${referenceText(inputReferenceInner(input.slot))}),`;
}

/** `, layer="…"` for the layer read from an Autark node's several, or nothing. */
function layerArgument(layer?: string): string {
  return layer ? `, layer=${widgetLiteral(layer, "python")}` : "";
}

/** The stacking code for these inputs, in circle order, reading *layer* from an Autark node's several. */
export function stackCode(inputs: readonly CodeInput[], layer?: string): string {
  const layered = layerArgument(layer);
  if (inputs.length === 0) return [...STACK_CODE_NOTE, `return ${STACK_HELPER}([]${layered})`, ""].join("\n");
  return [...STACK_CODE_NOTE, `return ${STACK_HELPER}([`, ...inputs.map(entryLine), `]${layered})`, ""].join("\n");
}

/**
 * The difference code for these inputs, in circle order, joining rows on
 * *key*, reading *layer* from an Autark node's several, and, when *absolute*,
 * giving each difference's size. The key comes last, as `keyOfCode` reads it.
 */
export function differenceCode(inputs: readonly CodeInput[], key?: string, layer?: string, absolute?: boolean): string {
  const args = `${layerArgument(layer)}${absolute ? ", absolute=True" : ""}${key ? `, key=${widgetLiteral(key, "python")}` : ""}`;
  if (inputs.length === 0) return [...DIFFERENCE_CODE_NOTE, `return ${DIFFERENCE_HELPER}([]${args})`, ""].join("\n");
  return [...DIFFERENCE_CODE_NOTE, `return ${DIFFERENCE_HELPER}([`, ...inputs.map(entryLine), `]${args})`, ""].join("\n");
}

/** The code for *mode*: the stacking code for Chart, the difference code for Difference. */
export function compareCode(
  mode: CompareMode,
  inputs: readonly CodeInput[],
  difference?: CompareDifference,
  layer?: string,
): string {
  return mode === "difference"
    ? differenceCode(inputs, difference?.key, layer, difference?.absolute)
    : stackCode(inputs, layer);
}

/** The view *code* was written for, by the step it calls, or null for code that calls neither. */
export function modeOfCode(code: string): CompareMode | null {
  if (code.includes(`${DIFFERENCE_HELPER}(`)) return "difference";
  if (code.includes(`${STACK_HELPER}(`)) return "chart";
  return null;
}

const KEY_RE = /\bkey=("(?:[^"\\]|\\.)*")\)/;

function literalOf(match: RegExpExecArray | null): string | undefined {
  if (!match) return undefined;
  try {
    return JSON.parse(match[1]);
  } catch {
    return undefined;
  }
}

/** The key the difference code joins rows on, or undefined when it names none. */
export function keyOfCode(code: string): string | undefined {
  return literalOf(KEY_RE.exec(code));
}

const LAYER_RE = /\blayer=("(?:[^"\\]|\\.)*")[,)]/;

/** Whether the difference code gives each difference's size. */
export function absoluteOfCode(code: string): boolean {
  return /\babsolute=True\b/.test(code);
}

/** The layer the code reads from an Autark node's several, or undefined when it names none. */
export function layerOfCode(code: string): string | undefined {
  return literalOf(LAYER_RE.exec(code));
}
