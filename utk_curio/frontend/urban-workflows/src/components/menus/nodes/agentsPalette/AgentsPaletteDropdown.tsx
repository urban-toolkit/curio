import React, { memo, useCallback, useEffect, useRef, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronDown, faChevronUp, faRobot } from "@fortawesome/free-solid-svg-icons";
import { agentsApi, type AgentCard } from "../../../../api/agentsApi";
import { useFlowContext } from "../../../../providers/FlowProvider";
import { useAgentsCatalogDrawerControls } from "../../../../providers/AgentsCatalogDrawerProvider";
import { AGENTS_PALETTE_REFRESH_EVENT } from "../../../../utils/agentsPaletteEvents";
import { PaletteAccordion } from "../paletteAccordion";
import {
  isToolsPaletteDismissOutsideClick,
  TOOLS_PALETTE_DROPDOWN_ATTR,
} from "../toolsPaletteDismiss";
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
  const { openAgentsCatalogDrawer, isAgentsCatalogDrawerOpen } =
    useAgentsCatalogDrawerControls();

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
    window.addEventListener(AGENTS_PALETTE_REFRESH_EVENT, onRefresh);
    return () => window.removeEventListener(AGENTS_PALETTE_REFRESH_EVENT, onRefresh);
  }, [load]);

  // Escape closes — but let the catalog drawer own Escape while it is open so
  // the palette stays behind it (e.g. right after installing an agent).
  useEffect(() => {
    if (!open) return;
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape" && !isAgentsCatalogDrawerOpen) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, isAgentsCatalogDrawerOpen]);

  // Dismiss on outside click, unless it lands in another tools-palette dropdown
  // or the catalog drawer is open (keep the palette visible on return).
  useEffect(() => {
    if (!open) return;
    const onDown = (ev: MouseEvent) => {
      if (isAgentsCatalogDrawerOpen) return;
      if (rootRef.current?.contains(ev.target as Node)) return;
      if (!isToolsPaletteDismissOutsideClick(ev.target)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDown, true);
    return () => document.removeEventListener("mousedown", onDown, true);
  }, [open, isAgentsCatalogDrawerOpen]);

  const total = agents.length;
  const openDrawer = useCallback(() => {
    openAgentsCatalogDrawer();
  }, [openAgentsCatalogDrawer]);

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
