import React, { memo, useCallback, useEffect, useRef, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronDown, faChevronUp, faRobot } from "@fortawesome/free-solid-svg-icons";
import { agentsApi, type AgentCard } from "../../../../api/agentsApi";
import { useFlowContext } from "../../../../providers/FlowProvider";
import { useAgentsCatalogDrawerControls } from "../../../../providers/AgentsCatalogDrawerProvider";
import { AGENTS_PALETTE_REFRESH_EVENT, AGENT_DRAG_MIME } from "../../../../utils/agentsPaletteEvents";
import styles from "./AgentsPalette.module.css";

/**
 * The AGENTS tools-panel palette. Lists the active project's installed agent
 * templates (action-free), refreshes when the catalog drawer changes the
 * lockfile, and opens the drawer via "Get more agents +". Rows are draggable;
 * the drag source writes the coordinate under ``application/curio-agent`` for
 * the attach drop handler (Feature 6).
 */
export const AgentsPaletteDropdown = memo(function AgentsPaletteDropdown() {
  const [open, setOpen] = useState(false);
  const [agents, setAgents] = useState<AgentCard[]>([]);
  const rootRef = useRef<HTMLDivElement>(null);
  const { projectId } = useFlowContext();
  const { openAgentsCatalogDrawer } = useAgentsCatalogDrawerControls();

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

  // Dismiss on outside click.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown, true);
    return () => document.removeEventListener("mousedown", onDown, true);
  }, [open]);

  const onDragStart = (e: React.DragEvent, coord: string) => {
    e.dataTransfer.setData(AGENT_DRAG_MIME, coord);
    e.dataTransfer.effectAllowed = "copy";
  };

  const openDrawer = () => {
    openAgentsCatalogDrawer();
    setOpen(false);
  };

  return (
    <div ref={rootRef} className={styles.root}>
      <button
        type="button"
        className={styles.trigger}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <FontAwesomeIcon icon={faRobot} />
        <span className={styles.triggerLabel}>AGENTS</span>
        {agents.length > 0 ? <span className={styles.badge}>{agents.length}</span> : null}
        <FontAwesomeIcon icon={open ? faChevronUp : faChevronDown} />
      </button>

      {open ? (
        <div className={styles.panel} role="menu" aria-label="Installed agents">
          <div className={styles.title}>AGENTS</div>
          {agents.length === 0 ? (
            <button type="button" className={styles.empty} onClick={openDrawer}>
              No agents installed — browse the catalog →
            </button>
          ) : (
            agents.map((a) => (
              <div
                key={a.dirName}
                className={styles.row}
                role="button"
                tabIndex={0}
                draggable
                onDragStart={(e) => onDragStart(e, a.dirName)}
                onClick={openDrawer}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") openDrawer();
                }}
                title={a.purpose || a.capabilities.join(" · ")}
              >
                <FontAwesomeIcon icon={faRobot} className={styles.rowIcon} />
                <span className={styles.rowName}>{a.name}</span>
                <span className={styles.rowMeta}>{a.category}</span>
              </div>
            ))
          )}
          <button
            type="button"
            className={styles.footer}
            aria-label="Get more agents — open the Agents Catalog drawer"
            onClick={openDrawer}
          >
            Get more agents +
          </button>
        </div>
      ) : null}
    </div>
  );
});
