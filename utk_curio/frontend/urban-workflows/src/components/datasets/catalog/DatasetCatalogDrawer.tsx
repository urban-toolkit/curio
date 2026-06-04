import React, { useCallback, useRef } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faFileImport, faThumbtack, faXmark } from "@fortawesome/free-solid-svg-icons";
import type { DatasetSortMode } from "../../../services/datasetCatalog";
import { DatasetCard } from "./DatasetCard";
import { DatasetDetailModal } from "./DatasetDetailModal";
import { InstalledDatasetsList } from "./InstalledDatasetsList";
import { TAB_LABEL } from "./datasetCatalogDrawerTypes";
import { useDatasetCatalogDrawer } from "./useDatasetCatalogDrawer";
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
    fileInputRef,
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
    tabInstalledCount,
    tabComputedCount,
    startUiTransition,
    onInstall,
    onUninstall,
    onPublish,
    onUnpublish,
    onPickImport,
    handleDatasetDragStart,
    handleDatasetDragEnd,
    openDatasetDetails,
    closeDatasetDetails,
  } = useDatasetCatalogDrawer(presented);

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
          <header className={styles.header}>
            <button
              type="button"
              className={`${styles.pinButton} ${pinned ? styles.pinButtonActive : ""}`}
              aria-label={pinned ? "Unpin drawer" : "Pin drawer open"}
              aria-pressed={pinned}
              title={pinned ? "Unpin drawer" : "Pin drawer (scrim won't close)"}
              onClick={() => setPinned((v) => !v)}
            >
              <FontAwesomeIcon icon={faThumbtack} aria-hidden />
            </button>
            <div className={styles.titleBlock}>
              <h2 id="dataset-catalog-title" className={styles.title}>
                Data Catalog
              </h2>
              <p className={styles.subtitle}>Datasets available to this dataflow.</p>
            </div>
            <button className={styles.closeButton} type="button" onClick={onRequestClose} aria-label="Close">
              <FontAwesomeIcon icon={faXmark} />
            </button>
          </header>

          <div className={styles.searchBar}>
            <input
              className={styles.searchInput}
              type="search"
              placeholder="Search datasets, sources..."
              value={search}
              onChange={(event) => {
                const value = event.target.value;
                startUiTransition(() => setSearch(value));
              }}
            />
            <select
              className={styles.sortSelect}
              value={sort}
              aria-label="Sort datasets"
              onChange={(event) => setSort(event.target.value as DatasetSortMode)}
            >
              <option value="recent">Sort: New</option>
              <option value="name">Sort: Name</option>
            </select>
          </div>

          <div className={styles.tabs}>
            <button
              type="button"
              className={`${styles.tab} ${tab === "featured" ? styles.tabActive : ""}`}
              onClick={() => startUiTransition(() => setTab("featured"))}
            >
              Featured
            </button>
            <button
              type="button"
              className={`${styles.tab} ${tab === "browse" ? styles.tabActive : ""}`}
              onClick={() => startUiTransition(() => setTab("browse"))}
            >
              Browse all
            </button>
            <button
              type="button"
              className={`${styles.tab} ${tab === "installed" ? styles.tabActive : ""}`}
              onClick={() => startUiTransition(() => setTab("installed"))}
            >
              Installed <span>{tabInstalledCount}</span>
            </button>
            <button
              type="button"
              className={`${styles.tab} ${tab === "computed" ? styles.tabActive : ""}`}
              onClick={() => startUiTransition(() => setTab("computed"))}
            >
              Computed <span>{tabComputedCount}</span>
            </button>
          </div>

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
              !catalog.loading && !catalog.error && items.length === 0 ? (
                <div className={styles.empty}>No datasets installed in this dataflow yet.</div>
              ) : (
                <InstalledDatasetsList
                  datasets={items}
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
                {!catalog.loading && !catalog.error && items.length === 0 ? (
                  <div className={styles.empty}>
                    {tab === "computed"
                      ? "No computed datasets yet. Run a dataflow node that outputs a table — it will appear here and be installed automatically."
                      : "No datasets match the current filters."}
                  </div>
                ) : null}
                <div className={styles.cardList}>
                  {items.map((dataset) => {
                    const isComputedInstalled =
                      dataset.origin === "computed" && dataset.installed === true;
                    const isInstalled =
                      isComputedInstalled ||
                      (!isComputedInstalled &&
                        (dataset.installed === true ||
                          (dataset.origin !== "hub" && dataset.origin !== "computed")));
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
                          projectId && !isComputedInstalled
                            ? (row) => void onUninstall(row)
                            : undefined
                        }
                        onUnpublish={
                          isPublished && isInstalled ? (row) => void onUnpublish(row) : undefined
                        }
                        onPublish={(datasetId) => void onPublish(datasetId)}
                        onOpenDetails={openDatasetDetails}
                      />
                    );
                  })}
                </div>
              </>
            )}
            <div className={styles.assistNote}>
              <strong>Shared dataflow environment</strong>
              <span>
                Drag a dataset onto a loader node to fill path, schema, ports, and required loader
                code.
              </span>
            </div>
          </main>

          <footer className={styles.footer}>
            <input
              ref={fileInputRef}
              className={styles.fileInput}
              type="file"
              onChange={(event) => {
                const file = event.currentTarget.files?.[0];
                if (file) void onPickImport(file);
                event.currentTarget.value = "";
              }}
            />
            <button
              type="button"
              className={styles.importButton}
              disabled={busyId === "import"}
              onClick={() => fileInputRef.current?.click()}
            >
              <FontAwesomeIcon icon={faFileImport} />{" "}
              {busyId === "import" ? "Importing..." : "Import dataset"}
            </button>
          </footer>
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
