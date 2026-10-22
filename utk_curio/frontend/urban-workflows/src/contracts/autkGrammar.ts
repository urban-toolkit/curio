/**
 * What a grammar node calls its inputs, and the one view an Autark node draws,
 * over the values in autkGrammar.json, which the backend reads too
 * (contracts.input_table_name and autk_one_view_problem). autkGrammar.cases.json
 * holds the cases both sides run.
 */
import autkGrammar from "./autkGrammar.json";

/** The name a grammar node's input at *position* is read by: input_0, input_1, ... in circle order. */
export function inputTableName(position: number): string {
  return `${autkGrammar.inputTablePrefix}${position}`;
}

/**
 * What a document with more than one view is told, when *spec* has a map and a
 * plot, or lists more than one map or more than one plot; else null. A list of
 * one map or one plot is that view.
 */
export function autkOneViewProblem(spec: unknown): string | null {
  if (spec === null || typeof spec !== "object" || Array.isArray(spec)) return null;
  const { map, plot } = spec as { map?: unknown; plot?: unknown };
  const views = [map, plot];
  const both = views.every((view) => view != null);
  const several = views.some((view) => Array.isArray(view) && view.length > 1);
  return both || several ? autkGrammar.oneView : null;
}
