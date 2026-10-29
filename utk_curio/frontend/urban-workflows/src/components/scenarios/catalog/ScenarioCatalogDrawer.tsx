import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { DrawerHeader } from "../../packages/publishing/DrawerHeader";
import { DrawerTabs } from "../../packages/publishing/DrawerTabs";
import { PackageSearchRow } from "../../packages/publishing/PackageSearchRow";
import shell from "../../packages/publishing/CatalogDrawerShell.module.css";
import { useDrawerDragThrough } from "../../packages/publishing/useDrawerDragThrough";
import { modalStackDepth } from "../../ModalShell";
import { LEAVE_DATAFLOW, useLeaveGuard } from "../../../hook/useLeaveGuard";
import { useFlowContext } from "../../../providers/FlowProvider";
import type { DrawerTab } from "../../../services/packages";
import { SCENARIO_SORT_OPTIONS } from "../../../services/scenarioCatalog";
import { liveScenarios } from "../../../utils/scenarios/scenarioParts";
import { InProjectScenarios } from "./InProjectScenarios";
import { ScenarioCard } from "./ScenarioCard";
import { ScenarioDetailModal } from "./ScenarioDetailModal";
import { ScenarioSetGroup } from "./ScenarioSetGroup";
import { rowHighlight, scenarioProjectPath } from "./scenarioFacts";
import { useScenarioCatalogDrawer } from "./useScenarioCatalogDrawer";
import styles from "./ScenarioCatalogDrawer.module.css";

export interface ScenarioCatalogDrawerProps {
  presented: boolean;
  onRequestClose: () => void;
  onExitComplete: () => void;
  /** The tab shown, held by the provider so a scenario command can open the
   *  drawer on In project. Without it the drawer holds its own, from Browse
   *  all. */
  tab?: DrawerTab;
  onTabChange?: (tab: DrawerTab) => void;
}

/**
 * The Scenario Catalog on the canvas, in two tabs as the other catalogs are.
 *
 * Browse all is every scenario saved in this account's projects, each a card
 * with its project's graph, inside a panel per scenario set headed by its name
 * and how many of the scenarios listed it holds, with the way to its project
 * (`ScenarioSetGroup`). The
 * groups keep the sort: each sits where its
 * first scenario would, with its scenarios in the sort's order
 * (`groupScenariosBySet`). A scenario lives in its project and is edited
 * there, so such a card changes nothing in it. It offers its details, the way
 * to its project, which asks first when this dataflow has unsaved changes, and
 * a drag onto the canvas, which brings a copy of the scenario into this
 * dataflow as a new scenario set. Checking cards of one set drags them
 * together; an unchecked card drags alone. While a card is dragged, the scrim lets the drag through to the
 * canvas beneath it, as in every drawer (useDrawerDragThrough).
 *
 * In project is this dataflow's scenarios, read off the canvas, with what can
 * be done to them (`InProjectScenarios`); its tab counts them.
 *
 * Built like the Model drawer (the same shell, header, search row and tabs,
 * the same card shape, Escape and pin rules).
 */
export const ScenarioCatalogDrawer: React.FC<ScenarioCatalogDrawerProps> = ({
  presented,
  onRequestClose,
  onExitComplete,
  tab: heldTab,
  onTabChange,
}) => {
  const drawerRef = useRef<HTMLElement>(null);
  const navigate = useNavigate();
  const { projectDirty, projectId, scenarios, nodes } = useFlowContext();
  const [ownTab, setOwnTab] = useState<DrawerTab>("browse");
  const tab = heldTab ?? ownTab;
  const setTab = onTabChange ?? setOwnTab;
  // This dataflow's scenarios, with members deleted since the last save left
  // out: the In project tab and its count.
  const inProject = useMemo(() => liveScenarios(scenarios ?? [], nodes ?? []), [scenarios, nodes]);
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
    groups,
    handleScenarioDragStart,
    handleScenarioDragEnd,
    isChecked,
    setRowsChecked,
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
  const openProject = (id: string) => {
    if (id === projectId) {
      onRequestClose();
      return;
    }
    leave(() => {
      onRequestClose();
      navigate(scenarioProjectPath(id));
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

          <DrawerTabs tab={tab} installedCount={inProject.length} onChange={setTab} />

          <main className={shell.scrollBody}>
            {tab === "installed" ? (
              <InProjectScenarios scenarios={inProject} search={search} sort={sort} presented={presented} />
            ) : (
              <>
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
                      : "No scenarios yet. On a canvas, choose View > Define scenario."}
                  </div>
                ) : null}
                {groups.map((group) => (
                  <ScenarioSetGroup
                    key={group.key}
                    name={group.set.name}
                    count={group.items.length}
                    isSet={Boolean(group.set.id)}
                    data={{ "data-scenario-group": group.project.id, "data-scenario-set": group.set.id }}
                    select={
                      group.set.id
                        ? {
                            checked: group.items.filter(isChecked).length,
                            onAll: (on) => setRowsChecked(group.items, on),
                          }
                        : undefined
                    }
                    action={
                      <button
                        type="button"
                        className={styles.openLink}
                        data-tooltip={`Open ${group.project.name}, where this set's scenarios are edited`}
                        onClick={() => openProject(group.project.id)}
                      >
                        Open source project
                      </button>
                    }
                  >
                    {group.items.map((scenario) => (
                      <ScenarioCard
                        key={scenario.key}
                        scenario={scenario}
                        highlight={rowHighlight(scenario)}
                        onOpenDetails={openScenarioDetails}
                        check={
                          group.set.id
                            ? { checked: isChecked(scenario), onChange: (on) => setRowsChecked([scenario], on) }
                            : undefined
                        }
                        onDragStart={(event) => handleScenarioDragStart(scenario, event)}
                        onDragEnd={handleScenarioDragEnd}
                      />
                    ))}
                  </ScenarioSetGroup>
                ))}
              </>
            )}
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
