/**
 * Shared helpers for datapool and dataset-catalog tabular previews.
 * Matches the column-oriented JSON shape produced by sandbox ``parseOutput``.
 */

export type TabularPreviewPayload = {
  dataType?: string;
  data?: Record<string, unknown> | { features?: Array<{ properties?: Record<string, unknown> }> };
};

export function rowsFromParseOutput(payload: TabularPreviewPayload): Record<string, unknown>[] {
  const { dataType, data } = payload;
  if (!data || typeof data !== "object") {
    return [];
  }

  if (dataType === "dataframe") {
    const columns = Object.keys(data as Record<string, unknown>);
    if (columns.length === 0) {
      return [];
    }
    const firstColumn = (data as Record<string, unknown>)[columns[0]];
    const indices = firstColumn && typeof firstColumn === "object"
      ? Object.keys(firstColumn as Record<string, unknown>)
      : [];
    return indices.map((index) => {
      const row: Record<string, unknown> = {};
      columns.forEach((column) => {
        const columnData = (data as Record<string, unknown>)[column];
        if (Array.isArray(columnData)) {
          row[column] = columnData[Number(index)];
        } else if (columnData && typeof columnData === "object") {
          row[column] = (columnData as Record<string, unknown>)[index];
        } else {
          row[column] = null;
        }
      });
      return row;
    });
  }

  if (dataType === "geodataframe" && "features" in data) {
    const features = (data as { features?: Array<{ properties?: Record<string, unknown> }> }).features;
    return (features || []).map((feature) => ({ ...(feature.properties || {}) }));
  }

  return [];
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
