import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faRobot } from "@fortawesome/free-solid-svg-icons";

import {
  askersOf,
  DATASET_SELECT_CAPABILITY,
  declaresCapability,
  installsIntoAccount,
  NODE_BUILD_CAPABILITY,
  SKILL_USE_WORDS,
  skillsUsedBy,
  type AgentAttachment,
  type AgentCardPart,
  type AgentChangePart,
  type AgentDatasetCandidatesPart,
  type AgentDatasetPick,
  type AgentDatasetSelection,
  type AgentDelegationPart,
  type AgentProposalPart,
  type AgentSessionTurn,
  type AgentSolveAttemptsPart,
  type AgentSourcePickPart,
  type RunStatusDisplay,
} from "../../../../services/agents";
import { AgentChangeCard } from "../../content/AgentChangeCard";
import { AgentChatCard } from "../../content/AgentChatCard";
import { AgentDatasetCandidatesCard } from "../../content/AgentDatasetCandidatesCard";
import { AgentSolveAttemptsCard } from "../../content/AgentSolveAttemptsCard";
import { AgentDelegationEntry } from "../../content/AgentDelegationEntry";
import { AgentReviewCard } from "../../content/AgentReviewCard";
import { SafeAgentContent } from "../../content/SafeAgentContent";
import { AgentRunStatusLine } from "../AgentRunStatusLine";
import { LlmConfigAction } from "../../../llmConfigs/LlmConfigAction";
import styles from "../AgentChatPanel.module.css";
import type { NodeChat } from "../../content/reviewCard/PlanNodesList";
import { failedCallWords, lastingToolFailures, planNodeStateFor, toolsCalledBy, type PlanLive } from "./chatPanelDerived";

/** The callbacks a turn's cards may need: an install's review, a change's
 * Undo, a landed plan's rows. */
export interface AgentTurnActions {
  onComposePrompt: (prompt: string) => void;
  /** A link the agent wrote to another Curio page: the owner decides whether leaving the dataflow needs a confirmation first. */
  onInternalLink?: (to: string) => void;
  onOpenAgentChat?: (attachmentId: string) => void;
  delegateExists?: (attachmentId: string) => boolean;
  /** The name of the agent another attachment binds, from the live list. */
  agentNameOf?: (attachmentId: string) => string | null;
  /** Record a pick on a card in this node Finder's chat, naming the card it
   * was made on (*discoveryId*) when the card has an id. */
  onRecordDatasetSelection?: (picks: AgentDatasetPick[], discoveryId?: string) => Promise<AgentDatasetSelection>;
  /** Record a pick on a node's candidates card in the chat that asked for
   * them: on the route of the node's Dataset Finder, *finderAttachmentId*,
   * naming the card. */
  onRecordSourcePick?: (
    finderAttachmentId: string,
    picks: AgentDatasetPick[],
    discoveryId?: string,
  ) => Promise<AgentDatasetSelection>;
  /** Another attachment of the dataflow, from the live list: a candidates
   * card in the chat that asked reads its node's Finder's record from it.
   * Null once the list no longer holds it; undefined with no list to read. */
  attachmentOf?: (attachmentId: string) => AgentAttachment | null | undefined;
  /** Whether a node is on the canvas; omitted, every node is taken as there. */
  nodeOnCanvas?: (nodeId: string) => boolean;
  /** Brings the card *discoveryId* into view when this chat holds it, else
   * opens the chat of its node's Finder (*finderAttachmentId*). */
  showCardOf?: (discoveryId: string | null, finderAttachmentId: string | null) => void;
  /** What this chat's agent is attached to, by the name its header shows: a
   * node's Dataset Finder names its card for its node. */
  targetName?: string | null;
  /** A build runs on this agent's plan: no plan row's Solve starts. */
  buildRunning?: boolean;
  /** What runs on this agent's plan now: each row of its card says its node's. */
  planLive?: PlanLive;
  /** A plan node's own agent, whose chat its row's name opens. */
  nodeChatOf?: (nodeId: string) => NodeChat | null;
  /** The name a node's header shows, null when the node is not on the
   * canvas: a change card's title names its node by it. */
  nodeNameOf?: (nodeId: string) => string | null;
  onImportDataset?: (
    file: File,
    discoverySource?: import("../../../../services/datasetCatalog/datasetCatalogTypes").DatasetDiscoverySourceInput,
  ) => Promise<string | null>;
  onApplyProposal?: (proposalId: string) => Promise<unknown>;
  /** dev/84: a package.install proposal applies THROUGH the install review dialog. */
  beginPackageReview: (proposalId: string, dirName: string) => Promise<unknown>;
  onDismissProposal?: (proposalId: string) => Promise<void>;
  /** Undo a change this attachment's agent made. */
  onUndoChange?: (changeId: string) => Promise<unknown>;
  /** Why the server refused the last Undo, Apply or Dismiss of the card of
   * a change or a proposal, by its id, as the chat keeps it. */
  refusalOf?: (cardId: string) => string | null;
  onSolvePlanNode?: (ref: string, onLine?: (line: string) => void) => Promise<void>;
  onRunPlanNode?: (ref: string, onLine?: (line: string) => void) => Promise<void>;
  /** An invited editor's chat: an install waits for the owner's review. */
  installsWaitForOwner?: boolean;
}

