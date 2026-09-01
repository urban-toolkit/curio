import React, { useCallback, useEffect, useMemo, useRef } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { DrawerFooter } from "../../packages/publishing/DrawerFooter";
import { DrawerHeader } from "../../packages/publishing/DrawerHeader";
import tabStyles from "../../packages/publishing/DrawerTabs.module.css";
import {
  DATASET_IMPORT_ACCEPT,
  DatasetSortMode,
  isInThisDataflow,
  pendingInstallsNotYetListed,
} from "../../../services/datasetCatalog";
import { DatasetCard } from "./DatasetCard";
import { DatasetInstallingCard } from "./DatasetInstallingCard";
import { DatasetDetailModal } from "./DatasetDetailModal";
import { useDatasetCatalogDrawer } from "./useDatasetCatalogDrawer";
import { PackageSearchRow } from "components/packages/publishing/PackageSearchRow";
import shell from "components/packages/publishing/CatalogDrawerShell.module.css";
import styles from "./DatasetCatalogDrawer.module.css";
import ConfirmDialog from "../../ConfirmDialog";
import { modalStackDepth } from "../../ModalShell";

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
    confirmAction,
    dismissConfirm,
  } = useDatasetCatalogDrawer(presented);

  // Escape dismisses this drawer, as it does the Node and Agent ones. It was
  // the only one of the three without a handler, so a user who had learned the
  // gesture on either peer pressed it here and nothing happened.
  //
  // Two conditions, both shared with the Agent drawer: a modal rendered on top
  // (the add/remove confirmation, the dataset detail) owns Escape while it is
  // open, and a pinned drawer is being deliberately kept open.
  useEffect(() => {
    if (!presented) return;
    const onKey = (ev: KeyboardEvent) => {
      if (modalStackDepth() > 0) return;
      if (ev.key === "Escape" && !pinned) onRequestClose?.();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [presented, pinned, onRequestClose]);

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
        className={`${shell.overlayRoot} ${styles.overlayRoot} ${
          presented ? shell.overlayRootPresented : ""
        }`}
        data-curio-dataset-catalog-drawer="true"
        aria-hidden={!presented}
      >
        <button
          type="button"
          className={shell.scrim}
          aria-label="Close dataset catalog"
          onClick={() => {
            if (!pinned) onRequestClose();
          }}
        />
        <aside
          ref={drawerRef}
          className={shell.drawer}
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
            closeAriaLabel="Close Data Catalog drawer"
          />

          {/* Typed with the dataset sort contract ("recent" | "name") — the
              values the backend actually documents (dev/74). */}
          <PackageSearchRow
            search={search}
            sort={sort}
            onSearchChange={(value) => startUiTransition(() => setSearch(value))}
            onSortChange={setSort}
            placeholder="Search datasets, publishers, tags…"
            sortAriaLabel="Sort datasets"
            sortOptions={[
              { value: "recent", label: "Sort: Recent activity" },
              { value: "name", label: "Sort: Name" },
            ]}
          />

          <nav className={tabStyles.tabs} aria-label="Data Catalog sections">
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
              In project
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

          <main className={shell.scrollBody}>
            {catalog.error ? <div className={shell.error}>{catalog.error}</div> : null}
            {catalog.loading && items.length === 0 ? (
              <div className={styles.skeletonList} aria-busy="true" aria-label="Loading datasets">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className={styles.skeletonCard} />
                ))}
              </div>
            ) : null}
            {/* One card for every tab. "In project" rendered
                `InstalledDatasetsList` - a separate compact row list with its
                own actions - so this drawer showed its tabs in two visual
                languages, and neither matched the Agent drawer. The Node drawer
                had the same split and lost it for the same reason. */}
            {(
              <>
                {!catalog.loading && !catalog.error && items.length === 0 && installingRows.length === 0 ? (
                  <div className={shell.empty}>
                    {tab === "installed"
                      ? "No datasets added to this dataflow yet."
                      : tab === "computed"
                      ? "No computed datasets yet. Run a dataflow node that outputs a table. It is saved to your Data Catalog and can be added to a dataflow from here."
                      : "No datasets match the current filters."}
                  </div>
                ) : null}
                <div className={shell.cardList}>
                  {installingRows.map((pending) => (
                    <DatasetInstallingCard key={`pending:${pending.key}`} pending={pending} />
                  ))}
                  {items.map((dataset) => {
                    // Installed state is driven by the ``installed`` flag (the
                    // dataset is referenced by the open dataflow). Imported
                    // datasets are register-only account-level items now, so
                    // origin is NOT a proxy for installed - only ``source_node``
                    // datasets (a data-loading node's own output in this flow)
                    // are installed by nature.
                    // `isInThisDataflow`, the same predicate the "In project"
                    // tab filters on. A bare `dataset.installed` disagreed with
                    // it: before the first save nothing is `installed`, so a
                    // dataset listed under "In project" - because it is in all
                    // projects, and so in this one the moment it saves - was
                    // handed a card offering "Add to project". Listed as in,
                    // told it was out.
                    const isInstalled =
                      isInThisDataflow(dataset, Boolean(projectId))
                      || dataset.origin === "source_node";
                    return (
                      <DatasetCard
                        key={`${dataset.origin}:${dataset.id}`}
                        dataset={dataset}
                        isInstalled={isInstalled}
                        busy={busyId === dataset.id || publishingId === dataset.id}
                        onDragStart={(event) => handleDatasetDragStart(dataset, event)}
                        onDragEnd={handleDatasetDragEnd}
                        onInstall={(row) => void onInstall(row)}
                        onUninstall={(row) => void onUninstall(row)}
                        // Passed unconditionally: the button shows disabled in
                        // an unsaved dataflow rather than disappearing, so a
                        // card under "In project" always has the control that
                        // takes it back out. Its two peers do the same.
                        hasProject={Boolean(projectId)}
                        // No publish/unpublish here: those are account-level
                        // decisions and they live in the Data Catalog page's
                        // detail drawer with the rest of them.
                        onDelete={(row) => void onDelete(row)}
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
            /* Text only: `DrawerFooter` renders the shared icon itself, so
               every drawer's import wears the same one. */
            label={busyId === "import" ? "Importing…" : "Import dataset"}
            onSideload={(file) => void onPickImport(file)}
          />
        </aside>
      </div>

      {detailDatasetId ? (
        <DatasetDetailModal
          canvasAvailable
          datasetId={detailDatasetId}
          dataflowId={projectId}
          liveOutputs={liveOutputs}
          fallbackDataset={detailFallback}
          onClose={closeDatasetDetails}
        />
      ) : null}

      {confirmAction ? (
        <ConfirmDialog
          title={confirmAction.title}
          body={confirmAction.body}
          confirmLabel={confirmAction.confirmLabel}
          destructive={confirmAction.destructive}
          layer="overlay"
          onCancel={dismissConfirm}
          onConfirm={() => {
            const { run } = confirmAction;
            dismissConfirm();
            void run();
          }}
        />
      ) : null}
    </>
  );
};
