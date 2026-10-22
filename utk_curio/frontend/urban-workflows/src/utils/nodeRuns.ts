/**
 * A node's runs, as `ProvenanceProvider` files them, turned into the items its
 * provenance history shows: each tagged with its number and named by the
 * kinds of data it read and returned. An edit made in the node's body (a Map
 * Edits node's action, or an entry of its list switched off or deleted) is
 * named by what it changed. Undo and Redo walk the same tree (`undoStep`,
 * `redoStep`).
 */
import type { NodeExecRecord } from "../providers/ProvenanceProvider";
import type { HistoryItem } from "./provenanceTree";

/** The history's items, in the order the runs and edits were filed. */
export function runItems(records: readonly NodeExecRecord[]): HistoryItem[] {
  const ids = new Set(records.map((record) => record.id));
  return records.map((record, i) => {
    const at = runTime(record.startTime);
    return {
      id: String(record.id),
      parentId: record.parentId != null && ids.has(record.parentId) ? String(record.parentId) : null,
      order: i,
      tag: String(record.id),
      title: entryTitle(record),
      when: at ? at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "",
      tooltip: at ? at.toLocaleString() : record.startTime || undefined,
    };
  });
}

/** Whether *record* is an edit, which ran nothing. */
export function isEdit(record: Pick<NodeExecRecord, "kind">): boolean {
  return record.kind === "edit";
}

/** What an entry's row reads: an edit's label ("remove building_id 12"), or a run's kinds of data. */
export function entryTitle(record: Pick<NodeExecRecord, "inputs" | "outputs" | "kind" | "label">): string {
  return isEdit(record) ? record.label || "Edit" : runKinds(record);
}

/** Where an Undo or a Redo goes: the code it puts back, and the entry the node's next one branches from. */
export interface HistoryStep {
  code: string;
  /** Null: before the node's first entry. */
  current: number | null;
}

/**
 * What Undo puts back from the entry *currentId* while the node holds *code*:
 * that entry's code when the node holds another, else the entry before it,
 * the parent, or the code an edit kept (`before`) when no entry holds it.
 * Entries that hold the code the node holds already, as a run of an edit
 * does, are passed over. Null when there is nothing before.
 */
export function undoStep(records: readonly NodeExecRecord[], currentId: number | null | undefined, code: string): HistoryStep | null {
  const byId = new Map(records.map((record) => [record.id, record]));
  let entry = currentId == null ? undefined : byId.get(currentId);
  if (entry && entry.code !== code) return { code: entry.code, current: entry.id };
  // A saved history whose parents run in a circle ends the walk.
  const seen = new Set<number>();
  while (entry && !seen.has(entry.id)) {
    seen.add(entry.id);
    const parent = entry.parentId == null ? undefined : byId.get(entry.parentId);
    const back = entry.before ?? parent?.code;
    if (back === undefined) return null;
    if (back !== code) return { code: back, current: parent?.id ?? null };
    entry = parent;
  }
  return null;
}

/**
 * What Redo puts back from the entry *currentId* (null: before the first) while
 * the node holds *code*: its newest child's code, passing over children that
 * hold that code already. Null when no entry comes after it.
 */
export function redoStep(records: readonly NodeExecRecord[], currentId: number | null | undefined, code: string): HistoryStep | null {
  const ids = new Set(records.map((record) => record.id));
  const childrenOf = (id: number | null) =>
    records.filter((record) => (id === null ? record.parentId == null || !ids.has(record.parentId) : record.parentId === id));
  let at: number | null = currentId ?? null;
  const seen = new Set<number>();
  for (;;) {
    const newest = childrenOf(at).reduce<NodeExecRecord | null>((best, record) => (best === null || record.id > best.id ? record : best), null);
    if (newest === null || seen.has(newest.id)) return null;
    if (newest.code !== code) return { code: newest.code, current: newest.id };
    seen.add(newest.id);
    at = newest.id;
  }
}

/** "In: DATAFRAME | Out: GEODATAFRAME": the kinds of data a run read and
 *  returned, ERROR for a run that failed, "none" for a side with none. */
export function runKinds(record: Pick<NodeExecRecord, "inputs" | "outputs">): string {
  const side = (kinds: readonly string[]) => (kinds.length > 0 ? kinds.join(", ") : "none");
  return `In: ${side(record.inputs)} | Out: ${side(record.outputs)}`;
}

/** A time a run was filed with (`formatDate` in utils/formatters), or null. */
export function runTime(text: string | null | undefined): Date | null {
  if (!text) return null;
  const at = new Date(text);
  return Number.isNaN(at.getTime()) ? null : at;
}

/** How long a run took, to the second its times are filed with: "3 s", or
 *  "under a second"; null when either time is missing. */
export function runDuration(record: Pick<NodeExecRecord, "startTime" | "endTime">): string | null {
  const start = runTime(record.startTime);
  const end = runTime(record.endTime);
  if (!start || !end) return null;
  const seconds = Math.round((end.getTime() - start.getTime()) / 1000);
  return seconds < 1 ? "under a second" : `${seconds} s`;
}
