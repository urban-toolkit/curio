import React, { useMemo, useState } from "react";
import { TabularPreviewTable } from "../../tables/TabularPreviewTable";
import {
  DATASET_FORMAT_LABEL,
  DatasetPreviewPart,
  DatasetPreviewResponse,
} from "../../../services/datasetCatalog";
import styles from "./DatasetBundlePreview.module.css";

export interface DatasetBundlePreviewProps {
  preview: DatasetPreviewResponse;
  datasetId: string;
  pageSize?: number;
}

export const DatasetBundlePreview: React.FC<DatasetBundlePreviewProps> = ({
  preview,
  datasetId,
  pageSize = 6,
}) => {
  const parts = preview.parts ?? [];
  const [activeIndex, setActiveIndex] = useState(0);

  const activePart: DatasetPreviewPart | null = useMemo(
    () => parts[activeIndex] ?? null,
    [parts, activeIndex],
  );

  if (parts.length === 0) {
    return (
      <div className={styles.state}>
        {preview.message || "This bundle has no previewable parts."}
      </div>
    );
  }

  const rows = (activePart?.rows || []) as Record<string, unknown>[];
  const showTable = activePart != null && !activePart.unsupported;

  return (
    <section className={styles.panel}>
      <div className={styles.tabBar} role="tablist" aria-label="Bundle parts">
        {parts.map((part, index) => (
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

      {showTable ? (
        <div className={styles.tableWrap}>
          <TabularPreviewTable
            rows={rows}
            rowKeyPrefix={`${datasetId}-bundle-${activeIndex}`}
            maxRows={pageSize}
            emptyMessage="No rows in this part."
          />
          <p className={styles.partNote}>
            {activePart.totalRows > 0
              ? `${activePart.totalRows.toLocaleString()} row(s) in this part`
              : "Scalar or metadata part"}
          </p>
        </div>
      ) : null}
    </section>
  );
};
