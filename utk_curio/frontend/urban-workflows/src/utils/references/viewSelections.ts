/**
 * What a selection tag reads from its view (#662): the rows the view matches
 * a selection against, and the selection the view made last.
 *
 * A view hands over its rows here as it holds them: a Vega-Lite node the rows
 * it draws (whose positions its point selections name), an Autark node the
 * features of each layer it reads (whose positions its picks name). Nothing is
 * fetched again. The flow records each view's latest selection as the view
 * reports it (`useSelectionTags`), so a tag added later starts from it.
 */
import type { SelectDetail, SelectionRows } from "../selectionMatch";
import { selectedIds, selectionLayer, type SelectionState } from "./selectionTags";

/** A view's rows: how to read them, and the columns they have. */
export interface ViewRows {
  rows: SelectionRows;
  columns: string[];
}

/** What a view answers with: the rows of *layer* (an Autark layer, by its
 * table name), or of the layer its picks come from when none is named. Null
 * while it holds none, before its first draw. */
export type ViewRowsProvider = (layer?: string) => ViewRows | null | Promise<ViewRows | null>;

export type ViewDetails = Record<string, SelectDetail>;

const providers = new Map<string, ViewRowsProvider>();
const latest = new Map<string, ViewDetails>();

/** Hand over a view's rows. Returns what takes them back, for an unmount. */
export function provideViewRows(nodeId: string, provider: ViewRowsProvider): () => void {
  providers.set(nodeId, provider);
  return () => {
    if (providers.get(nodeId) === provider) providers.delete(nodeId);
  };
}

/** The rows the view *nodeId* holds, or null when it holds none. */
export async function viewRowsOf(nodeId: string, layer?: string): Promise<ViewRows | null> {
  const provider = providers.get(nodeId);
  if (!provider) return null;
  try {
    return (await provider(layer)) ?? null;
  } catch {
    return null;
  }
}

/** Record the selection the view *nodeId* made last. */
export function recordViewSelection(nodeId: string, details: unknown): void {
  if (details && typeof details === "object") latest.set(nodeId, details as ViewDetails);
}

/** The selection the view *nodeId* made last, if it made one. */
export function latestViewSelection(nodeId: string): ViewDetails | undefined {
  return latest.get(nodeId);
}

/**
 * What the selection *details* of the view *nodeId* hold for a tag on
 * *column*: its ids, or how many there were. Null when the view holds no rows
 * yet, so nothing can be read.
 */
export async function selectionStateOf(
  nodeId: string,
  column: string,
  details: ViewDetails | undefined = latestViewSelection(nodeId),
): Promise<SelectionState | null> {
  const held = await viewRowsOf(nodeId, selectionLayer(details));
  if (!held) return null;
  return selectedIds(details, held.rows, column);
}

/** The columns of a view's rows that are its own: everything but what the
 * view adds (Vega's ids and Curio's row stamps are left out by `idColumns`). */
export function columnsOfRows(rows: readonly any[]): string[] {
  const first = rows.find((row) => row && typeof row === "object");
  return first ? Object.keys(first) : [];
}

/** Forget every view, between tests. */
export function resetViewSelections(): void {
  providers.clear();
  latest.clear();
}
