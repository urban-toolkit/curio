import React from "react";

import {
  dataLakeCatalogApi,
  formatBytes,
  lakeThumbnailPath,
  type LakeStorageFilesPage,
} from "../../services/dataLakeCatalog";
import { useAuthedObjectUrl } from "../../utils/useAuthedObjectUrl";
import styles from "./DataLakeFilesPanel.module.css";

/**
 * A storage row's files, a page at a time, for inspection and for picking
 * some of them to add.
 *
 * Files are numbered by their position in the row, which is also how their
 * thumbnails are addressed: no path ever leaves the client.
 */

export const FILES_PAGE_SIZE = 50;

export interface DataLakeFilesPanelProps {
  dirName: string;
  resourceId: string;
  /** Add only the picked files. Omitted where adding is not offered. */
  onAddFiles?: (relpaths: string[]) => void;
}

const FileThumb: React.FC<{ dirName: string; resourceId: string; index: number }> = ({
  dirName,
  resourceId,
  index,
}) => {
  const { url } = useAuthedObjectUrl(lakeThumbnailPath(dirName, resourceId, index));
  return url ? <img className={styles.thumb} src={url} alt="" /> : <span className={styles.thumb} />;
};

export function DataLakeFilesPanel({ dirName, resourceId, onAddFiles }: DataLakeFilesPanelProps) {
  const [offset, setOffset] = React.useState(0);
  const [page, setPage] = React.useState<LakeStorageFilesPage | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [picked, setPicked] = React.useState<Set<string>>(new Set());

  React.useEffect(() => {
    const controller = new AbortController();
    setError(null);
    dataLakeCatalogApi
      .listFiles(dirName, resourceId, { offset, limit: FILES_PAGE_SIZE }, controller.signal)
      .then(setPage)
      .catch((err: Error) => {
        if (err.name !== "AbortError") setError(err.message || "The files could not be listed.");
      });
    return () => controller.abort();
  }, [dirName, resourceId, offset]);

  const toggle = (relpath: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(relpath)) next.delete(relpath);
      else next.add(relpath);
      return next;
    });

  if (error) return <p className={styles.error} role="alert">{error}</p>;
  if (!page) return <p className={styles.note}>Listing files…</p>;

  const last = Math.min(page.offset + page.files.length, page.total);
  const fieldNames = page.files.length ? Object.keys(page.files[0].values) : [];

  return (
    <div className={styles.panel}>
      <table className={styles.table}>
        <thead>
          <tr>
            {onAddFiles ? <th aria-label="Pick" /> : null}
            {page.previews ? <th aria-label="Preview" /> : null}
            <th>File</th>
            {fieldNames.map((name) => (
              <th key={name}>{name}</th>
            ))}
            <th className={styles.size}>Size</th>
          </tr>
        </thead>
        <tbody>
          {page.files.map((file) => (
            <tr key={file.relpath}>
              {onAddFiles ? (
                <td>
                  <input
                    type="checkbox"
                    aria-label={`Pick ${file.relpath}`}
                    checked={picked.has(file.relpath)}
                    onChange={() => toggle(file.relpath)}
                  />
                </td>
              ) : null}
              {page.previews ? (
                <td>
                  <FileThumb dirName={dirName} resourceId={resourceId} index={file.index} />
                </td>
              ) : null}
              <td className={styles.path} title={file.relpath}>
                {file.relpath}
              </td>
              {fieldNames.map((name) => (
                <td key={name}>{file.values[name]}</td>
              ))}
              <td className={styles.size}>{formatBytes(file.size)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className={styles.footer}>
        <span className={styles.note}>
          {page.total === 0
            ? "No files."
            : `${(page.offset + 1).toLocaleString()} to ${last.toLocaleString()} of ${page.total.toLocaleString()}`}
        </span>
        <button
          type="button"
          className={styles.pageButton}
          disabled={page.offset === 0}
          onClick={() => setOffset(Math.max(0, page.offset - FILES_PAGE_SIZE))}
        >
          Previous
        </button>
        <button
          type="button"
          className={styles.pageButton}
          disabled={last >= page.total}
          onClick={() => setOffset(page.offset + FILES_PAGE_SIZE)}
        >
          Next
        </button>
        <span className={styles.spacer} />
        {onAddFiles ? (
          <button
            type="button"
            className={styles.addButton}
            disabled={picked.size === 0}
            onClick={() => onAddFiles(Array.from(picked))}
          >
            {picked.size === 0
              ? "Pick files to add"
              : `Add ${picked.size.toLocaleString()} picked file${picked.size === 1 ? "" : "s"}`}
          </button>
        ) : null}
      </div>
    </div>
  );
}

export default DataLakeFilesPanel;
