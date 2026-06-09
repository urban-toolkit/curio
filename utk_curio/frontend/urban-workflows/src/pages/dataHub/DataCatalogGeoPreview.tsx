import React from "react";
import type { DatasetFormat } from "../../services/datasetCatalog";
import styles from "../catalog/CatalogBrowseLayout.module.css";

export function DataCatalogGeoPreview({ format }: { format: DatasetFormat }) {
  const colors: Record<DatasetFormat, { fill: string; stroke: string; bg: string }> = {
    geojson: { fill: "rgba(47,143,74,0.12)", stroke: "rgba(47,143,74,0.3)", bg: "#F0FAF2" },
    csv: { fill: "rgba(59,111,212,0.1)", stroke: "rgba(59,111,212,0.25)", bg: "#F0F4FF" },
    json: { fill: "rgba(122,75,209,0.1)", stroke: "rgba(122,75,209,0.25)", bg: "#F7F2FF" },
    parquet: { fill: "rgba(251,170,105,0.12)", stroke: "rgba(251,170,105,0.3)", bg: "#FFF8F0" },
    geotiff: { fill: "rgba(122,75,209,0.1)", stroke: "rgba(122,75,209,0.25)", bg: "#F7F2FF" },
    shp: { fill: "rgba(136,136,136,0.1)", stroke: "rgba(136,136,136,0.25)", bg: "#F5F5F5" },
  };
  const c = colors[format] || colors.geojson;
  return (
    <div className={styles.geoPreview} style={{ background: c.bg }}>
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
      <span className={styles.geoPreviewLabel}>preview</span>
    </div>
  );
}
