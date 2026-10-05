import React, { useCallback, useEffect, useRef } from "react";

import { DrawerHeader } from "../../packages/publishing/DrawerHeader";
import { PackageSearchRow } from "../../packages/publishing/PackageSearchRow";
import shell from "../../packages/publishing/CatalogDrawerShell.module.css";
import ConfirmDialog from "../../ConfirmDialog";
import { modalStackDepth } from "../../ModalShell";
import { useFlowContext } from "../../../providers/FlowProvider";
import { MODEL_SORT_OPTIONS } from "../../../services/modelCatalog";
import { ModelCard } from "./ModelCard";
import { ModelDetailModal } from "./ModelDetailModal";
import { useModelCatalogDrawer } from "./useModelCatalogDrawer";
import styles from "./ModelCatalogDrawer.module.css";

export interface ModelCatalogDrawerProps {
  presented: boolean;
  onRequestClose: () => void;
  onExitComplete: () => void;
}

/**
 * The Model Catalog on the canvas: every model this account can run, each a
 * card to drag onto a node that runs one.
 *
 * Built like the Data drawer (the same shell, header and search row, the same
 * card shape, Escape and pin rules), with less in it: a model is named in a
 * node's code rather than installed into a dataflow, so there is no tab strip
 * and no add or remove, and models arrive from the Discovery Catalog, so there
 * is no import footer.
 */
export const ModelCatalogDrawer: React.FC<ModelCatalogDrawerProps> = ({
  presented,
  onRequestClose,
  onExitComplete,
}) => {
  const drawerRef = useRef<HTMLElement>(null);
  const { projectDirty } = useFlowContext();
  const {
    search,
    setSearch,
    sort,
    setSort,
    pinned,
    setPinned,
    busyId,
    catalog,
    items,
    onDelete,
    confirmAction,
    dismissConfirm,
    handleModelDragStart,
    handleModelDragEnd,
    detailModel,
    openModelDetails,
    closeModelDetails,
  } = useModelCatalogDrawer(presented);

  // Escape dismisses this drawer, as it does its peers: a modal on top (the
  // delete confirmation, a model's details) owns Escape while it is open, and
  // a pinned drawer is being deliberately kept open.
  useEffect(() => {
    if (!presented) return;
    const onKey = (ev: KeyboardEvent) => {
      if (modalStackDepth() > 0) return;
      if (ev.key === "Escape" && !pinned) onRequestClose?.();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [presented, pinned, onRequestClose]);

  const handleDrawerTransitionEnd = useCallback(
    (e: React.TransitionEvent<HTMLElement>) => {
      if (e.target !== drawerRef.current || e.propertyName !== "transform" || presented) return;
      onExitComplete();
    },
    [onExitComplete, presented],
  );

  const searching = search.trim().length > 0;

  return (
    <>
      <div
        className={`${shell.overlayRoot} ${styles.overlayRoot} ${
          presented ? shell.overlayRootPresented : ""
        }`}
        data-curio-model-catalog-drawer="true"
        aria-hidden={!presented}
      >
        <button
          type="button"
          className={shell.scrim}
          aria-label="Close model catalog"
          onClick={() => {
            if (!pinned) onRequestClose();
          }}
        />
        <aside
          ref={drawerRef}
          className={shell.drawer}
          role="dialog"
          aria-modal="true"
          aria-labelledby="model-catalog-title"
          tabIndex={-1}
          onTransitionEnd={handleDrawerTransitionEnd}
        >
          <DrawerHeader
            pinned={pinned}
            onPinToggle={() => setPinned((v) => !v)}
            onClose={onRequestClose}
            kind="model"
            title="Model Catalog"
            titleId="model-catalog-title"
            subtitle="Drag a model onto a node that runs one."
            closeAriaLabel="Close Model Catalog drawer"
          />

          <PackageSearchRow
            search={search}
            sort={sort}
            onSearchChange={setSearch}
            onSortChange={setSort}
            placeholder="Search models, publishers, tags…"
            sortAriaLabel="Sort models"
            sortOptions={MODEL_SORT_OPTIONS}
          />

          <main className={shell.scrollBody}>
            {catalog.error ? <div className={shell.error}>{catalog.error}</div> : null}
            {catalog.loading && items.length === 0 ? (
              <div className={shell.empty} aria-busy="true">
                Loading models…
              </div>
            ) : null}
            {!catalog.loading && !catalog.error && items.length === 0 ? (
              <div className={shell.empty}>
                {searching ? "No models match the current filters." : "Your Model Catalog is empty."}
              </div>
            ) : null}
            <div className={shell.cardList}>
              {items.map((model) => (
                <ModelCard
                  key={`${model.origin}:${model.id}`}
                  model={model}
                  busy={busyId === model.id}
                  onDragStart={(event) => handleModelDragStart(model, event)}
                  onDragEnd={handleModelDragEnd}
                  onDelete={onDelete}
                  onOpenDetails={openModelDetails}
                />
              ))}
            </div>
          </main>
        </aside>
      </div>

      {detailModel ? (
        <ModelDetailModal
          modelId={detailModel.id}
          fallbackModel={detailModel}
          unsavedChanges={projectDirty}
          onClose={closeModelDetails}
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

export default ModelCatalogDrawer;
