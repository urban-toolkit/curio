import React, { memo, useEffect, useMemo, useRef, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faChevronLeft,
  faChevronRight,
  faDatabase,
} from "@fortawesome/free-solid-svg-icons";
import { useFlowContext } from "../../../../providers/FlowProvider";
import { useDatasetCatalogDrawer } from "../../../../providers/datasetCatalog";
import { useDatasetPalette } from "../../../../providers/DatasetPaletteContext";
import { PaletteAccordion } from "../paletteAccordion";
import {
  DATASET_CATALOG_REFRESH_EVENT,
  groupDatasetsForPalette,
  isUserInstalledDataset,
  sortDatasetPaletteEntries,
  useDatasetCatalog,
  prefetchDatasetCatalog,
  type DatasetPaletteSortKey,
} from "../../../../services/datasetCatalog";
import { TOOLS_PALETTE_DROPDOWN_ATTR, TOOLS_PALETTE_PANEL_ATTR } from "../toolsPaletteDismiss";
import { buildSaveableLiveOutputs } from "../../../../utils/saveOutputDataset";
import { DatasetGroupRow, DatasetRow } from "./DatasetPaletteRows";
import { DatasetInstallingRow } from "./DatasetInstallingRow";
import { pendingInstallsNotYetListed } from "../../../../services/datasetCatalog/pendingInstallView";
import styles from "./DatasetsPaletteDropdown.module.css";

