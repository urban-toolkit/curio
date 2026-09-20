import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faSpinner, faTriangleExclamation } from "@fortawesome/free-solid-svg-icons";
import type { PendingInstall } from "../../../services/datasetCatalog";
import styles from "../../packages/publishing/PackageCard.module.css";

/**
 * Non-interactive "Adding…" placeholder card for the Data Catalog drawer, shown
 * while a dataset install is in flight. Mirrors DatasetCard's shell with a
 * spinner avatar and no actions; replaced by the real DatasetCard once the
 * install lands. A failed install says so rather than vanishing (#352).
 */
export const DatasetInstallingCard: React.FC<{ pending: PendingInstall }> = ({ pending }) => {
  const failed = pending.status === "failed";
  return (
    <article
      className={styles.card}
      role="status"
      aria-busy={failed ? "false" : "true"}
      aria-label={failed ? `Could not add ${pending.label}` : `Adding ${pending.label}`}
      style={{ opacity: 0.7 }}
    >
      <div className={`${styles.cardAvatar} ${styles.cardAvatarButton}`}>
        <FontAwesomeIcon
          icon={failed ? faTriangleExclamation : faSpinner}
          spin={!failed}
          aria-hidden="true"
          className={styles.cardIcon}
        />
      </div>
      <div className={styles.cardBody}>
        <h3 className={styles.cardTitle}>{pending.label}</h3>
        <div className={styles.cardMetaRow}>
          <span className={styles.cardMetaText}>
            {failed ? "Couldn't be added" : "Adding…"}
          </span>
        </div>
      </div>
    </article>
  );
};
