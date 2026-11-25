import React, { useCallback, useEffect, useMemo, useRef } from "react";
import { createPortal } from "react-dom";
import { useReactFlow, useStore } from "reactflow";
import { downloadLines } from "../../../utils/downloadLine";
import { resolveNodeDisplayLabel } from "../../../utils/palettePackageFactoryDraft";
import { AgentDock } from "./AgentDock";
import { AgentChatPanel } from "./AgentChatPanel";
import { workingText } from "./AgentAvatarBadge";
import { personText } from "./PeopleHere";
import { connectionName } from "./chat/chatPanelDerived";
import type { AgentAttachment } from "../../../services/agents";
import { useAgentAttachmentsContext } from "../../../providers/agents";
import { usePeopleHere } from "../../../providers/collab/usePeopleHere";
import { composeAgentRunContext, skillsApi } from "../../../services/agents";
import { BUILD_RUNNING_HINT, buildRunningOver } from "../../../services/agents/planBuild";
import { useAgentCanvasMutations } from "./useAgentCanvasMutations";
import { useFlowContext } from "../../../providers/FlowProvider";
import { useUserContext } from "../../../providers/userContext";
import { useSlideDrawerPresentation } from "../../../hook/useSlideDrawerPresentation";

const NO_ATTACHMENTS: AgentAttachment[] = [];

/** The name a node's header shows, from the store's node; null when it is not
 *  on the canvas. */
function nodeNameIn(state: any, nodeId: string): string | null {
  const node = state.nodeInternals?.get(nodeId);
  if (!node?.data) return null;
  try {
    return resolveNodeDisplayLabel(node.data) || null;
  } catch {
    // An unregistered node type is not worth blanking a name over.
    return null;
  }
}

/**
 * What each node and connection agent is attached to, as the canvas names it:
 * a node by the name its header shows, a connection by the two nodes it joins
 * ("from A to B"). Read off React Flow's store as one string, so renaming a
 * node renames it in the open chat at once, and a change that renames nothing
 * (a drag) draws nothing again (#228).
 */
function useTargetNames(attachments: AgentAttachment[]): Record<string, string> {
  const wanted = JSON.stringify(
    attachments
      .filter((a) => a.target.kind !== "canvas" && a.target.targetId)
      .map((a) => [a.attachmentId, a.target.kind, a.target.targetId]),
  );
  const named = useStore(
    useCallback(
      (state: any) => {
        const names: Record<string, string> = {};
        for (const [attachmentId, kind, targetId] of JSON.parse(wanted) as string[][]) {
          if (kind === "node") {
            const name = nodeNameIn(state, targetId);
            if (name) names[attachmentId] = name;
          } else if (kind === "connection") {
            const edge = (state.edges ?? []).find((e: { id: string }) => e.id === targetId);
            const from = edge ? nodeNameIn(state, edge.source) : null;
            const to = edge ? nodeNameIn(state, edge.target) : null;
            if (from && to) names[attachmentId] = connectionName(from, to);
          }
        }
        return JSON.stringify(names);
      },
      [wanted],
    ),
  );
  return useMemo(() => JSON.parse(named) as Record<string, string>, [named]);
}

/**
 * Canvas overlay for CANVAS-target agents: a persistent dock centered at the
 * top of the canvas. Node-target agents render at their node instead (see
 * {@link NodeAgentBadges}). The chat panel opens for whichever attachment is
 * selected — from a dock tile or a node badge.
 */
