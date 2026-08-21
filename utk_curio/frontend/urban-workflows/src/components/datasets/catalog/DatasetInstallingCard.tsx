import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faSpinner } from "@fortawesome/free-solid-svg-icons";
import type { PendingInstall } from "../../../services/datasetCatalog";
import styles from "../../packages/publishing/PackageCard.module.css";

/**
 * Non-interactive "Installing…" placeholder card for the Data Catalog drawer,
 * shown while a dataset install is in flight. Mirrors DatasetCard's shell with a
 * spinner avatar and no actions; replaced by the real DatasetCard once the
 * install lands.
 */
export const DatasetInstallingCard: React.FC<{ pending: PendingInstall }> = ({ pending }) => {
  return (
    <article
      className={styles.card}
      role="status"
      aria-busy="true"
      aria-label={`Installing ${pending.label}`}
      style={{ opacity: 0.7 }}
    >
      <div className={styles.cardAccent} />
      <div className={`${styles.cardAvatar} ${styles.cardAvatarButton}`}>
        <FontAwesomeIcon icon={faSpinner} spin aria-hidden="true" className={styles.cardIcon} />
      </div>
      <div className={styles.cardBody}>
        <h3 className={styles.cardTitle}>{pending.label}</h3>
        <div className={styles.cardMetaRow}>
          <span className={styles.cardMetaText}>Installing…</span>
        </div>
      </div>
    </article>
  );
};
