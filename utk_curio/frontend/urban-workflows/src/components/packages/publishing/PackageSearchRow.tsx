import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faMagnifyingGlass } from "@fortawesome/free-solid-svg-icons";
import { SortMode } from "./packageTypes";
import styles from "./PackageSearchRow.module.css";

export interface PackageSearchRowProps<S extends string = SortMode> {
  search: string;
  sort: S;
  onSearchChange: (value: string) => void;
  onSortChange: (value: S) => void;
  /** Catalog-flavored copy; defaults keep the package/dataset drawer strings. */
  placeholder?: string;
  sortAriaLabel?: string;
  /** Sort vocabulary. Defaults to the package pair; catalogs with their own
   * sort contract (e.g. datasets' "recent") pass matching options instead of
   * casting their state into SortMode (dev/74). */
  sortOptions?: { value: S; label: string }[];
}

const DEFAULT_SORT_OPTIONS: { value: SortMode; label: string }[] = [
  { value: "new", label: "Sort: New" },
  { value: "name", label: "Sort: Name" },
];

/** Search input + sort select bar rendered below the drawer subtitle. */
export function PackageSearchRow<S extends string = SortMode>({
  search,
  sort,
  onSearchChange,
  onSortChange,
  placeholder = "Search packages, authors, keywords...",
  sortAriaLabel = "Sort packages",
  sortOptions = DEFAULT_SORT_OPTIONS as { value: S; label: string }[],
}: PackageSearchRowProps<S>): React.ReactElement {
  return (
    <div className={styles.searchRow}>
      <div className={styles.searchWrap}>
        <FontAwesomeIcon icon={faMagnifyingGlass} className={styles.searchIcon} aria-hidden />
        <input
          className={styles.searchInput}
          type="search"
          placeholder={placeholder}
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
        />
      </div>
      <select
        className={styles.sortSelect}
        value={sort}
        aria-label={sortAriaLabel}
        onChange={(e) => onSortChange(e.target.value as S)}
      >
        {sortOptions.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}
