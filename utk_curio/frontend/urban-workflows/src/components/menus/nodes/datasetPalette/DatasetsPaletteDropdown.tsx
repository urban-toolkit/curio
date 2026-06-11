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
  beginDatasetDrag,
  endDatasetDrag,
  writeDatasetDragData,
  DATASET_CATALOG_REFRESH_EVENT,
  DATASET_FORMAT_LABEL,
  DatasetCatalogItem,
  datasetProvenanceLabel,
  isProjectSessionDataset,
  isUserInstalledDataset,
  useDatasetCatalog,
  prefetchDatasetCatalog,
} from "../../../../services/datasetCatalog";
import { buildSaveableLiveOutputs } from "../../../../utils/saveOutputDataset";
import {
  isToolsPaletteDismissOutsideClick,
  TOOLS_PALETTE_DROPDOWN_ATTR,
} from "../toolsPaletteDismiss";
import styles from "./DatasetsPaletteDropdown.module.css";

function formatAbbreviation(dataset: DatasetCatalogItem): string {
  if (dataset.format === "geojson") return "GeoJSON";
  if (dataset.format === "json") return "JSON";
  if (dataset.format === "geotiff") return "GeoTIFF";
  if (dataset.format === "bundle") return "Bundle";
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
        writeDatasetDragData(event.dataTransfer, beginDatasetDrag(dataset));
      }}
      onDragEnd={() => endDatasetDrag()}
    >
      {/*<div className={styles.rowAccent} />*/}
      <div className={styles.rowBody}>
        <div className={styles.rowTop}>
          <FontAwesomeIcon icon={faDatabase} className={styles.triggerIcon} />
          <span className={`${styles.formatChip} ${styles.iconBadge} ${styles[`chip_${dataset.format}` as keyof typeof styles] ?? ""}`}>
            {formatAbbreviation(dataset)}
          </span>
          <span className={styles.rowTitle}>{dataset.title}</span>
        </div>

        <div className={styles.rowMeta}>
          <span className={styles.typePill}>
            {datasetProvenanceLabel(dataset.origin, dataset.format)}
          </span>

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
  const { projectId, outputs, nodes, defaultSaveOutputDataset } = useFlowContext();
  const { openDatasetCatalogDrawer, isDatasetCatalogDrawerOpen } = useDatasetCatalogDrawer();
  const liveOutputs = useMemo(
    () => buildSaveableLiveOutputs(outputs, nodes, defaultSaveOutputDataset),
    [outputs, nodes, defaultSaveOutputDataset],
  );

  const catalog = useDatasetCatalog({
    dataflowId: projectId,
    includeHub: false,
    sort: "recent",
    // Only fold live session outputs into the query while the palette is open;
    // when closed the base catalog still drives the counter without refetching
    // every time node outputs change.
    liveOutputs: open ? liveOutputs : undefined,
    // Load at startup so the trigger counter is populated before the user opens
    // the palette, and the list is instantly available on open.
    enabled: true,
  });

  useEffect(() => {
    const onRefresh = () => void catalog.reload({ bustCache: true });
    window.addEventListener(DATASET_CATALOG_REFRESH_EVENT, onRefresh);
    return () => window.removeEventListener(DATASET_CATALOG_REFRESH_EVENT, onRefresh);
  }, [catalog.reload]);

  useEffect(() => {
    if (!open) return;
    const onKey = (ev: KeyboardEvent) => {
      // Let the drawer own Escape while it is open so the palette stays open
      // behind it (e.g. after installing from the Data Catalog).
      if (ev.key === "Escape" && !isDatasetCatalogDrawerOpen) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, isDatasetCatalogDrawerOpen]);

  useEffect(() => {
    if (!open) return;
    const onDocMouseDown = (ev: MouseEvent) => {
      // Keep the palette open while the Data Catalog drawer is open so the
      // newly installed dataset is visible once the drawer is dismissed.
      if (isDatasetCatalogDrawerOpen) return;
      if (rootRef.current?.contains(ev.target as Node)) return;
      if (!isToolsPaletteDismissOutsideClick(ev.target)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDocMouseDown, true);
    return () => document.removeEventListener("mousedown", onDocMouseDown, true);
  }, [open, isDatasetCatalogDrawerOpen]);

  const rows = useMemo(
    () => catalog.items.filter((item) => item.origin === "imported" || item.origin === "hub" || item.origin === "computed"),
    [catalog.items],
  );
  const installedRows = useMemo(
    () => rows.filter((item) => isUserInstalledDataset(item)),
    [rows],
  );
  const projectRows = useMemo(
    () => rows.filter((item) => isProjectSessionDataset(item)),
    [rows],
  );

  const total = rows.length;

  return (
    <div
      id="datasets-palette"
      className={styles.root}
      ref={rootRef}
      {...{ [TOOLS_PALETTE_DROPDOWN_ATTR]: "true" }}
    >
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
            {catalog.loading && rows.length === 0 ? <div className={styles.empty}>Loading datasets...</div> : null}
            {!catalog.loading && !catalog.refreshing && total === 0 ? (
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
              title="Project datasets"
              count={projectRows.length}
              selected
              defaultOpen
              actions={(
                <button
                  type="button"
                  className={styles.downloadButton}
                  aria-label="Import into this project"
                  onMouseDown={stopAccordionToggle}
                  onClick={stopAccordionToggle}
                >
                  <FontAwesomeIcon icon={faDownload} aria-hidden />
                </button>
              )}
            >
              {projectRows.length > 0 ? (
                projectRows.map((dataset) => <DatasetRow key={`${dataset.origin}:${dataset.id}`} dataset={dataset} />)
              ) : (
                <div className={styles.sectionEmpty}>No live session outputs yet.</div>
              )}
            </PaletteAccordion>
          </div>
          <div className={styles.footer}>
            <button
              type="button"
              className={styles.catalogButton}
              onMouseEnter={() => {
                prefetchDatasetCatalog({
                  dataflowId: projectId,
                  includeHub: true,
                  sort: "recent",
                });
              }}
              onClick={() => openDatasetCatalogDrawer()}
            >
              Browse Data Catalog +
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
});
