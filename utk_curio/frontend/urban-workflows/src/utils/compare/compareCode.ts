/**
 * The code a Compare Scenarios node (#662) writes for itself: one line per
 * input circle, each reading the input through its chip and naming the
 * scenario it comes from, handed to the sandbox's stacking step. A run in the
 * browser and a run on the server both run it as any Python node's code.
 */
import { inputReferenceInner, referenceText, widgetLiteral } from "../references/codeReferences";
import type { CompareInputLabel } from "./compareSettings";

/** What the node's code calls; `curio_stack_scenarios` in the sandbox's
 * namespace (`utk_curio/sandbox/util/scenario_stack.py`). */
export const STACK_HELPER = "curio_stack_scenarios";

export const STACK_CODE_NOTE = [
  "# Compare Scenarios writes this code from its inputs: each input, under the",
  "# id and the name of its scenario. It is written again when they change.",
];

/** The stacking code for these inputs, in circle order. */
export function stackCode(inputs: readonly { slot: number; label: CompareInputLabel }[]): string {
  if (inputs.length === 0) return [...STACK_CODE_NOTE, `return ${STACK_HELPER}([])`, ""].join("\n");
  const entries = inputs.map((input) => {
    const scenario = widgetLiteral(input.label.scenario ?? null, "python");
    const name = widgetLiteral(input.label.name, "python");
    return `    (${scenario}, ${name}, ${referenceText(inputReferenceInner(input.slot))}),`;
  });
  return [...STACK_CODE_NOTE, `return ${STACK_HELPER}([`, ...entries, "])", ""].join("\n");
}
