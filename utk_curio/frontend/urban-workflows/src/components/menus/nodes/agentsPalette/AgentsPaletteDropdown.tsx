import React, { memo, useCallback, useEffect, useRef, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronDown, faChevronUp, faRobot } from "@fortawesome/free-solid-svg-icons";
import { agentsApi, type AgentCard } from "../../../../api/agentsApi";
import { useFlowContext } from "../../../../providers/FlowProvider";
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
  const rootRef = useRef<HTMLDivElement>(null);
  const { projectId } = useFlowContext();
  const { openAgentCatalogDrawer, isAgentCatalogDrawerOpen } =
    useAgentCatalogDrawerControls();

  const load = useCallback(async () => {
    if (!projectId) {
      setAgents([]);
      return;
    }
    try {
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

  // Escape closes — but let the catalog drawer own Escape while it is open so
  // the palette stays behind it (e.g. right after installing an agent).
  useEffect(() => {
    if (!open) return;
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape" && !isAgentCatalogDrawerOpen) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, isAgentCatalogDrawerOpen]);

  // No outside-click dismissal, deliberately: ToolsMenu owns a single
  // `activePalette`, so the Datasets/Packages palettes close only when their
  // own trigger is clicked again or the other trigger takes the strip. A
  // bespoke listener here would make this palette behave unlike the two it
  // sits beside.

  const total = agents.length;
  const openDrawer = useCallback(() => {
    openAgentCatalogDrawer();
  }, [openAgentCatalogDrawer]);

  return (
    <div
      id="agents-palette"
      className={styles.root}
      ref={rootRef}
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
          <FontAwesomeIcon icon={faRobot} className={styles.triggerIcon} />
          <span className={styles.triggerLabel}>Agent Catalog</span>
          <span className={styles.triggerCount}>{total}</span>
          <FontAwesomeIcon
            icon={open ? faChevronUp : faChevronDown}
            className={styles.triggerChevron}
          />
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
              title="Agents in dataflow"
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
            <p className={styles.hint}>
              Drag an agent onto a node or the canvas to attach it.
            </p>
          </div>
          <div className={styles.footer}>
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
