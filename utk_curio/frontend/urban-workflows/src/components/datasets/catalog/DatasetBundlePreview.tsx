import React, { useEffect, useMemo, useState } from "react";
import { TabularPreviewTable } from "../../tables/TabularPreviewTable";
import { PreviewPagination } from "./PreviewPagination";
import {
  DATASET_FORMAT_LABEL,
  DatasetPreviewPart,
  DatasetPreviewResponse,
  datasetCatalogApi,
} from "../../../services/datasetCatalog";
import styles from "./DatasetBundlePreview.module.css";

export interface DatasetBundlePreviewProps {
  preview: DatasetPreviewResponse;
  datasetId: string;
  dataflowId?: string | null;
  liveOutputs?: Array<{ node_id: string; filename: string; data_type?: string }>;
  pageSize?: number;
}

export const DatasetBundlePreview: React.FC<DatasetBundlePreviewProps> = ({
  preview,
  datasetId,
  dataflowId = null,
  liveOutputs,
  pageSize = 6,
}) => {
  // The overview response carries every part's first page (offset 0) plus its
  // totalRows — enough for the tab bar and page 1. Deeper pages are fetched per
  // part on demand and cached by `${partIndex}:${page}`.
  const initialParts = preview.parts ?? [];
  const [activeIndex, setActiveIndex] = useState(0);
  const [pages, setPages] = useState<Record<number, number>>({});
  const [fetched, setFetched] = useState<Record<string, DatasetPreviewPart>>({});
  const [fetching, setFetching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A new dataset reuses this component instance — reset all per-part paging.
  useEffect(() => {
    setActiveIndex(0);
    setPages({});
    setFetched({});
    setError(null);
  }, [datasetId]);

  const activePage = pages[activeIndex] ?? 1;
  const basePart = initialParts[activeIndex] ?? null;
  const cacheKey = `${activeIndex}:${activePage}`;
  // totalRows is page-independent — always take it from the overview's part.
  const totalRows = basePart?.totalRows ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalRows / pageSize));

  // Page 1 is already in hand from the overview; later pages come from `fetched`.
  const activePart: DatasetPreviewPart | null =
    activePage === 1 ? basePart : fetched[cacheKey] ?? null;

  useEffect(() => {
    if (!basePart || activePage === 1 || fetched[cacheKey]) return;
    let cancelled = false;
    setFetching(true);
    void datasetCatalogApi
      .preview(datasetId, {
        dataflowId,
        liveOutputs,
        part: activeIndex,
        offset: (activePage - 1) * pageSize,
        rowLimit: pageSize,
      })
      .then((response) => {
        if (cancelled) return;
        setFetched((prev) => ({ ...prev, [cacheKey]: response as unknown as DatasetPreviewPart }));
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError((err as Error)?.message || "Could not load part page.");
      })
      .finally(() => {
        if (!cancelled) setFetching(false);
      });
    return () => {
      cancelled = true;
    };
  }, [datasetId, dataflowId, liveOutputs, activeIndex, activePage, cacheKey, pageSize, basePart, fetched]);

  const rows = useMemo(
    () => (activePart?.rows || []) as Record<string, unknown>[],
    [activePart?.rows],
  );

  if (initialParts.length === 0) {
    return (
      <div className={styles.state}>
        {preview.message || "This bundle has no previewable parts."}
      </div>
    );
  }

  // A page that hasn't arrived yet (fetch in flight / failed) leaves activePart null.
  const isLoadingPage = activePart == null && !error;
  const showTable = activePart != null && !activePart.unsupported;
  const offset = (activePage - 1) * pageSize;
  const rowCount = rows.length;
  const startRow = totalRows === 0 ? 0 : offset + 1;
  const endRow = totalRows === 0 ? 0 : Math.min(offset + rowCount, totalRows);

  return (
    <section className={styles.panel}>
      <div className={styles.tabBar} role="tablist" aria-label="Bundle parts">
        {initialParts.map((part, index) => (
          <button
            key={`${part.label}-${index}`}
            type="button"
            role="tab"
            aria-selected={index === activeIndex}
            className={index === activeIndex ? styles.tabActive : styles.tab}
            onClick={() => setActiveIndex(index)}
          >
            <span className={styles.tabLabel}>{part.label}</span>
            <span className={styles.tabFormat}>
              {DATASET_FORMAT_LABEL[part.format] ?? part.format}
            </span>
          </button>
        ))}
      </div>

      {activePart?.unsupported ? (
        <div className={styles.state}>
          {activePart.message || "Preview is not available for this part."}
        </div>
      ) : null}

      {isLoadingPage ? <div className={styles.state}>Loading page...</div> : null}
      {error ? <div className={styles.state}>{error}</div> : null}

      {showTable ? (
        <>
          <div className={`${styles.tableWrap} ${fetching ? styles.tableRefreshing : ""}`}>
            <TabularPreviewTable
              rows={rows}
              rowKeyPrefix={`${datasetId}-bundle-${activeIndex}-${offset}`}
              maxRows={pageSize}
              loading={fetching}
              emptyMessage={rowCount === 0 ? "No rows on this page." : "No rows in this part."}
            />
          </div>
          {totalRows > 0 ? (
            <PreviewPagination
              page={activePage}
              totalPages={totalPages}
              totalRows={totalRows}
              startRow={startRow}
              endRow={endRow}
              disabled={fetching}
              onPageChange={(next) =>
                setPages((prev) => ({ ...prev, [activeIndex]: next }))
              }
            />
          ) : (
            <p className={styles.partNote}>Scalar or metadata part</p>
          )}
        </>
      ) : null}
    </section>
  );
};
