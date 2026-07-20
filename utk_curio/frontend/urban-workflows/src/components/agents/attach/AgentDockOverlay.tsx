import React, { useState } from "react";
import { useFlowContext } from "../../../providers/FlowProvider";
import { AgentDock } from "./AgentDock";
import { AgentChatPanel } from "./AgentChatPanel";
import { useAgentAttachments } from "./useAgentAttachments";

/**
 * Canvas overlay that wires the attachments hook to the dock + chat: shows a
 * dock tile per attached agent, and opens a chat panel for the selected one.
 * Mounted once on the canvas.
 */
export const AgentDockOverlay: React.FC = () => {
  const { projectId } = useFlowContext();
  const { attachments, detach, run } = useAgentAttachments(projectId ?? null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const selected = attachments.find((a) => a.attachmentId === selectedId) ?? null;

  const onDetach = (attachmentId: string) => {
    if (selectedId === attachmentId) setSelectedId(null);
    detach(attachmentId);
  };

  return (
    <>
      <AgentDock
        attachments={attachments}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onDetach={onDetach}
      />
      {selected ? (
        <AgentChatPanel
          attachment={selected}
          onSend={(message) => run(selected.attachmentId, message)}
          onClose={() => setSelectedId(null)}
        />
      ) : null}
    </>
  );
};
