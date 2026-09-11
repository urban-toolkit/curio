import React, { useCallback, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { useReactFlow, useStore } from "reactflow";
import { resolveNodeDisplayLabel } from "../../../utils/palettePackageFactoryDraft";
import { AgentDock } from "./AgentDock";
import { AgentChatPanel } from "./AgentChatPanel";
import type { AgentAttachment } from "../../../api/agentsApi";
import { useAgentAttachmentsContext } from "./AgentAttachmentsProvider";
import { composeAgentRunContext } from "./agentRunContext";
import { useAgentCanvasMutations } from "./useAgentCanvasMutations";
import { useFlowContext } from "../../../providers/FlowProvider";
import { useSlideDrawerPresentation } from "../../../hook/useSlideDrawerPresentation";

/**
 * Canvas overlay for CANVAS-target agents: a persistent dock centered at the
 * top of the canvas. Node-target agents render at their node instead (see
 * {@link NodeAgentBadges}). The chat panel opens for whichever attachment is
 * selected — from a dock tile or a node badge.
 */
export const AgentDockOverlay: React.FC = () => {
  const ctx = useAgentAttachmentsContext();
  const { projectId, workflowGoal, setWorkflowGoal, workflowNameRef } = useFlowContext();
  const { getNodes, getEdges } = useReactFlow();
  // The apply→canvas bridge listener (dev/48 §3.3): applied node creations
  // and content writes land on the LIVE canvas from here, where React Flow
  // is reachable.
  useAgentCanvasMutations();

  // The name of whatever the open chat is attached to, for its header (#228).
  // Computed here, above the `!ctx` return, because it uses hooks; keyed on the
  // node id alone so the selector identity is stable across renders. Reading it
  // through the store rather than getNodes() means renaming a node updates the
  // open chat's header live, without the overlay re-rendering on every unrelated
  // node change the way useNodes() would.
  const openTarget = ctx?.attachments.find(
    (a) => a.attachmentId === ctx?.selectedId,
  )?.target;
  const openNodeId =
    openTarget && openTarget.kind === "node" ? openTarget.targetId ?? null : null;
  const selectedTargetName = useStore(
    useCallback(
      (s: any) => {
        if (!openNodeId) return null;
        const node = s.nodeInternals.get(openNodeId);
        if (!node?.data) return null;
        try {
          return resolveNodeDisplayLabel(node.data);
        } catch {
          // An unregistered node type is not worth blanking the header over.
          return null;
        }
      },
      [openNodeId],
    ),
  );
  // The chat is a sliding right-hand surface like the three catalog drawers, so
  // it presents through the same machine (#295). Hooks run above the `!ctx`
  // return, which is why the selection is read defensively here.
  const {
    mounted: chatMounted,
    presented: chatPresented,
    open: openChatPanel,
    close: closeChatPanel,
    finishExit: finishChatExit,
  } = useSlideDrawerPresentation();

  const selectedId = ctx?.selectedId ?? null;
  const chatWasOpenRef = useRef(false);
  useEffect(() => {
    const isOpen = selectedId != null;
    // Only the transitions matter. Cycling from one agent to another keeps
    // `isOpen` true, so the panel never re-slides for a content swap - the
    // arrows change who is in the panel, not whether there is one.
    if (isOpen === chatWasOpenRef.current) return;
    chatWasOpenRef.current = isOpen;
    if (isOpen) openChatPanel();
    else closeChatPanel();
  }, [selectedId, openChatPanel, closeChatPanel]);

  // What the panel showed last, so the exit slide has something to render.
  // Index and total are pinned alongside it: detaching the open agent empties
  // the roster, and reading them live would repaint the header as "0 / 0" for
  // the length of the slide out.
  const lastShownRef = useRef<{
    attachment: AgentAttachment;
    index: number;
    total: number;
    targetName: string | null;
  } | null>(null);

  if (!ctx) return null;

  // Canvas agents plus connection agents.
  //
  // Connection agents are listed here AS WELL AS on their own edge
  // (`EdgeAgentBadges`, #296), and the duplication is deliberate. The badge is
  // the locator - it says which connection this agent is about - but it is only
  // reachable while that edge is on screen at a legible zoom, and it is painted
  // behind any node the edge happens to run under. The dock is the roster:
  // viewport-anchored, always reachable, and the one place that enumerates
  // every agent not pinned to a node, which is also the order the chat header's
  // "n of m" arrows cycle through. The two never disagree - same attachments,
  // same AgentAvatarBadge, same `selectedId` - so clicking either lights up
  // both.
  const canvasAttachments = ctx.attachments.filter(
    (a) => a.target.kind === "canvas" || a.target.kind === "connection",
  );
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

  if (selected) {
    lastShownRef.current = {
      attachment: selected,
      index: selectedIdx + 1,
      total: ctx.attachments.length,
      targetName: selectedTargetName,
    };
  }
  // During the exit the selection is already gone, so the panel renders what it
  // last showed rather than disappearing a frame before it finishes sliding.
  const shown = selected ?? lastShownRef.current?.attachment ?? null;
  const shownIndex = selected ? selectedIdx + 1 : lastShownRef.current?.index ?? 1;
  const shownTotal = selected ? ctx.attachments.length : lastShownRef.current?.total ?? 1;
  const shownTargetName = selected
    ? selectedTargetName
    : lastShownRef.current?.targetName ?? null;

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
        // Offered as soon as ANY agent is attached, not just a canvas one:
        // the agents that read the goal most (Node Content Builder,
        // Connection Builder) attach to nodes.
        showGoal={ctx.attachments.length > 0}
        goal={workflowGoal}
        onGoalChange={setWorkflowGoal}
      />
      {/* Portal to <body>: the chat is a full-height right drawer flush with
          the viewport top — its dark header sits at the top-bar level per the
          concept — instead of being clipped under the main top menu inside the
          canvas container. */}
      {chatMounted && shown
        ? createPortal(
            <AgentChatPanel
              attachment={shown}
              presented={chatPresented}
              onExitComplete={finishChatExit}
              targetName={shownTargetName}
              index={shownIndex}
              total={shownTotal}
              onPrev={prev ? () => ctx.openChat(prev.attachmentId) : undefined}
              onNext={next ? () => ctx.openChat(next.attachmentId) : undefined}
              turns={ctx.transcripts[shown.attachmentId] ?? []}
              loadingHistory={ctx.hydratingId === shown.attachmentId}
              historyError={ctx.hydrateErrors[shown.attachmentId] ?? null}
              onRetryHistory={() => ctx.hydrateSession(shown.attachmentId)}
              onSend={(message) =>
                // Grounded context (memo dev/44): composed from the LIVE
                // canvas on every send — unsaved nodes included, never stale.
                ctx.sendMessage(
                  shown.attachmentId,
                  message,
                  composeAgentRunContext(shown, {
                    nodes: getNodes(),
                    edges: getEdges(),
                    workflowName: workflowNameRef.current,
                    workflowGoal,
                  }),
                )
              }
              onClose={ctx.closeChat}
              toolActivity={ctx.toolActivity[shown.attachmentId] ?? []}
              runStatus={ctx.runStatus[shown.attachmentId] ?? null}
              onApplyProposal={(proposalId) =>
                ctx.applyProposal(shown.attachmentId, proposalId)
              }
              onApplyPlanNode={(proposalId, ref) =>
                ctx.applyPlanNode(shown.attachmentId, proposalId, ref)
              }
              onSavePlanGoal={(proposalId, ref, goal) =>
                ctx.savePlanGoal(shown.attachmentId, proposalId, ref, goal)
              }
              onApplyPlanEdges={async (proposalId, indices) => {
                await ctx.applyPlanEdges(shown.attachmentId, proposalId, indices);
              }}
              onSolvePlanNode={async (ref) => {
                await ctx.validateNode(shown.attachmentId, { ref });
              }}
              onRunPlanNode={async (ref) => {
                await ctx.runNode(shown.attachmentId, { ref });
              }}
              onSimulate={(mode) => ctx.runSimulation(shown.attachmentId, mode)}
              onCancelSimulate={() => ctx.cancelSimulation(shown.attachmentId)}
              simulationActivity={ctx.simulationActivity[shown.attachmentId]}
              onSolve={(nodeIds) => ctx.solveAttachment(shown.attachmentId, nodeIds)}
              solveProgress={ctx.solveProgress[shown.attachmentId]}
              solveErrors={ctx.solveErrors[shown.attachmentId]}
              onCancelSolve={() => ctx.cancelSolve(shown.attachmentId)}
              onDismissProposal={(proposalId) =>
                ctx.dismissProposal(shown.attachmentId, proposalId)
              }
              // dev/72: delegation entries and plan-row chips link to the
              // delegated agent's chat; existence-checked against the live
              // list so a detached home never renders a dead link.
              onOpenAgentChat={ctx.openChat}
              delegateExists={(id) =>
                ctx.attachments.some((a) => a.attachmentId === id)
              }
              onSaveIntent={(intent) => ctx.saveIntent(shown.attachmentId, intent)}
              onSaveTitle={(title) => ctx.saveTitle(shown.attachmentId, title)}
              onClearConversation={() => ctx.clearConversation(shown.attachmentId)}
            />,
            document.body,
          )
        : null}
    </>
  );
};
