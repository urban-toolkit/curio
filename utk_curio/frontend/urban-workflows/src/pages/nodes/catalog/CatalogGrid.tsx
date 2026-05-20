import React from "react";
import { PackPayload } from "../../../api/packsApi";
import { CatalogCard } from "./CatalogCard";
import styles from "./Catalog.module.css";

export interface CatalogGridProps {
  /** Pre-filtered packs to display (tab + search already applied by parent). */
  packs: PackPayload[];
  search: string;
  onSearchChange: (value: string) => void;
  installedDirs: ReadonlySet<string>;
  busy: boolean;
  onInstall: (pack: PackPayload) => void;
  onUninstall: (pack: PackPayload) => void;
}

/**
 * Search bar + scrollable grid of CatalogCard items for the catalog main area.
 * Filtering is done by the parent; this component only renders what it receives.
 */
export const CatalogGrid: React.FC<CatalogGridProps> = ({
  packs,
  search,
  onSearchChange,
  installedDirs,
  busy,
  onInstall,
  onUninstall,
}) => (
  <main className={styles.main}>
    <div className={styles.searchRow}>
      <input
        className={styles.search}
        type="search"
        placeholder="Search packs by name, publisher, or description"
        value={search}
        onChange={(e) => onSearchChange(e.target.value)}
      />
    </div>

    <div className={styles.catalogScroll}>
      {packs.length === 0 ? (
        <div className={styles.empty}>No packs match the current filter.</div>
      ) : (
        <div className={styles.grid}>
          {packs.map((pack) => (
            <CatalogCard
              key={pack.dirName}
              pack={pack}
              isInstalled={installedDirs.has(pack.dirName)}
              busy={busy}
              onInstall={onInstall}
              onUninstall={onUninstall}
            />
          ))}
        </div>
      )}
    </div>
  </main>
);

