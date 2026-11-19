/**
 * The views an Autark document declares, read from the document as its node
 * holds it, before its chips are resolved and before it runs: its maps in the
 * order of `map`, then its plots in the order of `plot`, the order
 * autk-grammar's `arrangeViews` gives their panes. Each with its `id`, when it
 * has one, and the table it is picked or brushed on: a map's first layer that
 * picks (`isPick`), else its first, and a plot's `dataRef`.
 *
 * Light, so the canvas reads it without the grammar: an Autark node's dots
 * (one per view with an `id`, adapters/node/autkGrammarBehavior) and the views
 * a selection tag can name (hook/useSelectionViews).
 */
import { withChipPlaceholders } from "./references/codeReferences";

export type DocumentView = {
  kind: "map" | "plot";
  /** The view's place among the views of its kind. */
  index: number;
  id?: string;
  /** The table the view is picked or brushed on. */
  table?: string;
};

/** *value* as a list: none is an empty list, and one object a list of one. */
function asList(value: unknown): any[] {
  if (value === undefined || value === null) return [];
  return Array.isArray(value) ? value : [value];
}

/** A table a document names, its chip, `[!! input 0 !!]` or `[!! input_0 !!]`, read as the table it stands for. */
function tableNamed(ref: unknown): string | undefined {
  if (typeof ref !== "string" || ref.trim() === "") return undefined;
  const chip = /^\[!!\s*(.*?)\s*!!\]$/.exec(ref.trim());
  const name = chip ? chip[1].replace(/^input\s+(\d+)$/, "input_$1") : ref.trim();
  return name === "" ? undefined : name;
}

const idOf = (entry: any): string | undefined =>
  typeof entry?.id === "string" && entry.id !== "" ? entry.id : undefined;

/** The table a map is picked on: its first layer that picks, else its first. */
function pickTableOf(entry: any): string | undefined {
  const refs: any[] = Array.isArray(entry?.layerRefs) ? entry.layerRefs : [];
  return tableNamed((refs.find((ref) => ref?.isPick) ?? refs[0])?.dataRef);
}

/** The views of the document *written*, maps first; null when it does not read as a document, as while it is typed. */
export function documentViews(written: unknown): DocumentView[] | null {
  if (typeof written !== "string" || written.trim() === "") return null;
  let spec: any;
  try {
    spec = JSON.parse(withChipPlaceholders(written));
  } catch {
    return null;
  }
  if (!spec || typeof spec !== "object" || Array.isArray(spec)) return null;
  const views: DocumentView[] = [];
  asList(spec.map).forEach((entry, index) => {
    views.push({ kind: "map", index, ...(idOf(entry) ? { id: idOf(entry) } : {}), ...(pickTableOf(entry) ? { table: pickTableOf(entry) } : {}) });
  });
  asList(spec.plot).forEach((entry, index) => {
    const table = tableNamed(entry?.dataRef);
    views.push({ kind: "plot", index, ...(idOf(entry) ? { id: idOf(entry) } : {}), ...(table ? { table } : {}) });
  });
  return views;
}

/**
 * The ids of the views of a node of several views that have one, in their
 * panes' order, each once: the views an interaction edge can name by a dot.
 * None for a node of one view, whose own dot is its view's. Null when the
 * document does not read.
 */
export function viewDotIds(written: unknown): string[] | null {
  const views = documentViews(written);
  if (views === null) return null;
  if (views.length < 2) return [];
  return [...new Set(views.map((view) => view.id).filter((id): id is string => id !== undefined))];
}
