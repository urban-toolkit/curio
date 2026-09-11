import React from "react";
import { EdgeLabelRenderer } from "reactflow";
import { useAgentAttachmentsContext } from "./AgentAttachmentsProvider";
import { AgentAvatarBadge } from "./AgentAvatarBadge";
import { EDGE_AGENT_BADGES_ATTR } from "../../../utils/agentCatalogEvents";
import styles from "./EdgeAgentBadges.module.css";

/**
 * Agent avatars for the agents attached to *this* connection, rendered at the
 * edge's label point (#296).
 *
 * The twin of `NodeAgentBadges`, deliberately down to the shared
 * `AgentAvatarBadge`: a connection agent's chip, its "Open chat with <name>" /
 * "Detach <name>" names, its category tint and its detach-closes-first
 * behaviour are then the same object a node agent's are, on every surface.
 *
 * `EdgeLabelRenderer` portals into a div React Flow renders INSIDE the
 * viewport, between the edge layer and the node layer. Three consequences:
 * `labelX`/`labelY` are flow coordinates, so the chip rides pan and zoom for
 * free; the layer is `pointer-events: none`, so the chip has to opt back in
 * (and no wider box than the chips may do so, or it eats clicks meant for the
 * edge); and a badge whose midpoint falls under a node is painted behind it,
 * which is the right trade - the dock is still the roster.
 *
 * Renders nothing without a provider (a ReactFlow surface that has none, such
 * as the provenance graph) or with no connection-target agents on this edge.
 */
export const EdgeAgentBadges: React.FC<{
  edgeId: string | undefined;
  labelX: number;
  labelY: number;
}> = ({ edgeId, labelX, labelY }) => {
  const ctx = useAgentAttachmentsContext();
  if (!ctx || !edgeId) return null;

  const attached = ctx.attachments.filter(
    (a) => a.target.kind === "connection" && a.target.targetId === edgeId,
  );
  if (attached.length === 0) return null;

  return (
    <EdgeLabelRenderer>
      <div
        // nopan is React Flow's own noPanClassName, checked on pointerdown, so
        // pressing a badge cannot start a canvas pan; nodrag is the same
        // insurance for the node drag handler.
        className={`${styles.badges} nodrag nopan`}
        style={{
          transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
        }}
        role="group"
        aria-label="Attached agents"
        {...{ [EDGE_AGENT_BADGES_ATTR]: edgeId }}
      >
        {attached.map((a) => (
          <AgentAvatarBadge
            key={a.attachmentId}
            attachment={a}
            active={ctx.selectedId === a.attachmentId}
            onOpen={() => ctx.openChat(a.attachmentId)}
            onDetach={() => {
              if (ctx.selectedId === a.attachmentId) ctx.closeChat();
              ctx.detach(a.attachmentId);
            }}
          />
        ))}
      </div>
    </EdgeLabelRenderer>
  );
};
