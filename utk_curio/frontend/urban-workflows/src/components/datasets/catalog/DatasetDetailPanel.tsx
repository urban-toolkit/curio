import React, { useState } from "react";
import {
  DATASET_FORMAT_LABEL,
  DatasetCatalogItem,
  datasetListSourceCaption,
  datasetProvenanceLabel,
} from "../../../services/datasetCatalog";
import {
  datasetCount,
  datasetIconVariant,
  datasetInitials,
  defaultSchemaFields,
  formatBytes,
  formatClass,
  formatDatasetLocation,
  relativeTime,
} from "./datasetDetailHelpers";
import styles from "./DatasetDetailPanel.module.css";
import { DatasetSchemaPanel } from "./DatasetSchemaPanel";
import { DatasetTablePreview } from "./DatasetTablePreview";

const TABS = ["Overview", "Schema", "Table Preview", "Lineage"] as const;

export interface DatasetDetailPanelProps {
  dataset: DatasetCatalogItem | null;
  loading?: boolean;
  error?: string | null;
  variant?: "page" | "modal";
  dataflowId?: string | null;
  onBack?: () => void;
}

export const DatasetDetailPanel: React.FC<DatasetDetailPanelProps> = ({
  dataset,
  loading = false,
  error = null,
  variant = "modal",
  dataflowId = null,
  onBack,
}) => {
  const [activeTab, setActiveTab] = useState<(typeof TABS)[number]>("Overview");
  const fields = dataset?.schema?.fields?.length
    ? dataset.schema.fields
    : defaultSchemaFields(dataset);
  const rootClass = variant === "page" ? styles.pageRoot : styles.modalRoot;

  if (loading && !dataset) {
    return <p className={styles.loading}>Loading dataset...</p>;
  }

  if (error) {
    return <p className={styles.error}>{error}</p>;
  }

  if (!dataset) {
    return <p className={styles.loading}>Dataset not found.</p>;
  }

  const iconVariant = datasetIconVariant(dataset);
  const countLabel = datasetCount(dataset);
  const tags = dataset.tags.length > 0 ? dataset.tags : [dataset.format];

  return (
    <main className={`${styles.inspector} ${rootClass}`}>
      <div className={styles.pageHeader}>
        <div className={styles.breadcrumb}>
          {variant === "page" ? (
            <>
              <span>DATA CATALOG</span><span>/</span><span>INSTALLED DATASETS</span><span>/</span>
            </>
          ) : (
            <>
              <span>DATA CATALOG</span><span>/</span>
            </>
          )}
          <strong>{dataset.title}</strong>
        </div>

        {variant === "page" && onBack ? (
          <button className={styles.backButton} type="button" onClick={onBack}>Back</button>
        ) : null}

        <div className={styles.headerMain}>
          <div className={styles.titleBlock}>
            <span className={`${styles.datasetIcon} ${styles[`icon_${iconVariant}`]}`}>
              {datasetInitials(dataset.title)}
            </span>
            <div>
              <h1>{dataset.title}</h1>
              <div className={styles.inspectorMeta}>
                <span className={styles.installedBadge}>
                  {dataset.installed ? "Installed" : datasetProvenanceLabel(dataset.origin)}
                </span>
                <span className={formatClass(dataset.format, styles)}>{DATASET_FORMAT_LABEL[dataset.format]}</span>
                {countLabel ? <span>{countLabel}</span> : null}
                <span className={styles.metaDot} aria-hidden="true">·</span>
                <span>{fields.length} columns</span>
                {formatBytes(dataset.sizeBytes) ? (
                  <>
                    <span className={styles.metaDot} aria-hidden="true">·</span>
                    <span>{formatBytes(dataset.sizeBytes)}</span>
                  </>
                ) : null}
                <span className={styles.metaDot} aria-hidden="true">·</span>
                <span>Updated {relativeTime(dataset.updatedAt)}</span>
              </div>
            </div>
          </div>
          <div className={styles.inspectorActions}>
            <button className={styles.publishButton} type="button">Publish to Catalog</button>
            <button className={styles.exportButton} type="button">Export</button>
          </div>
        </div>

        <nav className={styles.inspectorTabs} aria-label="Dataset detail sections">
          {TABS.map((tab) => (
            <button
              key={tab}
              type="button"
              className={tab === activeTab ? styles.inspectorTabActive : ""}
              onClick={() => setActiveTab(tab)}
            >
              {tab}
            </button>
          ))}
        </nav>
      </div>

      <div className={styles.inspectorBody}>
        <section className={styles.schemaColumn} aria-label="Schema">
          <DatasetSchemaPanel dataset={dataset} dataflowId={dataflowId} />
        </section>

        <section className={styles.centerColumn} aria-label="Preview and lineage">
          <div className={styles.previewSection}>
            <div className={styles.previewSubtab}>
              <span className={styles.previewSubtabActive}>Table Preview</span>
            </div>
            <DatasetTablePreview dataset={dataset} dataflowId={dataflowId} />
          </div>

          <div className={styles.lineageSection}>
            <div className={styles.lineageHeader}>
              <h2>Data Flows <span className={styles.liveBadge}>live</span></h2>
              <p>Dataflows that generate or consume this dataset</p>
            </div>

            <p className={styles.lineageLabel}>Generated by</p>
            <article className={styles.lineageCard}>
              <div className={styles.lineageCardAccentWarm} />
              <div className={styles.lineageCardBody}>
                <strong>{datasetListSourceCaption(dataset)}</strong>
                <span className={styles.lineageNodeBadge}>Source node</span>
                <span className={styles.lineageFlowName}>Provenance: {formatDatasetLocation(dataset)}</span>
              </div>
              <button type="button" className={styles.lineageViewLink}>View node</button>
            </article>

            <p className={styles.lineageLabel}>
              Consumed by ({Math.max(dataset.consumerNodeIds.length, 1)})
            </p>
            {(dataset.consumerNodeIds.length > 0
              ? dataset.consumerNodeIds
              : ["Spatial Filter"]
            ).map((nodeId, index) => (
              <article className={styles.lineageCard} key={nodeId}>
                <div className={index % 2 === 0 ? styles.lineageCardAccentMuted : styles.lineageCardAccentBlue} />
                <div className={styles.lineageCardBody}>
                  <strong>{nodeId}</strong>
                  <span className={styles.lineageNodeBadgeMuted}>Compute node</span>
                  <span className={styles.lineageFlowName}>Provenance: {formatDatasetLocation(dataset)}</span>
                </div>
                <button type="button" className={styles.lineageViewLink}>View node</button>
              </article>
            ))}

            <p className={styles.lineageFooter}>
              Last execution: today · Duration: — · Data live
            </p>
            <button type="button" className={styles.lineageGraphLink}>View full lineage graph</button>
          </div>
        </section>

        <aside className={styles.infoColumn} aria-label="Dataset info">
          <div className={styles.infoHeader}>
            <h2>Dataset Info</h2>
          </div>

          <div className={styles.infoSection}>
            <p className={styles.infoSectionLabel}>General</p>
            <dl className={styles.infoRows}>
              <div><dt>Format</dt><dd>{DATASET_FORMAT_LABEL[dataset.format]}</dd></div>
              <div><dt>Total {dataset.featureCount != null ? "features" : "records"}</dt><dd>{(dataset.featureCount ?? dataset.rowCount)?.toLocaleString() || "Unknown"}</dd></div>
              <div><dt>Columns</dt><dd>{fields.length}</dd></div>
              <div><dt>File size</dt><dd>{formatBytes(dataset.sizeBytes) || "Unknown"}</dd></div>
              {dataset.schema?.crs ? (
                <div><dt>CRS</dt><dd>{dataset.schema.crs}</dd></div>
              ) : null}
              <div><dt>Availability</dt><dd><span className={styles.installedBadge}>{dataset.installed ? "Installed" : "Available"}</span></dd></div>
              <div><dt>Created</dt><dd>{new Date(dataset.updatedAt).toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</dd></div>
              <div><dt>Last updated</dt><dd>{relativeTime(dataset.updatedAt)}</dd></div>
            </dl>
          </div>

          <div className={styles.infoSection}>
            <p className={styles.infoSectionLabel}>Origin</p>
            <article className={styles.originCard}>
              <div className={styles.lineageCardAccentWarm} />
              <div>
                <strong>{datasetListSourceCaption(dataset)}</strong>
                <span>Source node · {DATASET_FORMAT_LABEL[dataset.format]} Loader</span>
                <button type="button" className={styles.lineageViewLink}>View node</button>
              </div>
            </article>
            {dataset.origin === "hub" || dataset.installed ? (
              <div className={styles.hubSourceCard}>
                <strong>Installed from Data Catalog</strong>
                <span>{dataset.sourceLabel || "Urban Lab"} · v1 · Installed recently</span>
              </div>
            ) : null}
          </div>

          <div className={styles.infoSection}>
            <p className={styles.infoSectionLabel}>
              Consumed by ({Math.max(dataset.consumerNodeIds.length, 1)})
            </p>
            {(dataset.consumerNodeIds.length > 0 ? dataset.consumerNodeIds : ["Spatial Filter"]).map((nodeId, index) => (
              <article className={styles.consumedCard} key={nodeId}>
                <div className={index % 2 === 0 ? styles.lineageCardAccentMuted : styles.lineageCardAccentBlue} />
                <div>
                  <strong>{nodeId}</strong>
                  <span>Compute node</span>
                </div>
                <span className={styles.consumedArrow} aria-hidden="true">→</span>
              </article>
            ))}
          </div>

          <div className={styles.infoSection}>
            <p className={styles.infoSectionLabel}>Tags</p>
            <div className={styles.tagList}>
              {tags.map((tag) => (
                <span className={styles.tagChip} key={tag}>{tag}</span>
              ))}
            </div>
          </div>
        </aside>
      </div>
    </main>
  );
};
