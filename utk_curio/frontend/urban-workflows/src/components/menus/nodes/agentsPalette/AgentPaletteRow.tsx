import React, { memo, useCallback } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faRobot } from "@fortawesome/free-solid-svg-icons";
import type { AgentCard } from "../../../../api/agentsApi";
import { AGENT_DRAG_MIME } from "../../../../utils/agentsPaletteEvents";
import { agentCategoryKey } from "./agentCategoryStyle";
import packageStyles from "../toolsMenuPackagePalette/ToolsMenuPackagePalette.module.css";
import rowStyles from "./AgentPaletteRow.module.css";

/** Shorten the install coordinate for display: ``agent.foo@1`` (major only). */
function shortCoord(agent: AgentCard): string {
  const major = (agent.version || "").split(".")[0] || agent.version;
  return `${agent.id}@${major}`;
}

/** Human label for a compatible-target kind. */
const HOOK_LABEL: Record<string, string> = {
  canvas: "Canvas",
  node: "Node",
  connection: "Connection",
};

/**
 * One installed-agent row in the AGENTS palette. Mirrors the Datasets/Packages
 * row structure (reusing the shared ``packageKind*`` classes): a draggable,
 * category-tinted avatar (the drag source writing ``AGENT_DRAG_MIME`` so the
 * canvas drop handler can attach it) plus a meta button showing the name, the
 * install coordinate, and a category-colored chip. Clicking the meta opens the
 * catalog drawer; dragging attaches (handled in ``MainCanvas``).
 */
export const AgentPaletteRow = memo(function AgentPaletteRow({
  agent,
  onOpen,
}: {
  agent: AgentCard;
  onOpen?: () => void;
}) {
  const key = agentCategoryKey(agent.category);
  const avatarClass =
    rowStyles[`avatar_${key}` as keyof typeof rowStyles] ?? rowStyles.avatar_default;
  const tooltip = agent.purpose || agent.capabilities.join(" · ");
  // Show one pill per compatible target kind (Canvas / Node / Connection) so a
  // dual-compatible agent clearly advertises both. Deduped, order preserved.
  const hooks = Array.from(new Set(agent.hooks));

  const onDragStart = useCallback(
    (event: React.DragEvent) => {
      event.dataTransfer.setData(AGENT_DRAG_MIME, agent.dirName);
      event.dataTransfer.effectAllowed = "copy";
    },
    [agent.dirName],
  );

  return (
    <div className={packageStyles.packageKindRow}>
      <div
        className={`${packageStyles.packageKindRowDrag} ${avatarClass}`}
        draggable
        onDragStart={onDragStart}
        title="Drag onto a node or the canvas to attach"
      >
        <FontAwesomeIcon icon={faRobot} className={rowStyles.avatarIcon} />
      </div>
      <button
        type="button"
        className={packageStyles.packageKindRowMeta}
        onClick={onOpen}
        title={tooltip}
      >
        <span className={packageStyles.packageKindRowLabel}>{agent.name}</span>
        <span className={rowStyles.coord}>{shortCoord(agent)}</span>
        <span className={rowStyles.pills}>
          {hooks.map((h) => {
            const chipClass =
              rowStyles[`chip_${agentCategoryKey(h)}` as keyof typeof rowStyles] ??
              rowStyles.chip_default;
            return (
              <span
                key={h}
                className={`${packageStyles.packageKindCategoryChip} ${chipClass}`}
              >
                {HOOK_LABEL[h] ?? h}
              </span>
            );
          })}
        </span>
      </button>
    </div>
  );
});
