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
  if (dataset.format === "geojson") return "GEO";
  if (dataset.format === "json") return "JSN";
  return DATASET_FORMAT_LABEL[dataset.format].slice(0, 3).toUpperCase();
}

function stopAccordionToggle(event: React.MouseEvent<HTMLButtonElement>) {
  event.preventDefault();
  event.stopPropagation();
}

function DatasetRow({ dataset }: { dataset: DatasetCatalogItem }) {
  return (
    <div
      className={styles.row}
      draggable
      onDragStart={(event) => {
        event.dataTransfer.setData(DATASET_DRAG_MIME, JSON.stringify(createDatasetDragPayload(dataset)));
        event.dataTransfer.effectAllowed = "copy";
      }}
    >
      <span className={styles.formatTile}>{formatAbbreviation(dataset)}</span>
      <span className={styles.rowText}>
        <span className={styles.rowTitle}>{dataset.title}</span>
        <span className={styles.typePill}>{dataset.origin === "computed" ? "COMPUTED" : "DATA"}</span>
      </span>
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
    () => catalog.items.filter((item) => item.origin !== "hub"),
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
