import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faMagnifyingGlass } from "@fortawesome/free-solid-svg-icons";
import { SortMode } from "./packTypes";
import styles from "./PackSearchRow.module.css";

export interface PackSearchRowProps {
  search: string;
  sort: SortMode;
  onSearchChange: (value: string) => void;
  onSortChange: (value: SortMode) => void;
}

/** Search input + sort select bar rendered below the drawer subtitle. */
export const PackSearchRow: React.FC<PackSearchRowProps> = ({
  search,
  sort,
  onSearchChange,
  onSortChange,
}) => (
  <div className={styles.searchRow}>
    <div className={styles.searchWrap}>
      <FontAwesomeIcon icon={faMagnifyingGlass} className={styles.searchIcon} aria-hidden />
      <input
        className={styles.searchInput}
        type="search"
        placeholder="Search packs, authors, keywords..."
        value={search}
        onChange={(e) => onSearchChange(e.target.value)}
      />
    </div>
    <select
      className={styles.sortSelect}
      value={sort}
      aria-label="Sort packs"
      onChange={(e) => onSortChange(e.target.value as SortMode)}
    >
      <option value="new">Sort: New</option>
      <option value="name">Sort: Name</option>
    </select>
  </div>
);

