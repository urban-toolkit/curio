/**
 * Shared helpers for datapool and dataset-catalog tabular previews.
 * Matches the column-oriented JSON shape produced by sandbox ``parseOutput``.
 */
import { toRows } from "./rowSource";

export type TabularPreviewPayload = {
  dataType?: string;
  data?: Record<string, unknown> | { features?: Array<{ properties?: Record<string, unknown> }> };
};

export function rowsFromParseOutput(payload: TabularPreviewPayload): Record<string, unknown>[] {
  // One implementation, in utils/rowSource. Eager here: these are preview
  // payloads of at most 100 rows and the callers treat them as arrays.
  return toRows(payload as any);
}

/** How many rows the table a `/get-preview` payload was cut from has, when it says. */
export function previewTotalRows(payload: unknown): number | undefined {
  const total = (payload as { totalRows?: unknown } | null)?.totalRows;
  return typeof total === "number" && Number.isFinite(total) ? total : undefined;
}

export function visiblePreviewColumns(
  rows: Record<string, unknown>[],
  excludeColumns: string[] = [],
): string[] {
  if (rows.length === 0) {
    return [];
  }
  const excluded = new Set(excludeColumns);
  return Object.keys(rows[0]).filter((column) => !excluded.has(column));
}
