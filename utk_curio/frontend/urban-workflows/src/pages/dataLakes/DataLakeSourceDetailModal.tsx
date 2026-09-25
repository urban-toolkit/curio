import React from "react";

import ModalShell from "../../components/ModalShell";
import { CatalogDetailHeader } from "../../components/catalog/CatalogDetailHeader";
import {
  LAKE_AUTH_LABEL,
  LAKE_PROVIDER_LABEL,
  unsearchableReason,
  type LakeSourceRow,
} from "../../services/dataLakeCatalog";
import { lakeSourceAccessItems, lakeSourceInfoRows } from "./lakeSourceFacts";
import styles from "../../components/agents/catalog/AgentDetailModal.module.css";

export interface DataLakeSourceDetailModalProps {
  source: LakeSourceRow;
  onBrowse: (source: LakeSourceRow) => void;
  onClose: () => void;
}

/**
 * "View details" for one data portal, the Data Lake Catalog's answer to
 * `PackageDetailModal`, `AgentDetailModal` and `DatasetDetailModal`.
 *
 * The lake page was the one catalog with no details view: a source's endpoint,
 * licence, formats, download cap and token help were in the right-hand drawer
 * and nowhere else, and below 1100px `CatalogBrowseLayout.module.css` hides the
 * drawer column outright. The rows come from `lakeSourceFacts`, the same ones
 * the drawer renders.
 */
export const DataLakeSourceDetailModal: React.FC<DataLakeSourceDetailModalProps> = ({
  source,
  onBrowse,
  onClose,
}) => {
  const blocked = unsearchableReason(source);
  const access = lakeSourceAccessItems(source);
  const rows = [...lakeSourceInfoRows(source), { label: "Identifier", value: source.sourceId }];

  return (
    <ModalShell onClose={onClose} size="xlarge" layer="overlay" label="Data lake details">
      <CatalogDetailHeader
        kind="lake"
        title={source.name}
        subtitle={
          <>
            {source.publisher || "Unknown publisher"} ·{" "}
            {LAKE_PROVIDER_LABEL[source.provider] ?? source.provider} ·{" "}
            {LAKE_AUTH_LABEL[source.auth.mode] ?? source.auth.mode}
          </>
        }
        actions={
          // The drawer's primary action. A source that cannot be searched says
          // why in the body instead, as the drawer does.
          blocked ? null : (
            <button
              type="button"
              className={styles.exportButton}
              onClick={() => onBrowse(source)}
            >
              Browse datasets
            </button>
          )
        }
      />

      <div className={styles.body}>
        {source.description ? <p className={styles.purpose}>{source.description}</p> : null}
        {blocked ? <p className={styles.purpose}>{blocked}</p> : null}

        <section className={styles.section}>
          <h3 className={styles.sectionLabel}>Source</h3>
          <dl className={styles.infoGrid}>
            {rows.map(({ label, value }) => (
              <React.Fragment key={label}>
                <dt className={styles.infoLabel}>{label}</dt>
                <dd className={styles.infoValue}>{value}</dd>
              </React.Fragment>
            ))}
          </dl>
        </section>

        {access.length > 0 ? (
          <section className={styles.section}>
            <h3 className={styles.sectionLabel}>Access</h3>
            <ul className={styles.list}>{access}</ul>
          </section>
        ) : null}

        {source.tags.length > 0 ? (
          <section className={styles.section}>
            <h3 className={styles.sectionLabel}>Tags</h3>
            <p className={styles.purpose}>{source.tags.join(", ")}</p>
          </section>
        ) : null}
      </div>
    </ModalShell>
  );
};

export default DataLakeSourceDetailModal;
