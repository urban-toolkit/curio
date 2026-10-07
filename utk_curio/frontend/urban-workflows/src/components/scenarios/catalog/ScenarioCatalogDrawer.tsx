import React, { useCallback, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";

import { DrawerHeader } from "../../packages/publishing/DrawerHeader";
import { PackageSearchRow } from "../../packages/publishing/PackageSearchRow";
import shell from "../../packages/publishing/CatalogDrawerShell.module.css";
import { useDrawerDragThrough } from "../../packages/publishing/useDrawerDragThrough";
import { modalStackDepth } from "../../ModalShell";
import { LEAVE_DATAFLOW, useLeaveGuard } from "../../../hook/useLeaveGuard";
import { useFlowContext } from "../../../providers/FlowProvider";
import { SCENARIO_SORT_OPTIONS, type ScenarioRow } from "../../../services/scenarioCatalog";
import { ScenarioCard } from "./ScenarioCard";
import { ScenarioDetailModal } from "./ScenarioDetailModal";
import { scenarioProjectPath } from "./scenarioFacts";
import { useScenarioCatalogDrawer } from "./useScenarioCatalogDrawer";
import styles from "./ScenarioCatalogDrawer.module.css";

export interface ScenarioCatalogDrawerProps {
  presented: boolean;
  onRequestClose: () => void;
  onExitComplete: () => void;
}

/**
 * The Scenario Catalog on the canvas: every scenario saved in this account's
 * projects, each a card with its project's graph.
 *
 * Built like the Model drawer (the same shell, header and search row, the same
 * card shape, Escape and pin rules). A scenario lives in its project and is
 * edited there, so a card changes nothing in it. A card offers its details,
 * the way to its project, which asks first when this dataflow has unsaved
 * changes, and a drag onto the canvas, which brings a copy of the scenario
 * into this dataflow. While a card is dragged, the scrim lets the drag through
 * to the canvas beneath it, as in every drawer (useDrawerDragThrough).
 */
export const ScenarioCatalogDrawer: React.FC<ScenarioCatalogDrawerProps> = ({
  presented,
  onRequestClose,
  onExitComplete,
}) => {
  const drawerRef = useRef<HTMLElement>(null);
  const navigate = useNavigate();
  const { projectDirty, projectId } = useFlowContext();
  const { leave, dialog: leaveDialog } = useLeaveGuard(projectDirty, LEAVE_DATAFLOW, {
    layer: "overlay",
  });
  const {
    search,
    setSearch,
    sort,
    setSort,
    pinned,
    setPinned,
    catalog,
    items,
    handleScenarioDragStart,
    handleScenarioDragEnd,
    detailScenario,
    openScenarioDetails,
    closeScenarioDetails,
  } = useScenarioCatalogDrawer(presented);
  const dragThrough = useDrawerDragThrough();

  // Escape dismisses this drawer, as it does its peers: a modal on top (a
  // scenario's details, the leave question) owns Escape while it is open, and
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

  // The project already open just closes the drawer onto it.
  const openProject = (scenario: ScenarioRow) => {
    if (scenario.project.id === projectId) {
      onRequestClose();
      return;
    }
    leave(() => {
      onRequestClose();
      navigate(scenarioProjectPath(scenario.project.id));
    });
  };

  const searching = search.trim().length > 0;

  return (
    <>
      <div
        className={`${shell.overlayRoot} ${styles.overlayRoot} ${
          presented ? shell.overlayRootPresented : ""
        }`}
        data-curio-scenario-catalog-drawer="true"
        aria-hidden={!presented}
        {...dragThrough}
      >
        <button
          type="button"
          className={shell.scrim}
          aria-label="Close scenario catalog"
          onClick={() => {
            if (!pinned) onRequestClose();
          }}
        />
        <aside
          ref={drawerRef}
          className={shell.drawer}
          role="dialog"
          aria-modal="true"
          aria-labelledby="scenario-catalog-title"
          tabIndex={-1}
          onTransitionEnd={handleDrawerTransitionEnd}
        >
          <DrawerHeader
            pinned={pinned}
            onPinToggle={() => setPinned((v) => !v)}
            onClose={onRequestClose}
            kind="scenario"
            title="Scenario Catalog"
            titleId="scenario-catalog-title"
            subtitle="Saved selections of nodes from your projects. Drag one onto the canvas to copy it here."
            closeAriaLabel="Close Scenario Catalog drawer"
          />

          <PackageSearchRow
            search={search}
            sort={sort}
            onSearchChange={setSearch}
            onSortChange={setSort}
            placeholder="Search scenarios, projects…"
            sortAriaLabel="Sort scenarios"
            sortOptions={SCENARIO_SORT_OPTIONS}
          />

          <main className={shell.scrollBody}>
            {catalog.error ? (
              <div className={shell.error} role="alert">
                {catalog.error}
                <button type="button" className={styles.retry} onClick={catalog.reload}>
                  Retry
                </button>
              </div>
            ) : null}
            {catalog.loading && items.length === 0 ? (
              <div className={shell.empty} aria-busy="true">
                Loading scenarios…
              </div>
            ) : null}
            {!catalog.loading && !catalog.error && items.length === 0 ? (
              <div className={shell.empty}>
                {searching
                  ? "No scenarios match the current search."
                  : "No scenarios yet. Select nodes on a canvas and choose View > Save selection as scenario."}
              </div>
            ) : null}
            <div className={shell.cardList}>
              {items.map((scenario) => (
                <ScenarioCard
                  key={scenario.key}
                  scenario={scenario}
                  onOpenDetails={openScenarioDetails}
                  onOpenProject={openProject}
                  onDragStart={(event) => handleScenarioDragStart(scenario, event)}
                  onDragEnd={handleScenarioDragEnd}
                />
              ))}
            </div>
          </main>
        </aside>
      </div>

      {detailScenario ? (
        <ScenarioDetailModal
          key={detailScenario.key}
          projectId={detailScenario.project.id}
          scenarioId={detailScenario.id}
          fallbackScenario={detailScenario}
          unsavedChanges={projectDirty}
          onLeave={onRequestClose}
          onClose={closeScenarioDetails}
        />
      ) : null}

      {leaveDialog}
    </>
  );
};

export default ScenarioCatalogDrawer;
