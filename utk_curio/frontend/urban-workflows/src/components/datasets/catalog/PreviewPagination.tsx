import React from "react";
import styles from "./PreviewPagination.module.css";

export interface PreviewPaginationProps {
  page: number;
  totalPages: number;
  totalRows: number;
  startRow: number;
  endRow: number;
  disabled?: boolean;
  onPageChange: (page: number) => void;
}

/** Row-range note + prev/numbered/next controls, shared by the top-level table
 *  preview and each bundle part tab so pagination looks and behaves identically. */
export const PreviewPagination: React.FC<PreviewPaginationProps> = ({
  page,
  totalPages,
  totalRows,
  startRow,
  endRow,
  disabled = false,
  onPageChange,
}) => {
  return (
    <div className={styles.pagination}>
      <span className={styles.paginationNote}>
        {totalRows === 0
          ? "Showing 0 of 0"
          : `Showing ${startRow}-${endRow} of ${totalRows.toLocaleString()}`}
      </span>
      <div className={styles.paginationControls}>
        <button
          type="button"
          className={styles.pageButton}
          disabled={page <= 1 || disabled}
          aria-label="Previous page"
          onClick={() => onPageChange(Math.max(1, page - 1))}
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
              disabled={disabled}
              onClick={() => onPageChange(pageNumber)}
            >
              {pageNumber}
            </button>
          );
        })}
        <button
          type="button"
          className={styles.pageButton}
          disabled={page >= totalPages || disabled || totalRows === 0}
          aria-label="Next page"
          onClick={() => onPageChange(Math.min(totalPages, page + 1))}
        >
          +
        </button>
      </div>
    </div>
  );
};
