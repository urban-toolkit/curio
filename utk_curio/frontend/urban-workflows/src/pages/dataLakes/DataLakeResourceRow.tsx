import React from "react";

import { CatalogFormatBadge } from "../../components/catalog/CatalogKindVisuals";
import {
  LAKE_RESOURCE_KIND_LABEL,
  jobProgress,
  jobProgressLabel,
  lakeThumbnailPath,
  type LakeAcquireBody,
  type LakeAcquireJob,
  type LakeDeclaredResource,
  type LakeResourceRow as Row,
} from "../../services/dataLakeCatalog";
import { useAuthedObjectUrl } from "../../utils/useAuthedObjectUrl";
import { DataLakeAddDialog, narrowableFields } from "./DataLakeAddDialog";
import { DataLakeFilesPanel } from "./DataLakeFilesPanel";
import { LakeSourceIcon } from "./LakeSourceIcon";
import styles from "./DataLakeResourceRow.module.css";

/** Sample thumbnails a collection row shows. */
const ROW_SAMPLES = 4;

/** What a row of a storage source needs beyond a portal's. */
export interface StorageRowContext {
  dirName: string;
  /** What the manifest declares about the row's resource. */
  declared?: LakeDeclaredResource;
  /** Adds the row, all of it or narrowed. */
  onAdd: (resource: Row, body: LakeAcquireBody) => void;
}

export interface DataLakeResourceRowProps {
  resource: Row;
  /** Shown on a federated result, where a row's portal is not implied by the
   *  page. Omitted on a single-source page, where it would repeat. */
  showSource?: boolean;
  iconUrl?: string | null;
  onDownload?: (resource: Row, format: string) => void;
  /** The download in flight or just finished for this row, if any. */
  job?: LakeAcquireJob;
  onCancel?: (resource: Row) => void;
  onDismiss?: (resource: Row) => void;
  /** Opens the dataset a finished (or earlier) download landed as. The page
   *  shows it in the Data Catalog's details modal, the one every other
   *  catalog opens, so reaching it never leaves the lake page. */
  onViewDataset?: (datasetId: string) => void;
  /** Present on a storage source's rows, which are added rather than
   *  downloaded, and can be narrowed or opened file by file. */
  storage?: StorageRowContext;
}

