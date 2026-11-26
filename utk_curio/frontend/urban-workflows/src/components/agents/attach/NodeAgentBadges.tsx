import React from "react";
import { useAgentAttachmentsContext } from "../../../providers/agents";
import { AgentAvatarBadge, waitsForYou } from "./AgentAvatarBadge";
import styles from "./NodeAgentBadges.module.css";

/**
 * Agent avatars for the agents attached to *this* node, rendered at the node's
 * bottom edge (per the concept). Each avatar opens the agent's chat; a hover ✕
 * detaches it. An agent that waits for you to pick the node's source, its
 * Dataset Finder or the Node Builder whose Solve asked for candidates, has the
 * waiting dot, and the group's name says how many wait. Renders nothing when
 * there is no attachments provider (e.g. a ReactFlow surface without one) or
 * no node-target agents for this node.
 */
export const NodeAgentBadges: React.FC<{ nodeId: string | undefined }> = ({ nodeId }) => {
  const ctx = useAgentAttachmentsContext();
  if (!ctx || !nodeId) return null;

  const attached = ctx.attachments.filter(
    (a) => a.target.kind === "node" && a.target.targetId === nodeId,
  );
  if (attached.length === 0) return null;
  const waiting = attached.filter(waitsForYou).length;

  return (
    <div
      className={styles.badges}
      role="group"
      aria-label={
        waiting ? `Attached agents, ${waiting === 1 ? "one waits" : `${waiting} wait`} for you` : "Attached agents"
      }
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
  );
};
