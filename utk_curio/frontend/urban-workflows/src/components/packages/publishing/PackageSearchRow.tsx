import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faMagnifyingGlass } from "@fortawesome/free-solid-svg-icons";
import { SortMode } from "./packageTypes";
import styles from "./PackageSearchRow.module.css";

export interface SearchRowSortOption<S extends string = SortMode> {
  value: S;
  label: string;
}

export interface PackageSearchRowProps<S extends string = SortMode> {
  search: string;
  sort: S;
  onSearchChange: (value: string) => void;
  onSortChange: (value: S) => void;
  /** Defaults to the package-catalog copy; the dataset drawer overrides these. */
  placeholder?: string;
  sortAriaLabel?: string;
  /** Sort vocabulary. Defaults to the package pair; a catalog with its own
   * sort contract (datasets' "recent", agents') passes matching options
   * instead of casting its state into SortMode. */
  sortOptions?: SearchRowSortOption<S>[];
}

const PACKAGE_SORT_OPTIONS: SearchRowSortOption<SortMode>[] = [
  { value: "new", label: "Sort: Newest" },
  { value: "name", label: "Sort: Name" },
];

/** Search input + sort select bar rendered below the drawer subtitle. */
export function PackageSearchRow<S extends string = SortMode>({
  search,
  sort,
  onSearchChange,
  onSortChange,
  placeholder = "Search packages, publishers, tags…",
  sortAriaLabel = "Sort packages",
  sortOptions = PACKAGE_SORT_OPTIONS as SearchRowSortOption<S>[],
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
        {sortOptions.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
