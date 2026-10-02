import React, { memo, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faBrain, faChevronLeft, faChevronRight } from "@fortawesome/free-solid-svg-icons";

import { useFlowContext } from "../../../../providers/FlowProvider";
import { useModelCatalogDrawer } from "../../../../providers/modelCatalog";
import { useModelCatalog, type ModelRow } from "../../../../services/modelCatalog";
import { ModelDetailModal } from "../../../models/catalog/ModelDetailModal";
import { PaletteDragHint } from "../PaletteDragHint";
import { PaletteAccordion } from "../paletteAccordion";
import { TOOLS_PALETTE_DROPDOWN_ATTR, TOOLS_PALETTE_PANEL_ATTR } from "../toolsPaletteDismiss";
import { ModelPaletteRow } from "./ModelPaletteRow";
import styles from "./ModelsPalette.module.css";

/**
 * The Model Catalog tools-panel palette. Shares the Datasets, Packages and
 * Agents pattern (dark vertical trigger card, dark dropdown panel, catalog
 * footer), differing only in content: every model this account can run, as
 * draggable rows to drop onto a node, and "Browse Model Catalog +" to open the
 * drawer.
 *
 * Not per project, unlike its peers: a model is not installed into a dataflow,
 * a node names it in its code, so every model is available in every dataflow.
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
  const { projectDirty } = useFlowContext();
  const { openModelCatalogDrawer } = useModelCatalogDrawer();
  // Fetched with the rail, as the other palettes are, so the trigger's count
  // is right before the palette is first opened.
  const catalog = useModelCatalog();
  const models = catalog.data.items;
  const total = models.length;
  const [detailModel, setDetailModel] = useState<ModelRow | null>(null);

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
          title={open ? "Close model palette" : "Open model palette"}
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
            <PaletteAccordion title="Models" count={total} selected defaultOpen>
              {catalog.loading && total === 0 ? (
                <div className={styles.sectionEmpty}>Loading models…</div>
              ) : catalog.error && total === 0 ? (
                <div className={styles.sectionEmpty}>{catalog.error}</div>
              ) : total > 0 ? (
                models.map((model) => (
                  <ModelPaletteRow
                    key={`${model.origin}:${model.id}`}
                    model={model}
                    onOpenDetails={setDetailModel}
                  />
                ))
              ) : (
                <div className={styles.sectionEmpty}>No models yet.</div>
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
        <ModelDetailModal
          modelId={detailModel.id}
          fallbackModel={detailModel}
          unsavedChanges={projectDirty}
          onClose={() => setDetailModel(null)}
        />
      ) : null}
    </div>
  );
});
