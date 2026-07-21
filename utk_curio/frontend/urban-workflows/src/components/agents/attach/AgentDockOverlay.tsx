import React from "react";
import { AgentDock } from "./AgentDock";
import { AgentChatPanel } from "./AgentChatPanel";
import { useAgentAttachmentsContext } from "./AgentAttachmentsProvider";

/**
 * Canvas overlay for CANVAS-target agents: a persistent dock centered at the
 * bottom of the canvas. Node-target agents render at their node instead (see
 * {@link NodeAgentBadges}). The chat panel opens for whichever attachment is
 * selected — from a dock tile or a node badge.
 */
export const AgentDockOverlay: React.FC = () => {
  const ctx = useAgentAttachmentsContext();
  if (!ctx) return null;

  const canvasAttachments = ctx.attachments.filter((a) => a.target.kind === "canvas");
  const selected = ctx.attachments.find((a) => a.attachmentId === ctx.selectedId) ?? null;

  const onDetach = (attachmentId: string) => {
    if (ctx.selectedId === attachmentId) ctx.closeChat();
    ctx.detach(attachmentId);
  };

  return (
    <>
      <AgentDock
        attachments={canvasAttachments}
        selectedId={ctx.selectedId}
        onSelect={ctx.openChat}
        onDetach={onDetach}
      />
      {selected ? (
        <AgentChatPanel
          attachment={selected}
          onSend={(message) => ctx.run(selected.attachmentId, message)}
          onClose={ctx.closeChat}
        />
      ) : null}
    </>
  );
};
