import React from "react";
import { PackPayload } from "../../../api/packsApi";
import { formatForkOfSubtitle } from "../../../utils/forkPackLineage";
import styles from "./Catalog.module.css";

export interface CatalogCardProps {
  pack: PackPayload;
  isInstalled: boolean;
  busy: boolean;
  onInstall: (pack: PackPayload) => void;
  onUninstall: (pack: PackPayload) => void;
}

/**
 * A single pack card in the catalog grid.
 * Shows name, publisher, description, fork-of line, node-kind chips,
 * and an Install / Uninstall action button.
 */
export const CatalogCard: React.FC<CatalogCardProps> = React.memo(
  function CatalogCard({ pack, isInstalled, busy, onInstall, onUninstall }) {
    const forkSubtitle = pack.lineage ? formatForkOfSubtitle(pack.lineage) : null;

    return (
      <article className={styles.card}>
        <div className={styles.cardHeader}>
          <div>
            <h3 className={styles.packName}>{pack.name}</h3>
            <span className={styles.publisher}>{pack.publisher || pack.packId}</span>
          </div>
          <div className={styles.cardHeaderAside}>
            {isInstalled ? (
              <span className={styles.installedTag}>Installed</span>
            ) : (
              <span className={styles.tag}>v{pack.version}</span>
            )}
            {(pack.channel ?? "stable") !== "stable" ? (
              <span className={styles.channelChip} title={`Release channel: ${pack.channel}`}>
                {pack.channel}
              </span>
            ) : null}
          </div>
        </div>

        <p className={styles.description}>{pack.description || "No description."}</p>

        {forkSubtitle ? (
          <p className={styles.catalogForkLine} title={forkSubtitle.title}>
            {forkSubtitle.text}
          </p>
        ) : null}

        <div className={styles.kinds}>
          {pack.kinds.slice(0, 4).map((k) => (
            <span key={k.kindId} className={styles.kindChip}>
              {k.label}
            </span>
          ))}
        </div>

        <div className={styles.versionRow}>
          <span className={styles.publisher}>
            {pack.kinds.length} node{pack.kinds.length === 1 ? "" : "s"}
          </span>
          {isInstalled ? (
            <button
              type="button"
              className={styles.ghostButton}
              disabled={busy}
              onClick={() => onUninstall(pack)}
            >
              Uninstall
            </button>
          ) : (
            <button
              type="button"
              className={styles.actionButton}
              disabled={busy}
              onClick={() => onInstall(pack)}
            >
              Install
            </button>
          )}
        </div>
      </article>
    );
  },
);

