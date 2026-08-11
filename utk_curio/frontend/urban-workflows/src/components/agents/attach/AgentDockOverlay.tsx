import React, { useState } from "react";
import { createPortal } from "react-dom";
import { useReactFlow } from "reactflow";
import { AgentDock } from "./AgentDock";
import { AgentChatPanel } from "./AgentChatPanel";
import { useAgentAttachmentsContext } from "./AgentAttachmentsProvider";
import { AgentSettingsModal } from "../settings/AgentSettingsModal";
import { composeAgentRunContext } from "./agentRunContext";
import { useAgentCanvasMutations } from "./useAgentCanvasMutations";
import { useFlowContext } from "../../../providers/FlowProvider";

/**
 * Canvas overlay for CANVAS-target agents: a persistent dock centered at the
 * bottom of the canvas. Node-target agents render at their node instead (see
 * {@link NodeAgentBadges}). The chat panel opens for whichever attachment is
 * selected — from a dock tile or a node badge.
 */
export const AgentDockOverlay: React.FC = () => {
  const ctx = useAgentAttachmentsContext();
  const { projectId, workflowGoal, workflowNameRef } = useFlowContext();
  const { getNodes, getEdges } = useReactFlow();
  // The apply→canvas bridge listener (dev/48 §3.3): applied node creations
  // and content writes land on the LIVE canvas from here, where React Flow
  // is reachable.
  useAgentCanvasMutations();
  // Attachment id whose settings modal is open (memo dev/42), or null.
  const [settingsFor, setSettingsFor] = useState<string | null>(null);
  if (!ctx) return null;

  const canvasAttachments = ctx.attachments.filter((a) => a.target.kind === "canvas");
  const selected = ctx.attachments.find((a) => a.attachmentId === ctx.selectedId) ?? null;
  // DEC-042: the chat header's ‹ › arrows cycle through ALL attached agents in
  // the dataflow (node + canvas targets), in list order, without wrapping.
  const selectedIdx = selected
    ? ctx.attachments.findIndex((a) => a.attachmentId === selected.attachmentId)
    : -1;
  const prev = selectedIdx > 0 ? ctx.attachments[selectedIdx - 1] : null;
  const next =
    selectedIdx >= 0 && selectedIdx < ctx.attachments.length - 1
      ? ctx.attachments[selectedIdx + 1]
      : null;

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
      {/* Portal to <body>: the chat is a full-height right drawer flush with
          the viewport top — its dark header sits at the top-bar level per the
          concept — instead of being clipped under the main top menu inside the
          canvas container. */}
      {selected
        ? createPortal(
            <AgentChatPanel
              attachment={selected}
              index={selectedIdx + 1}
              total={ctx.attachments.length}
              onPrev={prev ? () => ctx.openChat(prev.attachmentId) : undefined}
              onNext={next ? () => ctx.openChat(next.attachmentId) : undefined}
              turns={ctx.transcripts[selected.attachmentId] ?? []}
              loadingHistory={ctx.hydratingId === selected.attachmentId}
              historyError={ctx.hydrateErrors[selected.attachmentId] ?? null}
              onRetryHistory={() => ctx.hydrateSession(selected.attachmentId)}
              onSend={(message) =>
                // Grounded context (memo dev/44): composed from the LIVE
                // canvas on every send — unsaved nodes included, never stale.
                ctx.sendMessage(
                  selected.attachmentId,
                  message,
                  composeAgentRunContext(selected, {
                    nodes: getNodes(),
                    edges: getEdges(),
                    workflowName: workflowNameRef.current,
                    workflowGoal,
                  }),
                )
              }
              onClose={ctx.closeChat}
              onOpenSettings={
                projectId ? () => setSettingsFor(selected.attachmentId) : undefined
              }
              toolActivity={ctx.toolActivity[selected.attachmentId] ?? []}
              onApplyProposal={(proposalId) =>
                ctx.applyProposal(selected.attachmentId, proposalId)
              }
              onApplyPlanNode={(proposalId, ref) =>
                ctx.applyPlanNode(selected.attachmentId, proposalId, ref)
              }
              onSavePlanGoal={(proposalId, ref, goal) =>
                ctx.savePlanGoal(selected.attachmentId, proposalId, ref, goal)
              }
              onApplyPlanEdges={async (proposalId, indices) => {
                await ctx.applyPlanEdges(selected.attachmentId, proposalId, indices);
              }}
              onSimulate={(mode) => ctx.runSimulation(selected.attachmentId, mode)}
              onCancelSimulate={() => ctx.cancelSimulation(selected.attachmentId)}
              simulationActivity={ctx.simulationActivity[selected.attachmentId]}
              onSolve={(nodeIds) => ctx.solveAttachment(selected.attachmentId, nodeIds)}
              solveProgress={ctx.solveProgress[selected.attachmentId]}
              onCancelSolve={() => ctx.cancelSolve(selected.attachmentId)}
              onDismissProposal={(proposalId) =>
                ctx.dismissProposal(selected.attachmentId, proposalId)
              }
              onSaveIntent={(intent) => ctx.saveIntent(selected.attachmentId, intent)}
              onSaveTitle={(title) => ctx.saveTitle(selected.attachmentId, title)}
              onClearConversation={() => ctx.clearConversation(selected.attachmentId)}
            />,
            document.body,
          )
        : null}
      {settingsFor && projectId
        ? createPortal(
            <AgentSettingsModal
              scope="attachment"
              projectId={projectId}
              attachmentId={settingsFor}
              onClose={() => setSettingsFor(null)}
            />,
            document.body,
          )
        : null}
    </>
  );
};
