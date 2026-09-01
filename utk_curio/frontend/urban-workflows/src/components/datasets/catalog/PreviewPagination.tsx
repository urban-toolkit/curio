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

type PageItem = number | "ellipsis";

const numberRange = (start: number, end: number): number[] =>
  Array.from({ length: Math.max(0, end - start + 1) }, (_, index) => start + index);

/** Compact page list: the first page(s), a window around the current page, and
 *  the last page(s), with "ellipsis" markers for the skipped spans. When only a
 *  single page would be hidden, it is shown instead of an ellipsis (so the count
 *  of slots stays stable and no ellipsis ever stands in for one page).
 *
 *  ``boundaryCount`` pages are pinned at each end; ``siblingCount`` pages sit on
 *  each side of the current page. Example (current 6 of 20):
 *  ``1 … 5 6 7 … 20``. */
export function getPageItems(
  page: number,
  totalPages: number,
  siblingCount = 1,
  boundaryCount = 1,
): PageItem[] {
  // Everything fits: 2 boundaries + 2 ellipses + (2*siblings + 1) current block.
  const totalSlots = boundaryCount * 2 + siblingCount * 2 + 3;
  if (totalPages <= totalSlots) return numberRange(1, totalPages);

  const startPages = numberRange(1, boundaryCount);
  const endPages = numberRange(totalPages - boundaryCount + 1, totalPages);

  // Clamp the sibling window so it never overlaps the pinned boundary pages.
  const siblingsStart = Math.max(
    Math.min(page - siblingCount, totalPages - boundaryCount - siblingCount * 2 - 1),
    boundaryCount + 2,
  );
  const siblingsEnd = Math.min(
    Math.max(page + siblingCount, boundaryCount + siblingCount * 2 + 2),
    endPages[0] - 2,
  );

  return [
    ...startPages,
    // Left gap: an ellipsis, or the lone hidden page if exactly one is skipped.
    ...(siblingsStart > boundaryCount + 2
      ? (["ellipsis"] as PageItem[])
      : boundaryCount + 1 < totalPages - boundaryCount
        ? [boundaryCount + 1]
        : []),
    ...numberRange(siblingsStart, siblingsEnd),
    // Right gap: same rule, mirrored.
    ...(siblingsEnd < totalPages - boundaryCount - 1
      ? (["ellipsis"] as PageItem[])
      : totalPages - boundaryCount > boundaryCount
        ? [totalPages - boundaryCount]
        : []),
    ...endPages,
  ];
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
        {getPageItems(page, totalPages).map((item, index) =>
          item === "ellipsis" ? (
            <span key={`ellipsis-${index}`} className={styles.pageEllipsis} aria-hidden="true">
              …
            </span>
          ) : (
            <button
              key={item}
              type="button"
              className={`${styles.pageButton} ${item === page ? styles.pageButtonActive : ""}`}
              disabled={disabled}
              aria-label={`Page ${item}`}
              aria-current={item === page ? "page" : undefined}
              onClick={() => onPageChange(item)}
            >
              {item}
            </button>
          ),
        )}
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
