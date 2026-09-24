import React from "react";

import { CatalogFormatBadge } from "../../components/catalog/CatalogKindVisuals";
import type {
  LakeAcquirableFormat,
  LakeResourceRow as Row,
} from "../../services/dataLakeCatalog";
import { LakeSourceIcon } from "./LakeSourceIcon";
import styles from "./DataLakeResourceRow.module.css";

export interface DataLakeResourceRowProps {
  resource: Row;
  /** Shown on a federated result, where a row's portal is not implied by the
   *  page. Omitted on a single-source page, where it would repeat. */
  showSource?: boolean;
  iconUrl?: string | null;
  /** Absent until acquisition ships; the row then renders a disabled button
   *  rather than pretending it can download. */
  onDownload?: (resource: Row, format: string) => void;
}

/**
 * One dataset on a portal.
 *
 * A row rather than a card: a portal answers with tens of these, and the
 * tiles on `/catalog/lakes` are for the handful of sources you choose between.
 * Formats use the shared `CatalogFormatBadge`, so a CSV here is the same
 * colour as a CSV in the Data Catalog.
 */
export function DataLakeResourceRow({
  resource,
  showSource = false,
  iconUrl = null,
  onDownload,
}: DataLakeResourceRowProps) {
  const [format, setFormat] = React.useState<LakeAcquirableFormat | "">(
    resource.formats[0] ?? ""
  );
  const held = Boolean(resource.alreadyHeldDatasetId);

  return (
    <article className={styles.row} data-lake-resource={resource.resourceId}>
      <div className={styles.body}>
        <h3 className={styles.title}>{resource.name}</h3>
        <p className={styles.meta}>
          {[resource.publisher, resource.updatedAt ? `updated ${resource.updatedAt.slice(0, 10)}` : null]
            .filter(Boolean)
            .join(" · ")}
        </p>
        {resource.description ? (
          <p className={styles.description}>{resource.description}</p>
        ) : null}
        <div className={styles.badges}>
          {showSource ? (
            <span className={styles.sourceTag} title={resource.sourceName}>
              <LakeSourceIcon iconUrl={iconUrl} name={resource.sourceName} size="sm" />
              {resource.sourceName}
            </span>
          ) : null}
          {resource.formats.map((f) => (
            <CatalogFormatBadge key={f} label={f.toUpperCase()} formatKey={f} />
          ))}
          {held ? <span className={styles.held}>In your Data Catalog</span> : null}
          {resource.landingUrl ? (
            <a
              className={styles.landing}
              href={resource.landingUrl}
              target="_blank"
              rel="noreferrer noopener"
            >
              View on the portal ↗
            </a>
          ) : null}
        </div>
      </div>

      <div className={styles.actions}>
        {resource.formats.length > 1 ? (
          <select
            className={styles.formatSelect}
            value={format}
            aria-label={`Download format for ${resource.name}`}
            onChange={(e) => setFormat(e.target.value as LakeAcquirableFormat)}
          >
            {resource.formats.map((f) => (
              <option key={f} value={f}>
                {f.toUpperCase()}
              </option>
            ))}
          </select>
        ) : null}
        <button
          type="button"
          className={styles.download}
          /* Disabled until acquisition ships. A button that looks live and
             does nothing is worse than one that says it cannot yet. */
          disabled={!onDownload || !resource.acquirable}
          title={onDownload ? undefined : "Downloading is not wired up yet"}
          onClick={() => onDownload?.(resource, format)}
        >
          Download
        </button>
      </div>
    </article>
  );
}

export default DataLakeResourceRow;
