/**
 * What a tab of a Data Pool holds (hook/useTableData): a table, whose rows it
 * shows and flags; a raster, which it says it is, in the words an input chip's
 * preview says it in; or any other value, which is not tabular. The pool hands
 * every tab on.
 */
import { isTabularPayload } from "./nodeEmptyState";
import { RASTER_DATA_TYPE } from "./raster/rasterWire";

export type PoolTabKind = "table" | "raster" | "value";

/** What a raster's tab says. */
export const RASTER_TAB_TITLE = "A raster";

/** The kind of a tab: a raster, a value that names another type, else a table. */
export function poolTabKind(tab: unknown): PoolTabKind {
  const dataType = tab && typeof tab === "object" ? (tab as { dataType?: unknown }).dataType : undefined;
  if (dataType === RASTER_DATA_TYPE) return "raster";
  if (typeof dataType === "string" && !isTabularPayload(tab)) return "value";
  return "table";
}