export const DatasetsPaletteDropdown = memo(function DatasetsPaletteDropdown({
  open,
  setOpen,
}: {
  open: boolean;
  setOpen: (open: boolean) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const { projectId, outputs, nodes, defaultSaveOutputDataset, pendingInstalls } = useFlowContext();
  const { openDatasetCatalogDrawer } = useDatasetCatalogDrawer();
  const { datasetRevealId, setDatasetRevealId } = useDatasetPalette();

  // Saveable session outputs — a node's freshly-computed-and-auto-installed dataset
  // isn't in the project manifest yet (no save), so the backend only surfaces it as
  // a computed item when these are passed (then marks it installed from the user
  // store). Without them, just-generated installed computed datasets are invisible
  // here even though the Data Catalog drawer (which passes them) shows them.
  // buildSaveableLiveOutputs returns undefined when nothing is saveable, so the
  // common default-off workflow keeps a stable fetch key and never churns.
  const liveOutputs = useMemo(
    () => buildSaveableLiveOutputs(outputs, nodes, defaultSaveOutputDataset),
    [outputs, nodes, defaultSaveOutputDataset],
  );

  const catalog = useDatasetCatalog({
    dataflowId: projectId,
    includeHub: false,
    sort: "recent",
    // Pass saveable live outputs so genuinely-installed computed datasets appear
    // immediately. The list still filters to installed===true (isUserInstalledDataset),
    // so ephemeral non-installed outputs never show — only the counter/list churns
    // when a saveable output actually lands.
    liveOutputs,
    enabled: true,
  });

  useEffect(() => {
    const onRefresh = () => void catalog.reload();
    window.addEventListener(DATASET_CATALOG_REFRESH_EVENT, onRefresh);
    return () => window.removeEventListener(DATASET_CATALOG_REFRESH_EVENT, onRefresh);
  }, [catalog.reload]);

  // No Escape / outside-click dismissal on purpose: the palette stays open
  // until its own trigger is clicked again (or the packages palette claims the
  // strip), so browsing the canvas or the Data Catalog never collapses it.

  const rows = useMemo(
    () => catalog.items.filter((item) => item.origin === "imported" || item.origin === "hub" || item.origin === "computed"),
    [catalog.items],
  );
  const installedRows = useMemo(
    () => rows.filter((item) => isUserInstalledDataset(item)),
    [rows],
  );

  // Fold multilayer OSM PBF imports (layers sharing a groupId) into collapsible
  // groups; every other dataset stays a single row. Each layer remains an
  // ordinary, individually draggable DatasetRow inside its group.
  const paletteEntries = useMemo(
    () => groupDatasetsForPalette(installedRows),
    [installedRows],
  );

  // Palette sort key. Backed entirely by persisted dataset metadata (import
  // ``createdAt`` / install ``installedAt``), never UI-only state, so the order
  // is stable across reopens. Groups sort as a unit by their representative time.
  const [sortKey, setSortKey] = useState<DatasetPaletteSortKey>("importedAt");
  const sortedEntries = useMemo(
    () => sortDatasetPaletteEntries(paletteEntries, sortKey),
    [paletteEntries, sortKey],
  );

  // In-flight installs without a real installed row yet, rendered as
  // "Adding…" placeholders above the installed rows.
  const installingRows = useMemo(
    () => pendingInstallsNotYetListed(pendingInstalls, installedRows),
    [pendingInstalls, installedRows],
  );

  // Count what the palette actually shows (installed/saved datasets + in-flight
  // placeholders) so the trigger badge stays consistent with the list and does
  // not visibly jump when a placeholder is replaced by its real row.
  const total = installedRows.length + installingRows.length;

  // A node's DATASET chip requests a reveal: open the palette, then scroll the
  // matching row into view and pulse it. Mirrors the package palette behaviour.
  useEffect(() => {
    if (datasetRevealId) setOpen(true);
  }, [datasetRevealId, setOpen]);

  useEffect(() => {
    if (!open || !datasetRevealId) return undefined;
    let cancelled = false;
    let attempts = 0;
    const maxAttempts = 48;
    let pulseTimer: number | undefined;

    const tryReveal = (): void => {
      if (cancelled) return;
      const scrollEl = scrollRef.current;
      const anchor = scrollEl
        ? Array.from(scrollEl.querySelectorAll<HTMLElement>("[data-dataset-id]")).find(
            (el) => el.dataset.datasetId === datasetRevealId,
          )
        : undefined;
      attempts++;
      if (!anchor) {
        if (attempts < maxAttempts) window.requestAnimationFrame(tryReveal);
        else setDatasetRevealId(null);
        return;
      }
      anchor.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
      anchor.classList.add(styles.revealPulse);
      pulseTimer = window.setTimeout(() => anchor.classList.remove(styles.revealPulse), 1400);
      setDatasetRevealId(null);
    };

    const rafId = window.requestAnimationFrame(tryReveal);
    return () => {
      cancelled = true;
      window.cancelAnimationFrame(rafId);
      if (pulseTimer !== undefined) window.clearTimeout(pulseTimer);
    };
  }, [open, datasetRevealId, setDatasetRevealId, installedRows]);

  // Drop a pending reveal when the palette is closed (true→false only).
  const prevOpenRef = useRef(false);
  useEffect(() => {
    if (prevOpenRef.current && !open) setDatasetRevealId(null);
    prevOpenRef.current = open;
  }, [open, setDatasetRevealId]);

  return (
    <div
      id="datasets-palette"
      className={styles.root}
      {...{ [TOOLS_PALETTE_DROPDOWN_ATTR]: "true" }}
    >
      <div className={styles.column}>
        <button
          type="button"
          className={`${styles.trigger} ${open ? styles.triggerOpen : ""}`}
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-haspopup="true"
          title={open ? "Close dataset palette" : "Open dataset palette"}
        >
          <span className={styles.triggerTop}>
            <FontAwesomeIcon icon={faDatabase} className={styles.triggerIcon} />
            <span className={styles.triggerCount}>{total}</span>
            <FontAwesomeIcon
              icon={open ? faChevronLeft : faChevronRight}
              className={styles.triggerChevron}
            />
          </span>
          <span className={styles.triggerLabel}>Data Catalog</span>
        </button>
      </div>
      {open ? (
        <div
          className={styles.panel}
          role="region"
          aria-label="Dataset palette"
          {...{ [TOOLS_PALETTE_PANEL_ATTR]: "true" }}
        >
          <div className={styles.panelHeader}>
            <div className={styles.title}>Datasets</div>
          </div>
          <div className={styles.scroll} ref={scrollRef}>
            {catalog.loading && rows.length === 0 ? <div className={styles.empty}>Loading datasets...</div> : null}
            {!catalog.loading && !catalog.refreshing && total === 0 ? (
              <div className={styles.empty}>
                Add, import, or compute a dataset to use it here.
              </div>
            ) : null}
            <PaletteAccordion
              title="Datasets in dataflow"
              count={total}
              selected
              defaultOpen
              trailing={
                total > 0 ? (
                  <button
                    type="button"
                    className={styles.sortToggle}
                    // Toggle without opening/closing the accordion summary.
                    onClick={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      setSortKey((key) =>
                        key === "importedAt" ? "installedAt" : "importedAt",
                      );
                    }}
                    title="Toggle sort between import time and time added"
                    aria-label={`Sort by ${sortKey === "importedAt" ? "import" : "added"} date; click to change`}
                  >
                    Sort: {sortKey === "importedAt" ? "Import date" : "Added date"}
                  </button>
                ) : null
              }
            >
              {installingRows.map((pending) => (
                <DatasetInstallingRow key={`pending:${pending.key}`} pending={pending} />
              ))}
              {installedRows.length > 0 ? (
                sortedEntries.map((entry) =>
                  entry.kind === "group" ? (
                    <DatasetGroupRow key={`group:${entry.groupId}`} group={entry} />
                  ) : (
                    <DatasetRow
                      key={`${entry.dataset.origin}:${entry.dataset.id}`}
                      dataset={entry.dataset}
                    />
                  ),
                )
              ) : installingRows.length === 0 ? (
                <div className={styles.sectionEmpty}>No datasets added yet.</div>
              ) : null}
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
