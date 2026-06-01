import React, { useEffect, useMemo, useState } from "react";
import {
  DatasetCatalogItem,
  DatasetPreviewResponse,
  DatasetSchemaField,
  datasetCatalogApi,
} from "../../../services/datasetCatalog";
import styles from "./DatasetTablePreview.module.css";

const PAGE_SIZE = 6;

function formatCell(value: unknown): string {
  if (value == null || value === "") return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function cellTone(field: DatasetSchemaField | undefined, columnIndex: number): string {
  const type = (field?.type || "").toLowerCase();
  if (columnIndex === 0 || type.includes("int") || field?.name.endsWith("_id")) {
    return styles.cellId;
  }
  if (type.includes("float") || type.includes("number") || type.includes("double")) {
    return styles.cellNumber;
  }
  return styles.cellText;
}

function formatTotal(total: number): string {
  return total.toLocaleString();
}

export interface DatasetTablePreviewProps {
  dataset: DatasetCatalogItem;
  dataflowId?: string | null;
}

export const DatasetTablePreview: React.FC<DatasetTablePreviewProps> = ({
  dataset,
  dataflowId = null,
}) => {
  const [page, setPage] = useState(1);
  const [preview, setPreview] = useState<DatasetPreviewResponse | null>(null);
  const [fetching, setFetching] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const offset = (page - 1) * PAGE_SIZE;
  const isInitialLoad = fetching && !preview;
  const isRefreshing = fetching && preview != null;

  useEffect(() => {
    setPage(1);
    setPreview(null);
    setError(null);
  }, [dataset.id]);

  useEffect(() => {
    let cancelled = false;
    setFetching(true);
    void datasetCatalogApi
      .preview(dataset.id, { dataflowId, offset, rowLimit: PAGE_SIZE })
      .then((response) => {
        if (!cancelled) {
          setPreview(response);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError((err as Error)?.message || "Could not load preview.");
        }
      })
      .finally(() => {
        if (!cancelled) setFetching(false);
      });
    return () => {
      cancelled = true;
    };
  }, [dataflowId, dataset.id, offset]);

  const columns = useMemo(() => {
    const schemaFields = preview?.schema?.fields?.length
      ? preview.schema.fields
      : dataset.schema?.fields || [];
    if (schemaFields.length > 0) {
      return schemaFields.map((field) => field.name);
    }
    const firstRow = preview?.rows?.[0];
    if (firstRow && typeof firstRow === "object") {
      return Object.keys(firstRow);
    }
    return [];
  }, [dataset.schema?.fields, preview]);

  const fieldByName = useMemo(() => {
    const map = new Map<string, DatasetSchemaField>();
    for (const field of preview?.schema?.fields || dataset.schema?.fields || []) {
      map.set(field.name, field);
    }
    return map;
  }, [dataset.schema?.fields, preview?.schema?.fields]);

  const totalRows = preview?.totalRows
    ?? dataset.featureCount
    ?? dataset.rowCount
    ?? 0;
  const displayOffset = preview?.offset ?? offset;
  const rowCount = preview?.rows.length ?? 0;
  const startRow = totalRows === 0 ? 0 : displayOffset + 1;
  const endRow = totalRows === 0 ? 0 : Math.min(displayOffset + rowCount, totalRows);
  const totalPages = Math.max(1, Math.ceil(totalRows / PAGE_SIZE));
  const rangeLabel = totalRows === 0
    ? "No rows to preview"
    : `Showing rows ${startRow}-${endRow} of ${formatTotal(totalRows)}`;
  const showTable = preview != null && !preview.unsupported && !error;

  return (
    <section className={styles.panel}>
      <div className={styles.toolbar}>
        <span className={styles.toolbarNote}>{rangeLabel}</span>
        <button type="button" className={styles.columnsButton}>
          Columns
        </button>
      </div>

      {isInitialLoad ? <div className={styles.state}>Loading preview...</div> : null}
      {error && !preview ? <div className={styles.stateError}>{error}</div> : null}
      {!isInitialLoad && preview?.unsupported ? (
        <div className={styles.state}>{preview.message || "Preview is not available for this dataset yet."}</div>
      ) : null}

      {showTable ? (
        <>
          <div className={`${styles.tableWrap} ${isRefreshing ? styles.tableRefreshing : ""}`}>
            <table className={styles.table}>
              <thead>
                <tr>
                  {columns.map((column) => (
                    <th key={column}>{column}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row, rowIndex) => (
                  <tr key={`${displayOffset + rowIndex}`} className={rowIndex % 2 === 0 ? styles.rowTint : undefined}>
                    {columns.map((column, columnIndex) => (
                      <td
                        key={`${column}-${rowIndex}`}
                        className={cellTone(fieldByName.get(column), columnIndex)}
                      >
                        {formatCell((row as Record<string, unknown>)[column])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {rowCount === 0 ? <div className={styles.emptyRows}>No rows on this page.</div> : null}
          </div>

          <div className={styles.pagination}>
            <span className={styles.paginationNote}>
              {totalRows === 0 ? "Showing 0 of 0" : `Showing ${startRow}-${endRow} of ${formatTotal(totalRows)}`}
            </span>
            <div className={styles.paginationControls}>
              <button
                type="button"
                className={styles.pageButton}
                disabled={page <= 1 || isRefreshing}
                aria-label="Previous page"
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              >
                -
              </button>
              {Array.from({ length: Math.min(totalPages, 3) }, (_, index) => {
                const pageNumber = page <= 2 ? index + 1 : page - 1 + index;
                if (pageNumber > totalPages) return null;
                return (
                  <button
                    key={pageNumber}
                    type="button"
                    className={`${styles.pageButton} ${pageNumber === page ? styles.pageButtonActive : ""}`}
                    disabled={isRefreshing}
                    onClick={() => setPage(pageNumber)}
                  >
                    {pageNumber}
                  </button>
                );
              })}
              <button
                type="button"
                className={styles.pageButton}
                disabled={page >= totalPages || isRefreshing || totalRows === 0}
                aria-label="Next page"
                onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
              >
                +
              </button>
            </div>
          </div>
          {error ? <div className={styles.inlineError}>{error}</div> : null}
        </>
      ) : null}
    </section>
  );
};
