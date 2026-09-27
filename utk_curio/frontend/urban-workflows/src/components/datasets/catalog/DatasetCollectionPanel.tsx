import React, { useCallback, useEffect, useRef, useState } from "react";

import {
  DATASET_COLLECTION_KIND_LABEL,
  type DatasetCatalogItem,
  type DatasetCollection,
} from "../../../services/datasetCatalog";
import {
  dataLakeCatalogApi,
  isTerminal,
  jobProgressLabel,
  type LakeAcquireJob,
  type LakeCollectionStatus,
} from "../../../services/dataLakeCatalog";
import { useAuthedObjectUrl } from "../../../utils/useAuthedObjectUrl";
import { DetailLink } from "./DetailLink";
import { absoluteDate, formatBytes } from "./datasetDetailHelpers";
import styles from "./DatasetDetailPanel.module.css";
import stripStyles from "./DatasetCollectionPanel.module.css";

/**
 * What a `collection` dataset's details add: a strip of its files above the
 * index preview, and a Collection section saying where the files are and what
 * they are.
 *
 * The index is the dataset; the files stay where the lake source keeps them.
 * A bucket's files are read once cached, so the section offers Cache files.
 */

const COUNT_NOUN: Record<string, [string, string]> = {
  image: ["image", "images"],
  video: ["video", "videos"],
  frame: ["frame", "frames"],
  audio: ["recording", "recordings"],
  raster: ["raster", "rasters"],
};

function countsLabel(counts: Record<string, number>): string {
  return Object.entries(counts)
    .map(([kind, n]) => {
      const [one, many] = COUNT_NOUN[kind] ?? [kind, kind];
      return `${n.toLocaleString()} ${n === 1 ? one : many}`;
    })
    .join(", ");
}

