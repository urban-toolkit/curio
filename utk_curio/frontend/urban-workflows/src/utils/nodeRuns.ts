/**
 * A node's runs, as `ProvenanceProvider` files them, turned into the items its
 * provenance history shows: each tagged with its number and named by the
 * kinds of data it read and returned. An edit made in the node's body (a Map
 * Edits node's Apply, Remove or put back) is named by what it changed.
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
