import React, { memo, useCallback, useEffect, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronLeft, faChevronRight, faRobot } from "@fortawesome/free-solid-svg-icons";
import { agentsApi, type AgentCard } from "../../../../api/agentsApi";
import { useFlowContext } from "../../../../providers/FlowProvider";
import { PaletteDragHint } from "../PaletteDragHint";
import { useAgentCatalogDrawerControls } from "../../../../providers/AgentCatalogDrawerProvider";
import { AGENT_CATALOG_REFRESH_EVENT } from "../../../../utils/agentCatalogEvents";
import { PaletteAccordion } from "../paletteAccordion";
import { TOOLS_PALETTE_DROPDOWN_ATTR, TOOLS_PALETTE_PANEL_ATTR } from "../toolsPaletteDismiss";
import { AgentPaletteRow } from "./AgentPaletteRow";
import styles from "./AgentsPalette.module.css";

/**
 * The Agent Catalog tools-panel palette. Shares the Datasets/Packages pattern
 * (dark vertical trigger card + dark dropdown panel + orange catalog footer),
 * differing only in content. Lists the active project's installed agent
 * templates as draggable rows (drag to attach — handled in MainCanvas),
 * refreshes when the catalog drawer changes the lockfile, and opens the drawer
 * via "Browse Agent Catalog +".
 */
export const AgentsPaletteDropdown = memo(function AgentsPaletteDropdown({
  open,
  setOpen,
}: {
  /** Owned by ToolsMenu: the three palettes share one strip, so only one
   *  may be open. Uncontrolled state here would let two open at once. */
  open: boolean;
  setOpen: (value: boolean) => void;
}) {
  const [agents, setAgents] = useState<AgentCard[]>([]);
  const { projectId } = useFlowContext();
  const { openAgentCatalogDrawer } = useAgentCatalogDrawerControls();

  const load = useCallback(async () => {
    try {
      if (!projectId) {
        // A dataflow you have just created has no project yet - it is created
        // on the first save - so there is no lockfile to read and this showed
        // an EMPTY palette. The account's "in all projects" agents belong here:
        // they are in every project, and `save_project` seeds them into this one
        // the moment it exists, so listing them now is not a promise, it is a
        // preview of a state one save away.
        const r = await agentsApi.listImports();
        setAgents(r.agents);
        return;
      }
      const r = await agentsApi.listProjectAgents(projectId);
      setAgents(r.agents);
    } catch {
      setAgents([]);
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const onRefresh = () => load();
    window.addEventListener(AGENT_CATALOG_REFRESH_EVENT, onRefresh);
    return () => window.removeEventListener(AGENT_CATALOG_REFRESH_EVENT, onRefresh);
  }, [load]);

  // No Escape / outside-click dismissal on purpose: the palette stays open until
  // its own trigger is clicked again (or another palette claims the strip), so
  // browsing the canvas or the Agent Catalog never collapses it. Both peers say
  // the same thing in the same words (DatasetsPaletteDropdown.tsx,
  // PackagesPaletteDropdown.tsx).
  //
  // There used to be an Escape listener here, directly above a comment claiming
  // this palette deliberately behaved like the other two - true of outside-click,
  // false of Escape.

  const total = agents.length;
  const openDrawer = useCallback(() => {
    openAgentCatalogDrawer();
  }, [openAgentCatalogDrawer]);

  return (
    <div
      id="agents-palette"
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
          title={open ? "Close agent palette" : "Open agent palette"}
        >
          <span className={styles.triggerTop}>
            <FontAwesomeIcon icon={faRobot} className={styles.triggerIcon} />
            <span className={styles.triggerCount}>{total}</span>
            <FontAwesomeIcon
              icon={open ? faChevronLeft : faChevronRight}
              className={styles.triggerChevron}
            />
          </span>
          <span className={styles.triggerLabel}>Agent Catalog</span>
        </button>
      </div>
      {open ? (
        /* TOOLS_PALETTE_PANEL_ATTR marks this panel as occluding the canvas,
           exactly as the Datasets and Packages panels do. fitViewWithMenuOffset
           measures the dock's reach by taking the rightmost edge across the rail
           and any element carrying it, because an open panel is absolutely
           positioned and so is not inside the dock's own rect. Without it Fit
           View sized the graph against the full pane and parked part of it under
           this palette - the one way this palette did not behave like the two it
           sits beside. */
        <div
          className={styles.panel}
          role="region"
          aria-label="Agent palette"
          {...{ [TOOLS_PALETTE_PANEL_ATTR]: "true" }}
        >
          <div className={styles.panelHeader}>
            <div className={styles.title}>Agents</div>
          </div>
          <div className={styles.scroll}>
            <PaletteAccordion
              title="Agents in project"
              count={total}
              selected
              defaultOpen
            >
              {total > 0 ? (
                agents.map((a) => (
                  <AgentPaletteRow key={a.dirName} agent={a} onOpen={openDrawer} />
                ))
              ) : (
                <div className={styles.sectionEmpty}>
                  No agents added yet.
                </div>
              )}
            </PaletteAccordion>
          </div>
          <div className={styles.footer}>
            {/* Was inline here, and only here. Shared now, so the three
                palettes cannot say it three different ways - or, as the Data
                and Node ones did, not at all. */}
            <PaletteDragHint item="agent" attachesToNode />
            <button
              type="button"
              className={styles.catalogButton}
              onClick={openDrawer}
            >
              Browse Agent Catalog +
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
});