function durationLabel(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

function narrowedLabel(block: DatasetCollection): string | null {
  const parts = Object.entries(block.narrowedBy ?? {}).map(([name, kept]) =>
    Array.isArray(kept) ? `${name} ${kept.join(", ")}` : `${name} ${kept.min} to ${kept.max}`,
  );
  if (block.chosenFiles != null) parts.push(`${block.chosenFiles.toLocaleString()} picked files`);
  return parts.length ? parts.join("; ") : null;
}

const POLL_MS = 1000;

/** The collection's status, and a Cache files job that refreshes it. */
export function useCollectionStatus(datasetId: string | undefined) {
  const [status, setStatus] = useState<LakeCollectionStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<LakeAcquireJob | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const load = useCallback(() => {
    if (!datasetId) return;
    dataLakeCatalogApi
      .getCollection(datasetId)
      .then((s) => {
        setStatus(s);
        setError(null);
      })
      .catch((err: Error) => setError(err.message || "Could not read this collection."));
  }, [datasetId]);

  useEffect(() => {
    setStatus(null);
    setJob(null);
    load();
    return () => clearTimeout(timer.current);
  }, [load]);

  const follow = useCallback(
    (jobId: string) => {
      timer.current = setTimeout(() => {
        dataLakeCatalogApi
          .getJob(jobId)
          .then((next) => {
            setJob(next);
            if (isTerminal(next.status)) load();
            else follow(jobId);
          })
          .catch((err: Error) => setError(err.message || "Lost track of that job."));
      }, POLL_MS);
    },
    [load],
  );

  const cacheFiles = useCallback(() => {
    if (!datasetId) return;
    dataLakeCatalogApi
      .cacheCollection(datasetId)
      .then((started) => {
        setJob(started);
        follow(started.jobId);
      })
      .catch((err: Error) => setError(err.message || "Could not cache these files."));
  }, [datasetId, follow]);

  return { status, error, job, cacheFiles };
}

const StripThumb: React.FC<{ datasetId: string; fileId: string; name: string }> = ({
  datasetId,
  fileId,
  name,
}) => {
  const { url, failed } = useAuthedObjectUrl(
    `/api/datasets/${encodeURIComponent(datasetId)}/media/${encodeURIComponent(fileId)}?variant=thumb`,
  );
  return url ? (
    <img className={stripStyles.thumb} src={url} alt={name} title={name} />
  ) : (
    <span
      className={`${stripStyles.thumb} ${failed ? stripStyles.thumbFailed : ""}`}
      title={failed ? `${name} has no preview` : name}
    />
  );
};

/** The first files of the collection, above its index preview. */
export const CollectionStrip: React.FC<{ status: LakeCollectionStatus | null }> = ({ status }) => {
  if (!status || status.samples.length === 0) return null;
  return (
    <div className={stripStyles.strip} aria-label="Files in this collection">
      {status.samples.map((sample) => (
        <StripThumb
          key={sample.fileId}
          datasetId={status.datasetId}
          fileId={sample.fileId}
          name={sample.name}
        />
      ))}
    </div>
  );
};

/** The Collection section of the info column. */
export const CollectionInfoSection: React.FC<{
  dataset: DatasetCatalogItem;
  status: LakeCollectionStatus | null;
  error: string | null;
  job: LakeAcquireJob | null;
  onCacheFiles: () => void;
  onFollowLink?: (to: string) => void;
}> = ({ dataset, status, error, job, onCacheFiles, onFollowLink }) => {
  const block = dataset.collection;
  if (!block) return null;
  const running = job != null && !isTerminal(job.status);
  const narrowed = narrowedLabel(block);
  const split = Object.entries(block.split ?? {})
    .map(([name, value]) => `${name} ${value}`)
    .join(", ");

  return (
    <div className={styles.infoSection}>
      <p className={styles.infoSectionLabel}>Collection</p>
      <dl className={styles.infoRows}>
        <div>
          <dt>Kind</dt>
          <dd>{DATASET_COLLECTION_KIND_LABEL[block.kind] ?? block.kind}</dd>
        </div>
        <div>
          <dt>Indexed from</dt>
          <dd>
            <DetailLink
              to={`/catalog/lakes/${encodeURIComponent(block.sourceId)}`}
              onFollow={onFollowLink}
            >
              {block.sourceName}
            </DetailLink>{" "}
            · {block.resource}
          </dd>
        </div>
        {split ? (
          <div>
            <dt>Split</dt>
            <dd>{split}</dd>
          </div>
        ) : null}
        {narrowed ? (
          <div>
            <dt>Narrowed to</dt>
            <dd>{narrowed}</dd>
          </div>
        ) : null}
        <div>
          <dt>Files</dt>
          <dd>{countsLabel(block.counts) || block.fileCount.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Total size</dt>
          <dd>{formatBytes(block.totalBytes) ?? "Unknown"}</dd>
        </div>
        {block.fields.length > 0 ? (
          <div>
            <dt>Path fields</dt>
            <dd>{block.fields.join(", ")}</dd>
          </div>
        ) : null}
        {block.sequences != null ? (
          <div>
            <dt>Sequences</dt>
            <dd>{block.sequences.toLocaleString()}</dd>
          </div>
        ) : null}
        {block.fps != null ? (
          <div>
            <dt>Frame rate</dt>
            <dd>{block.fps} fps</dd>
          </div>
        ) : null}
        {block.totalSeconds != null ? (
          <div>
            <dt>Total duration</dt>
            <dd>{durationLabel(block.totalSeconds)}</dd>
          </div>
        ) : null}
        {dataset.schema?.crs ? (
          <div>
            <dt>Footprints</dt>
            <dd>{dataset.schema.crs}</dd>
          </div>
        ) : null}
        <div>
          <dt>Positions</dt>
          <dd>{block.hasGps ? "Yes" : "No"}</dd>
        </div>
        {block.probeErrors > 0 ? (
          <div>
            <dt>Unreadable files</dt>
            <dd>{block.probeErrors.toLocaleString()}</dd>
          </div>
        ) : null}
        <div>
          <dt>Indexed</dt>
          <dd>{absoluteDate(block.indexedAt)}</dd>
        </div>
        {status && !status.local ? (
          <div>
            <dt>On this machine</dt>
            <dd>
              {status.cachedFiles.toLocaleString()} of {status.fileCount.toLocaleString()} files
            </dd>
          </div>
        ) : null}
      </dl>
      {status && !status.local && status.cachedFiles < status.fileCount ? (
        <div className={stripStyles.cacheRow}>
          <button
            type="button"
            className={stripStyles.cacheButton}
            disabled={running}
            onClick={onCacheFiles}
          >
            {running ? "Caching…" : "Cache files"}
          </button>
          <span className={stripStyles.cacheNote}>
            {running && job
              ? jobProgressLabel(job)
              : "Nodes read a bucket's files once they are on this machine."}
          </span>
        </div>
      ) : null}
      {job && (job.status === "failed" || job.status === "refused") ? (
        <p className={styles.error} role="alert">
          {job.error || "Those files could not be cached."}
        </p>
      ) : null}
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
};
