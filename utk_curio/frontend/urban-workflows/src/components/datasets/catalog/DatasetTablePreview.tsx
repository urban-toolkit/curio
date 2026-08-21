import React, { useEffect, useMemo, useState } from "react";
import { TabularPreviewTable } from "../../tables/TabularPreviewTable";
import { DatasetBundlePreview } from "./DatasetBundlePreview";
import { PreviewPagination } from "./PreviewPagination";
import {
  DatasetCatalogItem,
  DatasetPreviewResponse,
  datasetCatalogApi,
} from "../../../services/datasetCatalog";
import styles from "./DatasetTablePreview.module.css";

const PAGE_SIZE = 6;

function formatTotal(total: number): string {
  return total.toLocaleString();
}

export interface DatasetTablePreviewProps {
  dataset: DatasetCatalogItem;
  dataflowId?: string | null;
  liveOutputs?: Array<{ node_id: string; filename: string; data_type?: string }>;
}

export const DatasetTablePreview: React.FC<DatasetTablePreviewProps> = ({
  dataset,
  dataflowId = null,
  liveOutputs,
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
      .preview(dataset.id, { dataflowId, liveOutputs, offset, rowLimit: PAGE_SIZE })
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
  }, [dataflowId, dataset.id, liveOutputs, offset]);

  const previewRows = useMemo(
    () => (preview?.rows || []) as Record<string, unknown>[],
    [preview?.rows],
  );

  const totalRows = preview?.totalRows
    ?? dataset.featureCount
    ?? dataset.rowCount
    ?? 0;
  const displayOffset = preview?.offset ?? offset;
  const rowCount = preview?.rows.length ?? 0;
  const startRow = totalRows === 0 ? 0 : displayOffset + 1;
  const endRow = totalRows === 0 ? 0 : Math.min(displayOffset + rowCount, totalRows);
  const totalPages = Math.max(1, Math.ceil(totalRows / PAGE_SIZE));
  const isBundle = preview?.bundle === true && (preview.parts?.length ?? 0) > 0;
  const partCount = preview?.parts?.length ?? 0;
  const rangeLabel = isBundle
    ? `${partCount} ${partCount === 1 ? "part" : "parts"}`
    : totalRows === 0
      ? "No rows to preview"
      : `Showing rows ${startRow}-${endRow} of ${formatTotal(totalRows)}`;
  const showTable = preview != null && !preview.unsupported && !error && !isBundle;

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
      {!isInitialLoad && preview?.unsupported && !isBundle ? (
        <div className={styles.state}>{preview.message || "Preview is not available for this dataset yet."}</div>
      ) : null}

      {!isInitialLoad && isBundle && preview ? (
        <DatasetBundlePreview
          preview={preview}
          datasetId={dataset.id}
          dataflowId={dataflowId}
          liveOutputs={liveOutputs}
          pageSize={PAGE_SIZE}
        />
      ) : null}

      {showTable ? (
        <>
          <div className={`${styles.tableWrap} ${isRefreshing ? styles.tableRefreshing : ""}`}>
            <TabularPreviewTable
              rows={previewRows}
              rowKeyPrefix={`${dataset.id}-${displayOffset}`}
              maxRows={PAGE_SIZE}
              loading={isRefreshing}
              emptyMessage={rowCount === 0 ? "No rows on this page." : "No rows to preview"}
            />
          </div>

          <PreviewPagination
            page={page}
            totalPages={totalPages}
            totalRows={totalRows}
            startRow={startRow}
            endRow={endRow}
            disabled={isRefreshing}
            onPageChange={setPage}
          />
          {error ? <div className={styles.inlineError}>{error}</div> : null}
        </>
      ) : null}
    </section>
  );
};
