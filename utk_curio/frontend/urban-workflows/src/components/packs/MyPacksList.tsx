import React from "react";
import { PackPayload } from "../../api/packsApi";
import styles from "./MyPacksList.module.css";

export interface MyPacksListProps {
  installed: PackPayload[];
  /** Map of dirName → catalog entry, used to detect pending updates. */
  catalogByDir: Map<string, PackPayload>;
}

/**
 * "Your packs" section shown on the Featured tab.
 * Renders a compact row for every installed pack, indicating whether an
 * update is available or how many nodes the pack provides.
 * Returns null when nothing is installed.
 */
export const MyPacksList: React.FC<MyPacksListProps> = ({ installed, catalogByDir }) => {
  if (installed.length === 0) return null;

  return (
    <>
      <p className={styles.sectionLabel}>Your packs · {installed.length} installed</p>
      <div className={styles.installedList}>
        {installed.map((pack) => {
          const catRow = catalogByDir.get(pack.dirName);
          const hasUpdate = catRow != null && catRow.version !== pack.version;
          return (
            <div key={pack.dirName} className={styles.installedRow}>
              <span className={styles.installedDot} aria-hidden />
              <span className={styles.installedName}>{pack.name}</span>
              <span className={styles.installedMeta}>
                v{pack.version}
                {hasUpdate ? " · update available" : ` · ${pack.kinds.length} nodes`}
              </span>
            </div>
          );
        })}
      </div>
    </>
  );
};