export const AgentDockOverlay: React.FC = () => {
  const ctx = useAgentAttachmentsContext();
  // dev/129 (porting dev/111): `outputs` rides along so nodeContext's
  // current_output can name the artifact a node produced.
  const { workflowGoal, setWorkflowGoal, workflowNameRef, outputs, scenarios } = useFlowContext();
  // The dataflow these agents work on: on an invited editor's canvas, the one
  // its link opened, which the flow state does not name.
  const dataflowId = ctx?.dataflowId ?? null;
  // Whose messages the chat names the writer of: everyone's but this account's.
  const { user } = useUserContext();
  const viewerAccount = user?.id != null ? String(user.id) : null;
  const { getNodes, getEdges } = useReactFlow();
  // The apply→canvas bridge listener (dev/48 §3.3): applied node creations
  // and content writes land on the LIVE canvas from here, where React Flow
  // is reachable.
  useAgentCanvasMutations();

  // What each agent is attached to, for the open chat's header and its rail
  // (#228). Computed here, above the `!ctx` return, because it uses hooks.
  const targetNames = useTargetNames(ctx?.attachments ?? NO_ATTACHMENTS);
  // Who is at work in the dataflow's room, for the rail's running dots, as
  // their chips in the dock say it.
  const here = usePeopleHere();
  const atWork = useMemo(() => {
    const doing = new Map<string, string>();
    for (const person of here.people) {
      const attachmentId = person.agent?.attachmentId;
      if (attachmentId && !doing.has(attachmentId)) doing.set(attachmentId, personText(person, null));
    }
    return doing;
  }, [here.people]);
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
    // Only the transitions matter. Moving from one agent to another keeps
    // `isOpen` true, so the panel never re-slides for a content swap - the
    // rail changes who is in the panel, not whether there is one.
    if (isOpen === chatWasOpenRef.current) return;
    chatWasOpenRef.current = isOpen;
    if (isOpen) openChatPanel();
    else closeChatPanel();
  }, [selectedId, openChatPanel, closeChatPanel]);

  // What the panel showed last, so the exit slide has something to render.
  // The rail's agents and their targets' names are pinned alongside it:
  // detaching the open agent empties the roster, and reading them live would
  // empty the rail for the length of the slide out.
  const lastShownRef = useRef<{
    attachment: AgentAttachment;
    attachments: AgentAttachment[];
    targetNames: Record<string, string>;
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
  // every agent not pinned to a node. The chat's rail lists every agent on the
  // dataflow, node agents too, in the same order. The two never disagree -
  // same attachments, same `selectedId` - so clicking either lights up both.
  const canvasAttachments = ctx.attachments.filter(
    (a) => a.target.kind === "canvas" || a.target.kind === "connection",
  );
  const selected = ctx.attachments.find((a) => a.attachmentId === ctx.selectedId) ?? null;

  if (selected) {
    lastShownRef.current = { attachment: selected, attachments: ctx.attachments, targetNames };
  }
  // During the exit the selection is already gone, so the panel renders what it
  // last showed rather than disappearing a frame before it finishes sliding.
  const shown = selected ?? lastShownRef.current?.attachment ?? null;
  const shownAttachments = selected ? ctx.attachments : lastShownRef.current?.attachments ?? NO_ATTACHMENTS;
  const shownNames = selected ? targetNames : lastShownRef.current?.targetNames ?? {};

  const onDetach = (attachmentId: string) => {
    if (ctx.selectedId === attachmentId) ctx.closeChat();
    ctx.detach(attachmentId);
  };

  return (
    <>
      {/* "Add key for <host>" from a card opens API Settings through the
          top bar's ApiSettingsRequestHost (GlobalPageHeader): one host per
          page, or one request would be answered twice. */}
      <AgentDock
        attachments={canvasAttachments}
        selectedId={ctx.selectedId}
        onSelect={ctx.openChat}
        onDetach={onDetach}
      />
      {/* Portal to <body>: the chat is a right drawer under the top bar,
          placed against the window rather than clipped inside the canvas
          container. */}
      {chatMounted && shown
        ? createPortal(
            <AgentChatPanel
              attachment={shown}
              presented={chatPresented}
              onExitComplete={finishChatExit}
              targetName={shownNames[shown.attachmentId] ?? null}
              // The rail: every agent on the dataflow, what each is attached
              // to, and who is at work, in the room or in the background.
              attachments={shownAttachments}
              targetNameOf={(a) => shownNames[a.attachmentId] ?? null}
              workingOf={(a) => workingText(a, atWork.get(a.attachmentId) ?? null)}
              turns={ctx.transcripts[shown.attachmentId] ?? []}
              viewerAccount={viewerAccount}
              installsWaitForOwner={ctx.installsWaitForOwner}
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
                    outputs,
                    scenarios,
                  }),
                )
              }
              onClose={ctx.closeChat}
              toolActivity={ctx.toolActivity[shown.attachmentId] ?? []}
              runStatus={ctx.runStatus[shown.attachmentId] ?? null}
              waitingAsks={ctx.waitingAsks[shown.attachmentId] ?? []}
              onStopTurn={() => ctx.stopTurn(shown.attachmentId)}
              onWithdrawAsk={(askId) => ctx.withdrawAsk(shown.attachmentId, askId)}
              onApplyProposal={(proposalId) =>
                ctx.applyProposal(shown.attachmentId, proposalId)
              }
              onUndoChange={(changeId) => ctx.undoChange(shown.attachmentId, changeId)}
              // A plan row's Solve and Run: how far a download on first use
              // of what the node reads has come reaches the row's own line,
              // as a node's Solve narrates it.
              onSolvePlanNode={async (ref, onLine) => {
                await ctx.validateNode(shown.attachmentId, { ref }, downloadLines(onLine));
              }}
              onRunPlanNode={async (ref, onLine) => {
                await ctx.runNode(shown.attachmentId, { ref }, downloadLines(onLine));
              }}
              onSimulate={(mode) => ctx.runSimulation(shown.attachmentId, mode)}
              onCancelSimulate={() => ctx.cancelSimulation(shown.attachmentId)}
              simulationActivity={ctx.simulationActivity[shown.attachmentId]}
              simulating={ctx.simulating[shown.attachmentId] ?? null}
              onSolve={(nodeIds) => ctx.solveAttachment(shown.attachmentId, nodeIds)}
              solveProgress={ctx.solveProgress[shown.attachmentId]}
              solveErrors={ctx.solveErrors[shown.attachmentId]}
              solveRemedies={ctx.solveRemedies[shown.attachmentId]}
              solveWaiting={ctx.solveWaiting[shown.attachmentId]}
              solveEndedBy={ctx.solveEndedBy[shown.attachmentId] ?? null}
              solvePass={ctx.solvePass[shown.attachmentId] ?? null}
              onSolveOneNode={(nodeId) => ctx.solveNode(shown.attachmentId, nodeId)}
              solveWave={ctx.solveWave[shown.attachmentId]}
              solveNotices={ctx.solveNotices[shown.attachmentId]}
              onCancelSolve={() => ctx.cancelSolve(shown.attachmentId)}
              // dev/115 (Amendment A2): the per-node Solve from the node's own agent.
              onSolveNode={
                shown.target.kind === "node" && shown.target.targetId
                  ? () => ctx.solveNode(shown.attachmentId, shown.target.targetId as string)
                  : undefined
              }
              solveNodeActivity={ctx.solveNodeActivity[shown.attachmentId] ?? null}
              // No Solve of a node starts while a build runs on its plan.
              solveNodeBlocker={
                shown.target.kind === "node" &&
                shown.target.targetId &&
                buildRunningOver(shown.target.targetId, ctx.attachments, ctx.simulating)
                  ? BUILD_RUNNING_HINT
                  : null
              }
              onDismissProposal={(proposalId) =>
                ctx.dismissProposal(shown.attachmentId, proposalId)
              }
              // dev/72: delegation entries and plan-row chips link to the
              // delegated agent's chat; existence-checked against the live
              // list so a detached home never renders a dead link.
              onOpenAgentChat={ctx.openChat}
              onRecordDatasetSelection={(picks) =>
                ctx.recordDatasetSelection(shown.attachmentId, picks)
              }
              // A node's candidates in the chat that asked for them: the pick
              // records on the node's Dataset Finder.
              onRecordSourcePick={(finderAttachmentId, picks) =>
                ctx.recordDatasetSelection(finderAttachmentId, picks)
              }
              // dev/132: the portal-download row's Import button.
              onImportDataset={ctx.importDataset}
              delegateExists={(id) =>
                ctx.attachments.some((a) => a.attachmentId === id)
              }
              // A label that opens another agent's chat names that agent as
              // the live list does, by its manifest's name.
              agentNameOf={(id) =>
                ctx.attachments.find((a) => a.attachmentId === id)?.name ?? null
              }
              onSaveIntent={(intent) => ctx.saveIntent(shown.attachmentId, intent)}
              onSaveTitle={(title) => ctx.saveTitle(shown.attachmentId, title)}
              // The dataflow's goal, on the line under the header of every
              // agent's chat, node and connection agents' included.
              goal={workflowGoal}
              onSaveGoal={setWorkflowGoal}
              onClearConversation={() => ctx.clearConversation(shown.attachmentId)}
              // What `/` offers: the skills this chat's next run lists.
              loadSkills={
                dataflowId
                  ? async () => (await skillsApi.runSkills(dataflowId, shown.attachmentId)).skills
                  : undefined
              }
            />,
            document.body,
          )
        : null}
    </>
  );
};
