import React, { memo, useEffect, useMemo, useRef, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faChevronLeft,
  faChevronRight,
  faDatabase,
} from "@fortawesome/free-solid-svg-icons";
import { useFlowContext } from "../../../../providers/FlowProvider";
import { useDatasetCatalogDrawer } from "../../../../providers/datasetCatalog";
import { PaletteDragHint } from "../PaletteDragHint";
import { useDatasetPalette } from "../../../../providers/DatasetPaletteContext";
import { PaletteAccordion } from "../paletteAccordion";
import {
  DATASET_CATALOG_REFRESH_EVENT,
  groupDatasetsForPalette,
  isInThisDataflow,
  isUserInstalledDataset,
  useDatasetCatalog,
  prefetchDatasetCatalog,
} from "../../../../services/datasetCatalog";
import { TOOLS_PALETTE_DROPDOWN_ATTR, TOOLS_PALETTE_PANEL_ATTR } from "../toolsPaletteDismiss";
import { buildSaveableLiveOutputs } from "../../../../utils/saveOutputDataset";
import { DatasetGroupRow, DatasetRow } from "./DatasetPaletteRows";
import { DatasetInstallingRow } from "./DatasetInstallingRow";
import { pendingInstallsNotYetListed } from "../../../../services/datasetCatalog/pendingInstallView";
import { isSavedOutputOfDataflow } from "../../../../services/datasetCatalog/producerLinkage";
import { useDatasetDetails } from "../../../datasets/catalog/datasetDetailsContext";
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
  const { openDatasetDetails } = useDatasetDetails();

  // Saveable session outputs, so a node's freshly computed output is listed
  // before the next project save. buildSaveableLiveOutputs returns undefined
  // when nothing is saveable, so the common default-off workflow keeps a
  // stable fetch key and never churns.
  const liveOutputs = useMemo(
    () => buildSaveableLiveOutputs(outputs, nodes, defaultSaveOutputDataset),
    [outputs, nodes, defaultSaveOutputDataset],
  );

  const catalog = useDatasetCatalog({
    dataflowId: projectId,
    // Matches the drawer. `false` was not a narrower view of the same data - it
    // takes a different branch server-side: with no `dataflowId` the listing
    // then skips `user_store.list_items()` entirely, so the account's datasets
    // were not in the response at all and nothing could mark them. That is why
    // this palette and the Data Catalog drawer disagreed about the very same
    // dataflow, and why a dataset added to all projects appeared in one and not
    // the other. With a project open the extra rows are filtered out below by
    // `isInThisDataflow` anyway, so this only ever adds what was missing.
    includeHub: true,
    sort: "recent",
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
    // `isInThisDataflow`, not `isUserInstalledDataset`: with no project yet
    // nothing is `installed`, and this palette rendered empty even for datasets
    // the user had just added to every project.
    () => rows.filter((item) => isInThisDataflow(item, Boolean(projectId))),
    [rows, projectId],
  );

  // Fold multilayer OSM PBF imports (layers sharing a groupId) into collapsible
  // groups; every other dataset stays a single row. Each layer remains an
  // ordinary, individually draggable DatasetRow inside its group. The palette
  // keeps the listing's order, the catalog's Recent activity (`sort: "recent"`
  // above), and a group sits where its first layer is listed.
  const paletteEntries = useMemo(
    () => groupDatasetsForPalette(installedRows),
    [installedRows],
  );

  // Outputs this dataflow's nodes saved to the account (#217). They are not in
  // the project, so they get their own group, and a run's placeholder is
  // replaced by its row there instead of vanishing.
  const savedOutputRows = useMemo(() => {
    const listed = new Set(installedRows.map((item) => item.id));
    return rows.filter(
      (item) => !listed.has(item.id) && isSavedOutputOfDataflow(item, projectId),
    );
  }, [rows, installedRows, projectId]);

  // In-flight installs without a real row yet, rendered as "Adding…"
  // placeholders above the rows.
  // placeholders, each in the group its row lands in: a run's output in Saved
  // outputs, anything else in the project's datasets.
  const installingRows = useMemo(
    () => pendingInstallsNotYetListed(pendingInstalls, [...installedRows, ...savedOutputRows]),
    [pendingInstalls, installedRows, savedOutputRows],
  );
  const savingRows = installingRows.filter((pending) => Boolean(pending.producerNodeId));
  const addingRows = installingRows.filter((pending) => !pending.producerNodeId);
  const projectCount = installedRows.length + addingRows.length;
  const savedCount = savedOutputRows.length + savingRows.length;

  // Count what the palette actually shows so the trigger badge stays
  // consistent with the list and does not visibly jump when a placeholder is
  // replaced by its real row.
  const total = projectCount + savedCount;

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
        if (attempts < maxAttempts) {
          window.requestAnimationFrame(tryReveal);
          return;
        }
        // No row lists it here (#441): show the dataset's details instead.
        const listed = catalog.items.find((item) => item.id === datasetRevealId);
        openDatasetDetails(datasetRevealId, listed ? { fallbackDataset: listed } : undefined);
        setDatasetRevealId(null);
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
  }, [open, datasetRevealId, setDatasetRevealId, installedRows, savedOutputRows, catalog.items, openDatasetDetails]);

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
          // The count below is being fetched again (after a save, an install
          // or an import), so the number shown may be about to change.
          aria-busy={catalog.loading || catalog.refreshing}
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
              title="Datasets in project"
              count={projectCount}
              selected
              defaultOpen
              /* No sort toggle. Neither peer palette has one, it toggled
                 between two near-identical timestamps ("Import date" /
                 "Added date") that differ only for a dataset installed long
                 after it was imported, and it sat in the accordion's summary
                 row where it competed with the row's own click target. The
                 list keeps its stable default order. */
            >
              {addingRows.map((pending) => (
                <DatasetInstallingRow key={`pending:${pending.key}`} pending={pending} />
              ))}
              {installedRows.length > 0 ? (
                paletteEntries.map((entry) =>
                  entry.kind === "group" ? (
                    <DatasetGroupRow key={`group:${entry.groupId}`} group={entry} />
                  ) : (
                    <DatasetRow
                      key={`${entry.dataset.origin}:${entry.dataset.id}`}
                      dataset={entry.dataset}
                    />
                  ),
                )
              ) : addingRows.length === 0 ? (
                <div className={styles.sectionEmpty}>No datasets added yet.</div>
              ) : null}
            </PaletteAccordion>
            {savedCount > 0 ? (
              <PaletteAccordion title="Saved outputs" count={savedCount} defaultOpen>
                {savingRows.map((pending) => (
                  <DatasetInstallingRow key={`pending:${pending.key}`} pending={pending} />
                ))}
                {savedOutputRows.map((dataset) => (
                  <DatasetRow key={`${dataset.origin}:${dataset.id}`} dataset={dataset} />
                ))}
              </PaletteAccordion>
            ) : null}
          </div>
          <div className={styles.footer}>
            <PaletteDragHint item="dataset" />
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
