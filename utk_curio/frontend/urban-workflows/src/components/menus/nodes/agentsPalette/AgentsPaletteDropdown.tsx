import React, { memo, useCallback, useEffect, useRef, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronDown, faChevronUp, faRobot } from "@fortawesome/free-solid-svg-icons";
import { agentsApi, type AgentCard } from "../../../../api/agentsApi";
import { useFlowContext } from "../../../../providers/FlowProvider";
import { useAgentCatalogDrawerControls } from "../../../../providers/AgentCatalogDrawerProvider";
import { AGENT_CATALOG_REFRESH_EVENT } from "../../../../utils/agentCatalogEvents";
import { PaletteAccordion } from "../paletteAccordion";
import { TOOLS_PALETTE_DROPDOWN_ATTR } from "../toolsPaletteDismiss";
import { AgentPaletteRow } from "./AgentPaletteRow";
import styles from "./AgentsPalette.module.css";

/**
 * The AGENTS tools-panel palette. Shares the Datasets/Packages palette pattern
 * (dark vertical trigger card + dark dropdown panel + orange catalog footer),
 * differing only in content. Lists the active project's installed agent
 * templates as draggable rows (drag to attach — handled in MainCanvas),
 * refreshes when the catalog drawer changes the lockfile, and opens the drawer
 * via "Browse Agents Catalog +".
 */
export const AgentsPaletteDropdown = memo(function AgentsPaletteDropdown() {
  const [open, setOpen] = useState(false);
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
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-haspopup="true"
          title={open ? "Close agents palette" : "Open agents palette"}
        >
          <FontAwesomeIcon icon={faRobot} className={styles.triggerIcon} />
          <span className={styles.triggerLabel}>Agents</span>
          <span className={styles.triggerCount}>{total}</span>
          <FontAwesomeIcon
            icon={open ? faChevronUp : faChevronDown}
            className={styles.triggerChevron}
          />
        </button>
      </div>
      {open ? (
        <div className={styles.panel} role="region" aria-label="Agents palette">
          <div className={styles.panelHeader}>
            <div className={styles.title}>Agents</div>
          </div>
          <div className={styles.scroll}>
            <PaletteAccordion
              title="Installed in this project"
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
                  No agents installed in this project yet.
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
              Browse Agents Catalog +
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
});