/**
 * One agent turn (split out of `AgentChatPanel.tsx` by memo dev/142, F4):
 * the avatar, the message, every typed content part it carries, the lines
 * that stay under it, and its meta line. Agent rich content renders ONLY
 * through the safe renderer (REQ-SEC-002); error markers and the lines under
 * the reply are plain text.
 *
 * Under the reply stays what a person acts on: a failed call's reason, that
 * a canvas agent changed nothing, a reply still running, stopped or failed.
 * What the run used (its skills, its time and tokens, the tools it called,
 * the cards of its trace, what ran a task it handed on) shows only with the
 * viewer's Show run details (*runDetails*).
 */
export const AgentTurn: React.FC<{
  turn: AgentSessionTurn;
  attachment: AgentAttachment;
  tint: string;
  meta: RunStatusDisplay | null;
  actions: AgentTurnActions;
  /** A canvas agent's reply that changed nothing on the canvas (#243). */
  canvasUnchanged?: boolean;
  /** The viewer shows run details. */
  runDetails?: boolean;
}> = ({ turn: t, attachment, tint, meta, actions, canvasUnchanged = false, runDetails = false }) => {
  // An agent on a node that records the dataset the node loads.
  const isFinderOnNode =
    declaresCapability(attachment, DATASET_SELECT_CAPABILITY) && attachment.target.kind === "node";
  // #447: the failed tool calls that keep their reason under the reply.
  const failedCalls = lastingToolFailures(t);
  const usedSkills = t.error || !runDetails ? [] : skillsUsedBy(t.execution);
  const toolsCalled = runDetails && !t.error ? toolsCalledBy(t) : [];
  // How the reply ended: running, stopped and failed are always said; a reply
  // that finished says its time and tokens with Show run details.
  const shownMeta = meta && (meta.kind !== "done" || runDetails) ? meta : null;
  // An install on an invited editor's chat is the owner's to review.
  const waitsForOwner = (part: AgentProposalPart) =>
    Boolean(actions.installsWaitForOwner) && installsIntoAccount(part.tool);
  // A node's own Dataset Finder: the chats that asked for its candidates hold
  // the same card, the one its record offers now, while their agents are on
  // the dataflow.
  const ownNode = attachment.target.targetId ?? null;
  const ownRecord = isFinderOnNode ? attachment.sourceRecord ?? null : null;
  const askerNames = askersOf(ownRecord)
    .filter((asker) => asker !== attachment.attachmentId)
    .map((asker) => actions.agentNameOf?.(asker) ?? null)
    .filter((name): name is string => Boolean(name));
  return (
    <div className={styles.agentRow}>
      <span className={`${styles.agentRowAvatar} ${tint}`} aria-hidden="true">
        <FontAwesomeIcon icon={faRobot} />
      </span>
      <div className={styles.agentCol}>
        <div className={`${styles.msgAgent} ${t.error ? styles.msgError : ""}`}>
          {t.error ? t.text : <SafeAgentContent text={t.text} onInternalLink={actions.onInternalLink} />}
          {t.error ? <LlmConfigAction remedy={t.remedy} /> : null}
          {(t.content ?? [])
            .filter((p): p is AgentCardPart => p.type === "card" && (runDetails || (p as AgentCardPart).runDetails !== true))
            .map((card, j) => (
              <AgentChatCard key={j} card={card} tintClassName={tint} />
            ))}
          {(t.content ?? [])
            .filter((p): p is AgentDatasetCandidatesPart => p.type === "datasetCandidates")
            .map((part, j) => (
              <AgentDatasetCandidatesCard
                key={`cand-${j}`}
                part={part}
                tintClassName={tint}
                // A card that records its own pick (Use this source) leaves
                // the message box alone; one with no pick of its own composes
                // the message that confirms its selection.
                onComposePrompt={
                  actions.onRecordDatasetSelection && isFinderOnNode ? undefined : actions.onComposePrompt
                }
                // dev/114: in the chat of an agent that builds nodes, the
                // runtime minted these from a dataset.discover delegation, so
                // the confirmation asks it to build.
                variant={declaresCapability(attachment, NODE_BUILD_CAPABILITY) ? "builder" : "finder"}
                // Any other agent hands a source to the agent it hands nodes
                // to build to, named as that agent's manifest names it.
                handoffName={attachment.nodeBuildDelegate}
                // dev/126: an agent that records selections, attached to a
                // NODE, records the confirmed source for it, which the node's
                // next Solve reads, naming the card it was made on.
                onRecordSelection={
                  actions.onRecordDatasetSelection && isFinderOnNode
                    ? (picks) =>
                        part.discoveryId
                          ? actions.onRecordDatasetSelection!(picks, part.discoveryId)
                          : actions.onRecordDatasetSelection!(picks)
                    : undefined
                }
                // dev/132: and the Import button under a portal row's download
                // steps: the same catalog import as the drawer footer.
                onImportDataset={actions.onImportDataset && isFinderOnNode ? actions.onImportDataset : undefined}
                // The Finder's card is named for its node and follows its
                // record: Recorded where the pick was made, closed once newer
                // candidates replaced it, and, while it is the card on offer,
                // it names the chats that asked, which hold the same card.
                {...(isFinderOnNode
                  ? {
                      nodeLabel: actions.targetName ?? null,
                      nodeId: ownNode,
                      record: ownRecord,
                      waitsForPick: Boolean(ownNode && (attachment.waitsForYou ?? []).includes(ownNode)),
                      discoveryId: part.discoveryId ?? null,
                      onShowNewest: actions.showCardOf
                        ? () => actions.showCardOf!(ownRecord?.discoveryId ?? null, null)
                        : null,
                      mirroredIn:
                        !part.discoveryId || ownRecord?.discoveryId === part.discoveryId ? askerNames : [],
                    }
                  : {})}
              />
            ))}
          {(t.content ?? [])
            .filter((p): p is AgentSourcePickPart => p.type === "sourcePick")
            .map((part, j) => {
              // A node's candidates in the chat that asked for them: the pick
              // records on the node's Dataset Finder, naming this card, and
              // the card follows that Finder's record, from the live list, as
              // its own card does. A Finder the list no longer holds closes
              // it (null); with no list to read (undefined) it stays open.
              const finder = actions.attachmentOf?.(part.finderAttachmentId);
              const finderName = finder ? actions.agentNameOf?.(part.finderAttachmentId) ?? finder.name : null;
              return (
                <AgentDatasetCandidatesCard
                  key={`pick-${part.nodeId}-${j}`}
                  part={{ type: "datasetCandidates", lanes: part.lanes }}
                  tintClassName={tint}
                  nodeLabel={part.nodeLabel}
                  nodeId={part.nodeId}
                  onRecordSelection={
                    actions.onRecordSourcePick
                      ? (picks) =>
                          part.discoveryId
                            ? actions.onRecordSourcePick!(part.finderAttachmentId, picks, part.discoveryId)
                            : actions.onRecordSourcePick!(part.finderAttachmentId, picks)
                      : undefined
                  }
                  onImportDataset={actions.onRecordSourcePick ? actions.onImportDataset : undefined}
                  record={finder?.sourceRecord ?? null}
                  waitsForPick={finder ? (finder.waitsForYou ?? []).includes(part.nodeId) : true}
                  discoveryId={part.discoveryId ?? null}
                  finderPresent={finder !== null}
                  nodePresent={actions.nodeOnCanvas ? actions.nodeOnCanvas(part.nodeId) : true}
                  onShowNewest={
                    actions.showCardOf
                      ? () => actions.showCardOf!(finder?.sourceRecord?.discoveryId ?? null, part.finderAttachmentId)
                      : null
                  }
                  finderChat={
                    finder && finderName && actions.onOpenAgentChat
                      ? { name: finderName, onOpen: () => actions.onOpenAgentChat!(part.finderAttachmentId) }
                      : null
                  }
                />
              );
            })}
          {(t.content ?? [])
            .filter((p): p is AgentSolveAttemptsPart => p.type === "solveAttempts")
            .map((part, j) => (
              // dev/127: every attempt to fix this node, with the code it ran.
              <AgentSolveAttemptsCard
                key={`attempts-${part.nodeId}-${j}`}
                part={part}
                tintClassName={tint}
                onOpenChat={actions.onOpenAgentChat}
                agentName={part.attachmentId ? actions.agentNameOf?.(part.attachmentId) ?? null : null}
              />
            ))}
          {(t.content ?? [])
            .filter((p): p is AgentDelegationPart => p.type === "delegation")
            .map((part, j) => (
              <AgentDelegationEntry
                key={`dlg-${j}`}
                part={part}
                onOpenChat={actions.onOpenAgentChat}
                delegateExists={actions.delegateExists}
                runDetails={runDetails}
              />
            ))}
          {(t.content ?? [])
            .filter((p): p is AgentChangePart => p.type === "change")
            .map((part, j) => (
              <AgentChangeCard
                key={part.changeId ?? j}
                part={part}
                tintClassName={tint}
                onUndo={actions.onUndoChange}
                refusal={actions.refusalOf?.(part.changeId) ?? null}
                planNodeState={planNodeStateFor(attachment, part, Boolean(actions.buildRunning), actions.planLive)}
                onSolvePlanNode={actions.onSolvePlanNode}
                onRunPlanNode={actions.onRunPlanNode}
                onOpenAgentChat={actions.onOpenAgentChat}
                delegateExists={actions.delegateExists}
                agentNameOf={actions.agentNameOf}
                nodeChatOf={actions.nodeChatOf}
                nodeName={part.nodeId ? actions.nodeNameOf?.(part.nodeId) ?? null : null}
                runDetails={runDetails}
              />
            ))}
          {(t.content ?? [])
            .filter((p): p is AgentProposalPart => p.type === "proposal")
            .map((part, j) => (
              <AgentReviewCard
                key={part.proposalId ?? j}
                part={part}
                tintClassName={tint}
                waitsForOwner={waitsForOwner(part)}
                onApply={
                  waitsForOwner(part)
                    ? undefined
                    : part.tool === "package.install" && actions.onApplyProposal
                      ? (proposalId) => actions.beginPackageReview(proposalId, part.pins?.dirName ?? "")
                      : actions.onApplyProposal
                }
                onDismiss={waitsForOwner(part) ? undefined : actions.onDismissProposal}
                refusal={actions.refusalOf?.(part.proposalId) ?? null}
              />
            ))}
        </div>
        {/* Why a call failed: what it did in plain words, and its tool's id
            with Show run details. */}
        {failedCalls.map((call, j) => (
          <div key={`call-${j}`} className={styles.turnNote}>
            {runDetails ? `${call.tool} · ${call.reason}` : failedCallWords(call)}
          </div>
        ))}
        {canvasUnchanged ? <div className={styles.turnNote}>No changes were made to the canvas</div> : null}
        {/* The skills this reply's run held or loaded, from its record: each
            name says on hover how the run came to hold it. */}
        {usedSkills.length > 0 ? (
          <div className={`${styles.turnNote} ${styles.turnSkills}`} data-curio-reply-skills="true">
            Skills:{" "}
            {usedSkills.map((skill, j) => (
              <React.Fragment key={skill.name}>
                {j > 0 ? ", " : null}
                <span className={styles.turnSkill} data-tooltip={SKILL_USE_WORDS[skill.use]}>
                  {skill.name}
                </span>
              </React.Fragment>
            ))}
          </div>
        ) : null}
        {/* Per-reply execution status (dev/80 amendment): running while THIS
            reply streams, then its own duration + tokens. */}
        {shownMeta ? (
          <div className={styles.turnMeta}>
            <AgentRunStatusLine display={shownMeta} tintClassName={tint} />
          </div>
        ) : null}
        {toolsCalled.length > 0 ? (
          <div className={`${styles.turnNote} ${styles.turnSkills}`} data-curio-reply-tools="true">
            Tools:{" "}
            {toolsCalled.map((tool, j) => (
              <React.Fragment key={tool}>
                {j > 0 ? ", " : null}
                <span className={styles.turnSkill}>{tool}</span>
              </React.Fragment>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
};
