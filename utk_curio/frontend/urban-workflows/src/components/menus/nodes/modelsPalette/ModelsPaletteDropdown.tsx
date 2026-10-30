import React, { memo, useEffect, useMemo, useRef, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faBrain, faChevronLeft, faChevronRight } from "@fortawesome/free-solid-svg-icons";

import { useFlowContext } from "../../../../providers/FlowProvider";
import { useModelCatalogDrawer } from "../../../../providers/modelCatalog";
import { useModelPackages, type PackagePayload } from "../../../../services/packages";
import { PackageDetailModal } from "../../../packages/publishing/PackageDetailModal";
import { PaletteDragHint } from "../PaletteDragHint";
import { PaletteAccordion } from "../paletteAccordion";
import { TOOLS_PALETTE_DROPDOWN_ATTR, TOOLS_PALETTE_PANEL_ATTR } from "../toolsPaletteDismiss";
import { ModelPaletteRow } from "./ModelPaletteRow";
import styles from "./ModelsPalette.module.css";

/**
 * The Model Catalog tools-panel palette. Shares the Datasets, Packages and
 * Agents pattern (dark vertical trigger card, dark dropdown panel, catalog
 * footer). Like the Data Catalog palette's "Datasets in project", it lists
 * what the open dataflow has: the model packages its lockfile names, the set
 * the Model Catalog drawer's In project tab lists, as draggable rows to drop
 * onto a node or the canvas. "Browse Model Catalog +" opens the drawer, where
 * any other model is added to the dataflow.
 */
export const ModelsPaletteDropdown = memo(function ModelsPaletteDropdown({
  open,
  setOpen,
}: {
  /** Owned by ToolsMenu: the palettes share one strip, so only one may be
   *  open. Uncontrolled state here would let two open at once. */
  open: boolean;
  setOpen: (value: boolean) => void;
}) {
  // `packages` is the dataflow's lockfile, the one the drawer's Add, Remove
  // and Import write; the drawer's In project tab reads the same list.
  const { projectDirty, whenChangesKept, packages: dataflowPackages } = useFlowContext();
  const { openModelCatalogDrawer } = useModelCatalogDrawer();
  // Fetched with the rail, as the other palettes are, so the trigger's count
  // is right before the palette is first opened.
  const catalog = useModelPackages();
  const [detailModel, setDetailModel] = useState<PackagePayload | null>(null);

  // A model can join the lockfile before this listing holds it: Import
  // package and Save as package make a new model and add it to the dataflow
  // at once. So the listing is read again whenever the lockfile changes.
  const { reload } = catalog;
  const lockfileKey = dataflowPackages.join("\n");
  const readForLockfile = useRef(lockfileKey);
  useEffect(() => {
    if (readForLockfile.current === lockfileKey) return;
    readForLockfile.current = lockfileKey;
    reload();
  }, [lockfileKey, reload]);

  const models = useMemo(() => {
    const declared = new Set(dataflowPackages);
    return catalog.models.filter((model) => declared.has(model.dirName));
  }, [catalog.models, dataflowPackages]);
  // The trigger counts what the palette lists.
  const total = models.length;

  // No Escape / outside-click dismissal on purpose: the palette stays open
  // until its own trigger is clicked again (or another palette claims the
  // strip), the same rule its three peers state.

  return (
    <div
      id="models-palette"
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
          data-tooltip={open ? "Close model palette" : "Open model palette"}
        >
          <span className={styles.triggerTop}>
            <FontAwesomeIcon icon={faBrain} className={styles.triggerIcon} />
            <span className={styles.triggerCount}>{total}</span>
            <FontAwesomeIcon
              icon={open ? faChevronLeft : faChevronRight}
              className={styles.triggerChevron}
            />
          </span>
          <span className={styles.triggerLabel}>Model Catalog</span>
        </button>
      </div>
      {open ? (
        /* TOOLS_PALETTE_PANEL_ATTR marks this panel as occluding the canvas,
           as its peers do, so Fit View sizes the graph around it. */
        <div
          className={styles.panel}
          role="region"
          aria-label="Model palette"
          {...{ [TOOLS_PALETTE_PANEL_ATTR]: "true" }}
        >
          <div className={styles.panelHeader}>
            <div className={styles.title}>Models</div>
          </div>
          <div className={styles.scroll}>
            {catalog.loading && catalog.models.length === 0 ? (
              <div className={styles.empty}>Loading models...</div>
            ) : null}
            {!catalog.loading && total === 0 ? (
              <div className={styles.empty}>
                {catalog.error ?? "Add or import a model to use it here."}
              </div>
            ) : null}
            <PaletteAccordion title="Models in project" count={total} selected defaultOpen>
              {total > 0 ? (
                models.map((model) => (
                  <ModelPaletteRow
                    key={model.dirName}
                    model={model}
                    onOpenDetails={setDetailModel}
                  />
                ))
              ) : (
                <div className={styles.sectionEmpty}>No models added yet.</div>
              )}
            </PaletteAccordion>
          </div>
          <div className={styles.footer}>
            <PaletteDragHint item="model" ontoNodeOnly />
            <button
              type="button"
              className={styles.catalogButton}
              onClick={() => openModelCatalogDrawer()}
            >
              Browse Model Catalog +
            </button>
          </div>
        </div>
      ) : null}
      {detailModel ? (
        <PackageDetailModal
          pkg={detailModel}
          unsavedChanges={projectDirty}
          whenChangesKept={whenChangesKept}
          onClose={() => setDetailModel(null)}
        />
      ) : null}
    </div>
  );
});
