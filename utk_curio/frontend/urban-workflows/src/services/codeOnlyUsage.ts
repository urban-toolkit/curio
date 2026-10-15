/**
 * What a catalog's Remove says of the dataflows that use an item only through
 * node code: a literal `curio_data_path("<id>")` for a dataset, a literal
 * `curio_load_model("<id>")` for a model, with no binding. Nothing rewrites
 * node code on removal, so that code stays behind, and the confirmation names
 * those dataflows first.
 *
 * Written once for the Data Catalog's Remove and the Model Catalog's, from
 * their usage reads (`GET /api/datasets/<id>/usage`,
 * `GET /api/packages/<dir>/usage`), whose rows mark such a dataflow
 * `codeOnly`.
 */

/** A dataflow a usage read names, as both reads answer it. */
export interface DataflowUsageRow {
  dataflowId: string;
  dataflowName: string | null;
  nodeCount: number;
  /** The dataflow's nodes that use the item. */
  nodes?: Array<{ nodeId: string; nodeType?: string | null }>;
  /** It uses the item only through node code, which keeps nothing. */
  codeOnly?: boolean;
}

/** What a dataflow with no name is called. */
export const UNTITLED_DATAFLOW = "Untitled dataflow";

/** The names of the dataflows of *usage* that use the item only through node code. */
export function codeOnlyDataflowNames(
  usage: ReadonlyArray<Pick<DataflowUsageRow, "dataflowName" | "codeOnly">>,
): string[] {
  return usage.filter((row) => row.codeOnly).map((row) => row.dataflowName || UNTITLED_DATAFLOW);
}

/** *names* in the order the usage reads give them: by name, ignoring case. */
export function byDataflowName(names: readonly string[]): string[] {
  return [...names].sort((a, b) => {
    const x = a.toLowerCase();
    const y = b.toLowerCase();
    return x < y ? -1 : x > y ? 1 : 0;
  });
}

/**
 * The confirmation's paragraph naming the dataflows *names*, whose nodes load
 * the *item* ("dataset", "model") in code, then *outcome*: what becomes of
 * that code, told whether several dataflows are named. `""` for none.
 */
export function codeOnlyWarning(
  names: readonly string[],
  item: string,
  outcome: (several: boolean) => string,
): string {
  if (names.length === 0) return "";
  const several = names.length > 1;
  return `\n\n${several ? "Nodes in" : "A node in"} ${names.join(", ")} ${
    several ? "load" : "loads"
  } this ${item} in code. ${outcome(several)}`;
}