const SampleThumb: React.FC<{ path: string; name: string }> = ({ path, name }) => {
  const { url } = useAuthedObjectUrl(path);
  return url ? (
    <img className={styles.sample} src={url} alt={name} title={name} />
  ) : (
    <span className={styles.sample} title={name} />
  );
};

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
  job,
  onCancel,
  onDismiss,
  onViewDataset,
  storage,
}: DataLakeResourceRowProps) {
  const [format, setFormat] = React.useState<string>(resource.formats[0] ?? "");
  const [adding, setAdding] = React.useState(false);
  const [filesOpen, setFilesOpen] = React.useState(false);
  const held = Boolean(resource.alreadyHeldDatasetId);
  const running = job != null && (job.status === "queued" || job.status === "running");
  const finished = job?.status === "completed";
  const failed = job != null && (job.status === "failed" || job.status === "refused");
  const landedAt = job?.datasetId ?? resource.alreadyHeldDatasetId;
  const kind = resource.kind ?? null;
  const splitBy = storage?.declared?.splitBy ?? [];
  const perFile = storage?.declared?.datasets === "per-file";
  const samples =
    storage && kind && kind !== "table" ? (resource.samples ?? []).slice(0, ROW_SAMPLES) : [];

  const add = () => {
    if (!storage) return;
    if (narrowableFields(resource, splitBy).length > 0) setAdding(true);
    else storage.onAdd(resource, { title: resource.name });
  };

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
          {kind ? <span className={styles.kind}>{LAKE_RESOURCE_KIND_LABEL[kind] ?? kind}</span> : null}
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
        {samples.length > 0 && storage ? (
          <div className={styles.samples} aria-label={`Files in ${resource.name}`}>
            {samples.map((relpath, index) => (
              <SampleThumb
                key={relpath}
                name={relpath}
                path={lakeThumbnailPath(storage.dirName, resource.resourceId, index)}
              />
            ))}
          </div>
        ) : null}
      </div>

      <div className={styles.actions}>
        {running ? (
          <ProgressPanel job={job!} onCancel={() => onCancel?.(resource)} />
        ) : (
          <>
            {storage && !perFile ? (
              <button
                type="button"
                className={styles.filesToggle}
                aria-expanded={filesOpen}
                onClick={() => setFilesOpen((open) => !open)}
              >
                {filesOpen ? "Hide files" : "Files"}
              </button>
            ) : null}
            {!storage && resource.formats.length > 1 ? (
              <select
                className={styles.formatSelect}
                value={format}
                aria-label={`Download format for ${resource.name}`}
                onChange={(e) => setFormat(e.target.value)}
              >
                {resource.formats.map((f) => (
                  <option key={f} value={f}>
                    {f.toUpperCase()}
                  </option>
                ))}
              </select>
            ) : null}
            {(finished || held) && landedAt && onViewDataset ? (
              <button
                type="button"
                className={styles.viewDataset}
                onClick={() => onViewDataset(landedAt)}
              >
                View dataset
              </button>
            ) : storage ? (
              <button
                type="button"
                className={styles.download}
                disabled={!resource.acquirable}
                onClick={add}
              >
                Add to Data Catalog
              </button>
            ) : (
              <button
                type="button"
                className={styles.download}
                disabled={!onDownload || !resource.acquirable}
                title={onDownload ? undefined : "Downloading is not available here"}
                onClick={() => onDownload?.(resource, format)}
              >
                Download
              </button>
            )}
          </>
        )}
      </div>

      {filesOpen && storage ? (
        <DataLakeFilesPanel
          dirName={storage.dirName}
          resourceId={resource.resourceId}
          onAddFiles={(files) => {
            setFilesOpen(false);
            storage.onAdd(resource, {
              title: `${resource.name} (${files.length.toLocaleString()} files)`,
              files,
            });
          }}
        />
      ) : null}

      {adding && storage ? (
        <DataLakeAddDialog
          resource={resource}
          splitBy={splitBy}
          onCancel={() => setAdding(false)}
          onAdd={(body) => {
            setAdding(false);
            storage.onAdd(resource, body);
          }}
        />
      ) : null}

      {failed ? (
        /* The server's own words. It knows whether the file was too large, an
           archive, or a portal that refused - and any of those is more use
           than "download failed". */
        <p className={styles.failure} role="alert">
          {job?.error || "That download did not finish."}
          {onDismiss ? (
            <button
              type="button"
              className={styles.dismiss}
              aria-label="Dismiss"
              onClick={() => onDismiss(resource)}
            >
              ×
            </button>
          ) : null}
        </p>
      ) : null}
    </article>
  );
}

/**
 * A download in flight.
 *
 * Determinate when the portal sent a Content-Length, indeterminate with the
 * stage message when it did not - plenty of portals stream without declaring
 * one, and a bar stuck at 0% reads as broken.
 */
const ProgressPanel: React.FC<{ job: LakeAcquireJob; onCancel: () => void }> = ({
  job,
  onCancel,
}) => {
  const fraction = jobProgress(job);
  return (
    <div className={styles.progress}>
      <div
        className={styles.progressTrack}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={fraction == null ? undefined : 100}
        aria-valuenow={fraction == null ? undefined : Math.round(fraction * 100)}
        aria-label={job.stageMessage}
      >
        <span
          className={[
            styles.progressFill,
            fraction == null ? styles.progressIndeterminate : "",
          ]
            .filter(Boolean)
            .join(" ")}
          style={fraction == null ? undefined : { width: `${fraction * 100}%` }}
        />
      </div>
      <span className={styles.progressLabel}>{jobProgressLabel(job)}</span>
      <button type="button" className={styles.cancel} onClick={onCancel}>
        Cancel
      </button>
    </div>
  );
};

export default DataLakeResourceRow;
