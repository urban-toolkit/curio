import React from "react";
import { useAgentAttachmentsContext } from "./AgentAttachmentsProvider";
import { AgentAvatarBadge } from "./AgentAvatarBadge";
import styles from "./NodeAgentBadges.module.css";

/**
 * Agent avatars for the agents attached to *this* node, rendered at the node's
 * bottom edge (per the concept). Each avatar opens the agent's chat; a hover ✕
 * detaches it. Renders nothing when there is no attachments provider (e.g. a
 * ReactFlow surface without one) or no node-target agents for this node.
 */
export const NodeAgentBadges: React.FC<{ nodeId: string | undefined }> = ({ nodeId }) => {
  const ctx = useAgentAttachmentsContext();
  if (!ctx || !nodeId) return null;

  const attached = ctx.attachments.filter(
    (a) => a.target.kind === "node" && a.target.targetId === nodeId,
  );
  if (attached.length === 0) return null;

  return (
    <div className={styles.badges} role="group" aria-label="Attached agents">
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
  );
};
