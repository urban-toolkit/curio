import React, { memo, useEffect, useMemo, useRef, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faChevronDown,
  faChevronUp,
  faDatabase,
  faDownload,
} from "@fortawesome/free-solid-svg-icons";
import { useFlowContext } from "../../../../providers/FlowProvider";
import { useDatasetCatalogDrawer } from "../../../../providers/datasetCatalog";
import { PaletteAccordion } from "../paletteAccordion";
import {
  createDatasetDragPayload,
  DATASET_DRAG_MIME,
  DATASET_FORMAT_LABEL,
  DatasetCatalogItem,
  useDatasetCatalog,
} from "../../../../services/datasetCatalog";
import styles from "./DatasetsPaletteDropdown.module.css";

function formatAbbreviation(dataset: DatasetCatalogItem): string {
  if (dataset.format === "geojson") return "GeoJSON";
  if (dataset.format === "json") return "JSON";
  if (dataset.format === "geotiff") return "GeoTIFF";
  return DATASET_FORMAT_LABEL[dataset.format].toUpperCase();
}

function relativeTime(iso?: string | null): string {
  if (!iso) return "";
  const delta = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(delta) || delta < 0) return "";
  const minutes = Math.max(1, Math.round(delta / 60_000));
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function datasetCount(dataset: DatasetCatalogItem): string | null {
  if (dataset.featureCount != null) return `${dataset.featureCount.toLocaleString()} feat.`;
  if (dataset.rowCount != null) return `${dataset.rowCount.toLocaleString()} rows`;
  return null;
}

function stopAccordionToggle(event: React.MouseEvent<HTMLButtonElement>) {
  event.preventDefault();
  event.stopPropagation();
}

function DatasetRow({ dataset }: { dataset: DatasetCatalogItem }) {
  const count = datasetCount(dataset);
  const time = relativeTime(dataset.updatedAt);
  const metaParts = [count, time].filter(Boolean).join(" · ");
  const upCount = dataset.producerNodeId ? 1 : 0;
  const downCount = dataset.consumerNodeIds?.length ?? 0;
  const hasConnections = upCount > 0 || downCount > 0;

  return (
    <div
      className={`${styles.row} ${styles[`fmt_${dataset.format}` as keyof typeof styles] ?? ""}`}
      draggable
      onDragStart={(event) => {
        event.dataTransfer.setData(DATASET_DRAG_MIME, JSON.stringify(createDatasetDragPayload(dataset)));
        event.dataTransfer.effectAllowed = "copy";
      }}
    >
      {/*<div className={styles.rowAccent} />*/}
      <div className={styles.rowBody}>
        <div className={styles.rowTop}>
          <span className={`${styles.formatChip} ${styles[`chip_${dataset.format}` as keyof typeof styles] ?? ""}`}>
            {formatAbbreviation(dataset)}
          </span>
          <span className={styles.rowTitle}>{dataset.title}</span>
        </div>
        {dataset.sourceLabel ? (
          <span className={styles.rowSource}>{dataset.sourceLabel}</span>
        ) : null}
        <div className={styles.rowMeta}>
          {metaParts ? <span className={styles.rowMetaText}>{metaParts}</span> : null}
          {hasConnections ? (
            <span className={styles.connBadge}>
              {upCount > 0 ? `${upCount}\u2191 ` : ""}{downCount > 0 ? `${downCount}\u2193` : ""}
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export const DatasetsPaletteDropdown = memo(function DatasetsPaletteDropdown() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const { projectId } = useFlowContext();
  const { openDatasetCatalogDrawer } = useDatasetCatalogDrawer();
  const catalog = useDatasetCatalog({
    dataflowId: projectId,
    includeHub: false,
    sort: "recent",
  });

  useEffect(() => {
    if (!open) return;
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDocMouseDown = (ev: MouseEvent) => {
      if (rootRef.current?.contains(ev.target as Node)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDocMouseDown, true);
    return () => document.removeEventListener("mousedown", onDocMouseDown, true);
  }, [open]);

  const rows = useMemo(
    () => catalog.items.filter((item) => item.origin === "imported" || item.origin === "hub"),
    [catalog.items],
  );
  const installedRows = useMemo(
    () => rows.filter((item) => item.origin !== "computed"),
    [rows],
  );

  const total = rows.length;

  return (
    <div className={styles.root} ref={rootRef}>
      <div className={styles.column}>
        <button
          type="button"
          className={`${styles.trigger} ${open ? styles.triggerOpen : ""}`}
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-haspopup="true"
          title={open ? "Close dataset palette" : "Open dataset palette"}
        >
          <FontAwesomeIcon icon={faDatabase} className={styles.triggerIcon} />
          <span className={styles.triggerLabel}>Data</span>
          <span className={styles.triggerCount}>{total}</span>
          <FontAwesomeIcon icon={open ? faChevronUp : faChevronDown} className={styles.triggerChevron}/>
          
        </button>
        {total === 0 ? <p className={styles.emptyHint}>No data yet</p> : null}
      </div>
      {open ? (
        <div className={styles.panel} role="region" aria-label="Dataset palette">
          <div className={styles.panelHeader}>
            <div className={styles.title}>Dataset Palette</div>
          </div>
          <div className={styles.scroll}>
            {catalog.loading ? <div className={styles.empty}>Loading datasets...</div> : null}
            {!catalog.loading && total === 0 ? (
              <div className={styles.empty}>
                Install, import, or compute a dataset to use it here.
              </div>
            ) : null}
            <PaletteAccordion
              title="Installed datasets"
              count={installedRows.length}
              actions={(
                <button
                  type="button"
                  className={styles.downloadButton}
                  aria-label="Install datasets"
                  onMouseDown={stopAccordionToggle}
                  onClick={stopAccordionToggle}
                >
                  <FontAwesomeIcon icon={faDownload} aria-hidden />
                </button>
              )}
            >
              {installedRows.length > 0 ? (
                installedRows.map((dataset) => <DatasetRow key={`${dataset.origin}:${dataset.id}`} dataset={dataset} />)
              ) : (
                <div className={styles.sectionEmpty}>No installed datasets yet.</div>
              )}
            </PaletteAccordion>

            <PaletteAccordion
              title="Current dataflow"
              count={total}
              selected
              defaultOpen
              actions={(
                <button
                  type="button"
                  className={styles.downloadButton}
                  aria-label="Import into current dataflow"
                  onMouseDown={stopAccordionToggle}
                  onClick={stopAccordionToggle}
                >
                  <FontAwesomeIcon icon={faDownload} aria-hidden />
                </button>
              )}
            >
              {rows.length > 0 ? (
                rows.map((dataset) => <DatasetRow key={`${dataset.origin}:${dataset.id}`} dataset={dataset} />)
              ) : (
                <div className={styles.sectionEmpty}>No datasets in this dataflow yet.</div>
              )}
            </PaletteAccordion>
          </div>
          <div className={styles.footer}>
            <button
              type="button"
              className={styles.catalogButton}
              onClick={() => {
                openDatasetCatalogDrawer();
              }}
            >
              Browse Data Hub +
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
});
