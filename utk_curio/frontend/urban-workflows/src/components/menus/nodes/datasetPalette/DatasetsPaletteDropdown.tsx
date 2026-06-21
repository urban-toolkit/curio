import React, { memo, useEffect, useMemo, useRef, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faChevronDown,
  faChevronUp,
  faDatabase,
} from "@fortawesome/free-solid-svg-icons";
import { useFlowContext } from "../../../../providers/FlowProvider";
import { useDatasetCatalogDrawer } from "../../../../providers/datasetCatalog";
import { PaletteAccordion } from "../paletteAccordion";
import {
  DATASET_CATALOG_REFRESH_EVENT,
  isUserInstalledDataset,
  useDatasetCatalog,
  prefetchDatasetCatalog,
} from "../../../../services/datasetCatalog";
import {
  isToolsPaletteDismissOutsideClick,
  TOOLS_PALETTE_DROPDOWN_ATTR,
} from "../toolsPaletteDismiss";
import { DatasetRow } from "./DatasetPaletteRows";
import styles from "./DatasetsPaletteDropdown.module.css";

export const DatasetsPaletteDropdown = memo(function DatasetsPaletteDropdown() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const { projectId } = useFlowContext();
  const { openDatasetCatalogDrawer, isDatasetCatalogDrawerOpen } = useDatasetCatalogDrawer();

  const catalog = useDatasetCatalog({
    dataflowId: projectId,
    includeHub: false,
    sort: "recent",
    // The palette lists installed/saved datasets only — these come from the
    // base catalog (persisted spec refs + user store) and are surfaced after an
    // install/save via DATASET_CATALOG_REFRESH_EVENT. Deliberately do NOT fold
    // ephemeral session `liveOutputs` into the query: they are never `installed`
    // (so never appear in the list below) yet would churn the fetch key on every
    // node execution, making the counter flicker and computed rows blink out.
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

  // Count what the palette actually shows (installed/saved datasets) so the
  // trigger badge stays consistent with the list instead of also counting
  // hub/ephemeral rows that never render here.
  const total = installedRows.length;

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
            <div className={styles.title}>Datasets</div>
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
              selected
              defaultOpen
            >
              {installedRows.length > 0 ? (
                installedRows.map((dataset) => <DatasetRow key={`${dataset.origin}:${dataset.id}`} dataset={dataset} />)
              ) : (
                <div className={styles.sectionEmpty}>No installed datasets yet.</div>
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
