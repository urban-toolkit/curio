import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faMagnifyingGlass } from "@fortawesome/free-solid-svg-icons";
import styles from "./PackageSearchRow.module.css";

export interface SearchRowSortOption {
  value: string;
  label: string;
}

export interface PackageSearchRowProps {
  search: string;
  sort: string;
  onSearchChange: (value: string) => void;
  onSortChange: (value: string) => void;
  /** Defaults to the package-catalog copy; the dataset drawer overrides these. */
  placeholder?: string;
  sortAriaLabel?: string;
  sortOptions?: SearchRowSortOption[];
}

const PACKAGE_SORT_OPTIONS: SearchRowSortOption[] = [
  { value: "new", label: "Sort: Newest" },
  { value: "name", label: "Sort: Name" },
];

/** Search input + sort select bar rendered below the drawer subtitle. */
export const PackageSearchRow: React.FC<PackageSearchRowProps> = ({
  search,
  sort,
  onSearchChange,
  onSortChange,
  placeholder = "Search packages, publishers, tags…",
  sortAriaLabel = "Sort packages",
  sortOptions = PACKAGE_SORT_OPTIONS,
}) => (
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
      onChange={(e) => onSortChange(e.target.value)}
    >
      {sortOptions.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  </div>
);
