import React, { useCallback, useMemo, useRef } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faFileImport } from "@fortawesome/free-solid-svg-icons";
import { DrawerFooter } from "../../packages/publishing/DrawerFooter";
import { DrawerHeader } from "../../packages/publishing/DrawerHeader";
import tabStyles from "../../packages/publishing/DrawerTabs.module.css";
import {
  DATASET_IMPORT_ACCEPT,
  pendingInstallsNotYetListed,
} from "../../../services/datasetCatalog";
import { DatasetCard } from "./DatasetCard";
import { DatasetInstallingCard } from "./DatasetInstallingCard";
import { DatasetDetailModal } from "./DatasetDetailModal";
import { InstalledDatasetsList } from "./InstalledDatasetsList";
import { TAB_LABEL } from "./datasetCatalogDrawerTypes";
import { useDatasetCatalogDrawer } from "./useDatasetCatalogDrawer";
import { PackageSearchRow } from "components/packages/publishing/PackageSearchRow";
import { SortMode } from "components/packages/publishing/packageTypes";
import styles from "./DatasetCatalogDrawer.module.css";

export interface DatasetCatalogDrawerProps {
  presented: boolean;
  onRequestClose: () => void;
  onExitComplete: () => void;
}

export const DatasetCatalogDrawer: React.FC<DatasetCatalogDrawerProps> = ({
  presented,
  onRequestClose,
  onExitComplete,
}) => {
  const drawerRef = useRef<HTMLElement>(null);
  const {
    projectId,
    tab,
    setTab,
    search,
    setSearch,
    sort,
    setSort,
    pinned,
    setPinned,
    busyId,
    publishingId,
    detailDatasetId,
    detailFallback,
    liveOutputs,
    catalog,
    items,
    pendingInstalls,
    tabInstalledCount,
    tabComputedCount,
    startUiTransition,
    onInstall,
    onUninstall,
    onPublish,
    onUnpublish,
    onDelete,
    onPickImport,
    handleDatasetDragStart,
    handleDatasetDragEnd,
    openDatasetDetails,
    closeDatasetDetails,
  } = useDatasetCatalogDrawer(presented);

  // In-flight installs without a real installed row yet → "Installing…" cards.
  // Match against genuinely-installed items only (an un-installed hub/computed row
  // sharing the id must not suppress the placeholder while the install runs).
  const installingRows = useMemo(() => {
    const installed = items.filter(
      (it) => it.installed === true || (it.origin !== "hub" && it.origin !== "computed"),
    );
    return pendingInstallsNotYetListed(pendingInstalls, installed);
  }, [pendingInstalls, items]);

  const handleDrawerTransitionEnd = useCallback(
    (e: React.TransitionEvent<HTMLElement>) => {
      if (e.target !== drawerRef.current || e.propertyName !== "transform" || presented) return;
      onExitComplete();
    },
    [onExitComplete, presented],
  );

  return (
    <>
      <div
        className={`${styles.overlayRoot} ${presented ? styles.overlayRootPresented : ""}`}
        data-curio-dataset-catalog-drawer="true"
        aria-hidden={!presented}
      >
        <button
          type="button"
          className={styles.scrim}
          aria-label="Close dataset catalog"
          onClick={() => {
            if (!pinned) onRequestClose();
          }}
        />
        <aside
          ref={drawerRef}
          className={styles.drawer}
          role="dialog"
          aria-modal="true"
          aria-labelledby="dataset-catalog-title"
          tabIndex={-1}
          onTransitionEnd={handleDrawerTransitionEnd}
        >
          <DrawerHeader
            pinned={pinned}
            onPinToggle={() => setPinned((v) => !v)}
            onClose={onRequestClose}
            kind="dataset"
            title="Data Catalog"
            titleId="dataset-catalog-title"
            subtitle="Datasets available to this dataflow."
            closeAriaLabel="Close data catalog drawer"
          />

          <PackageSearchRow
            search={search}
            sort={sort as SortMode}
            onSearchChange={(value) => startUiTransition(() => setSearch(value))}
            onSortChange={setSort as (value: SortMode) => void}
          />

          <nav className={tabStyles.tabs} aria-label="Data catalog sections">
            <button
              type="button"
              className={`${tabStyles.tab} ${tab === "featured" ? tabStyles.tabActive : ""}`}
              onClick={() => startUiTransition(() => setTab("featured"))}
            >
              Featured
            </button>
            <button
              type="button"
              className={`${tabStyles.tab} ${tab === "browse" ? tabStyles.tabActive : ""}`}
              onClick={() => startUiTransition(() => setTab("browse"))}
            >
              Browse all
            </button>
            <button
              type="button"
              className={`${tabStyles.tab} ${tab === "installed" ? tabStyles.tabActive : ""}`}
              onClick={() => startUiTransition(() => setTab("installed"))}
            >
              Installed
              {tabInstalledCount > 0 ? (
                <span className={`${tabStyles.tabBadge} ${tabStyles.tabBadgeDark}`}>
                  {tabInstalledCount}
                </span>
              ) : null}
            </button>
            <button
              type="button"
              className={`${tabStyles.tab} ${tab === "computed" ? tabStyles.tabActive : ""} ${
                tabComputedCount === 0 ? tabStyles.tabMuted : ""
              }`}
              onClick={() => startUiTransition(() => setTab("computed"))}
            >
              Computed
              {tabComputedCount > 0 ? (
                <span className={`${tabStyles.tabBadge} ${tabStyles.tabBadgeDark}`}>
                  {tabComputedCount}
                </span>
              ) : null}
            </button>
          </nav>

          <main className={styles.content}>
            {catalog.error ? <div className={styles.error}>{catalog.error}</div> : null}
            {catalog.loading && items.length === 0 ? (
              <div className={styles.skeletonList} aria-busy="true" aria-label="Loading datasets">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className={styles.skeletonCard} />
                ))}
              </div>
            ) : null}
            {tab === "installed" ? (
              !catalog.loading && !catalog.error && items.length === 0 && installingRows.length === 0 ? (
                <div className={styles.empty}>No datasets installed in this dataflow yet.</div>
              ) : (
                <InstalledDatasetsList
                  datasets={items}
                  installing={installingRows}
                  busy={busyId != null || publishingId != null}
                  publishingId={publishingId}
                  onUninstall={projectId ? (dataset) => void onUninstall(dataset) : undefined}
                  onPublish={(datasetId) => void onPublish(datasetId)}
                  onDragStart={handleDatasetDragStart}
                  onDragEnd={handleDatasetDragEnd}
                  refreshing={false}
                />
              )
            ) : (
              <>
                {!catalog.error ? <p className={styles.sectionLabel}>{TAB_LABEL[tab]}</p> : null}
                {!catalog.loading && !catalog.error && items.length === 0 && installingRows.length === 0 ? (
                  <div className={styles.empty}>
                    {tab === "computed"
                      ? "No computed datasets yet. Run a dataflow node that outputs a table — it is saved to your Data Catalog and can be installed into a project from here."
                      : "No datasets match the current filters."}
                  </div>
                ) : null}
                <div className={styles.cardList}>
                  {installingRows.map((pending) => (
                    <DatasetInstallingCard key={`pending:${pending.key}`} pending={pending} />
                  ))}
                  {items.map((dataset) => {
                    // Installed state is driven by the ``installed`` flag (the
                    // dataset is referenced by the open dataflow). Imported
                    // datasets are register-only account-level items now, so
                    // origin is NOT a proxy for installed — only ``source_node``
                    // datasets (a data-loading node's own output in this flow)
                    // are installed by nature.
                    const isInstalled =
                      dataset.installed === true || dataset.origin === "source_node";
                    const isPublished = dataset.origin === "hub" || dataset.publishedToHub === true;
                    return (
                      <DatasetCard
                        key={`${dataset.origin}:${dataset.id}`}
                        dataset={dataset}
                        isInstalled={isInstalled}
                        isPublished={isPublished}
                        busy={busyId === dataset.id || publishingId === dataset.id}
                        publishingId={publishingId}
                        onDragStart={(event) => handleDatasetDragStart(dataset, event)}
                        onDragEnd={handleDatasetDragEnd}
                        onInstall={(row) => void onInstall(row)}
                        onUninstall={
                          projectId
                            ? (row) => void onUninstall(row)
                            : undefined
                        }
                        onUnpublish={
                          isPublished && isInstalled ? (row) => void onUnpublish(row) : undefined
                        }
                        onDelete={(row) => void onDelete(row)}
                        onPublish={(datasetId) => void onPublish(datasetId)}
                        onOpenDetails={openDatasetDetails}
                      />
                    );
                  })}
                </div>
              </>
            )}
          </main>

          <DrawerFooter
            busy={busyId === "import"}
            accept={DATASET_IMPORT_ACCEPT}
            label={
              <>
                <FontAwesomeIcon icon={faFileImport} />{" "}
                {busyId === "import" ? "Importing..." : "Import dataset"}
              </>
            }
            onSideload={(file) => void onPickImport(file)}
          />
        </aside>
      </div>

      {detailDatasetId ? (
        <DatasetDetailModal
          datasetId={detailDatasetId}
          dataflowId={projectId}
          liveOutputs={liveOutputs}
          fallbackDataset={detailFallback}
          onClose={closeDatasetDetails}
        />
      ) : null}
    </>
  );
};
