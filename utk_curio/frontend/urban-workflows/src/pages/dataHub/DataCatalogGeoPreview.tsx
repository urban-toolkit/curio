import React, { useEffect, useMemo, useState } from "react";
import type { DatasetCatalogItem, DatasetFormat } from "../../services/datasetCatalog";
import { datasetCatalogApi } from "../../services/datasetCatalog";
import { visiblePreviewColumns } from "../../utils/tabularPreview";
import styles from "../catalog/CatalogBrowseLayout.module.css";

const ROW_LIMIT = 3;
const MAX_COLUMNS = 4;
const EXCLUDE_COLUMNS = ["geometry", "geom", "wkt", "the_geom"];

const colors: Record<DatasetFormat, { fill: string; stroke: string; bg: string }> = {
  geojson: { fill: "rgba(47,143,74,0.12)", stroke: "rgba(47,143,74,0.3)", bg: "#F0FAF2" },
  csv: { fill: "rgba(59,111,212,0.1)", stroke: "rgba(59,111,212,0.25)", bg: "#F0F4FF" },
  json: { fill: "rgba(122,75,209,0.1)", stroke: "rgba(122,75,209,0.25)", bg: "#F7F2FF" },
  parquet: { fill: "rgba(251,170,105,0.12)", stroke: "rgba(251,170,105,0.3)", bg: "#FFF8F0" },
  geotiff: { fill: "rgba(122,75,209,0.1)", stroke: "rgba(122,75,209,0.25)", bg: "#F7F2FF" },
  shp: { fill: "rgba(136,136,136,0.1)", stroke: "rgba(136,136,136,0.25)", bg: "#F5F5F5" },
};

function formatCell(value: unknown): string {
  if (value == null) return "—";
  const text = String(value);
  return text.length > 20 ? `${text.slice(0, 17)}…` : text;
}

function DecorativePreview({ format }: { format: DatasetFormat }) {
  const c = colors[format] || colors.geojson;
  return (
    <svg className={styles.geoPreviewSvg} viewBox="0 0 296 112" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path
        d="M60 80 L100 50 L145 62 L180 48 L210 68 L208 98 L165 106 L110 103 L60 96 Z"
        fill={c.fill}
        stroke={c.stroke}
        strokeWidth="1"
      />
      <path
        d="M80 84 L115 58 L148 68 L172 58 L195 74 L193 95 L160 100 L118 98 L80 92 Z"
        fill={c.fill}
      />
    </svg>
  );
}

export function DataCatalogGeoPreview({ dataset }: { dataset: DatasetCatalogItem }) {
  const [fetching, setFetching] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [unsupportedMessage, setUnsupportedMessage] = useState<string | null>(null);
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    let cancelled = false;
    setFetching(true);
    setError(null);
    setUnsupportedMessage(null);
    setRows([]);
    void datasetCatalogApi
      .preview(dataset.id, { rowLimit: ROW_LIMIT })
      .then((response) => {
        if (cancelled) return;
        if (response.unsupported) {
          setUnsupportedMessage(response.message || "Preview unavailable");
          return;
        }
        setRows((response.rows || []) as Record<string, unknown>[]);
      })
      .catch((err) => {
        if (!cancelled) {
          setError((err as Error)?.message || "Preview unavailable");
        }
      })
      .finally(() => {
        if (!cancelled) setFetching(false);
      });
    return () => {
      cancelled = true;
    };
  }, [dataset.id]);

  const columns = useMemo(
    () => visiblePreviewColumns(rows, EXCLUDE_COLUMNS).slice(0, MAX_COLUMNS),
    [rows],
  );
  const showTable = !fetching && columns.length > 0 && rows.length > 0;
  const c = colors[dataset.format] || colors.geojson;
  const statusMessage = fetching
    ? "Loading preview…"
    : error || unsupportedMessage || (!showTable ? "No preview rows" : null);

  return (
    <div className={styles.geoPreview} style={{ background: c.bg }} aria-label="Dataset preview">
      {!showTable ? <DecorativePreview format={dataset.format} /> : null}
      {showTable ? (
        <div className={styles.drawerPreviewTableWrap}>
          <table className={styles.drawerPreviewTable}>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column} title={column}>
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, ROW_LIMIT).map((row, rowIndex) => (
                <tr key={`${dataset.id}-${rowIndex}`}>
                  {columns.map((column) => (
                    <td key={column} title={formatCell(row[column])}>
                      {formatCell(row[column])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {statusMessage && !showTable ? (
        <span className={styles.geoPreviewStatus}>{statusMessage}</span>
      ) : null}
    </div>
  );
}
