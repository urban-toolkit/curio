import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faRobot } from "@fortawesome/free-solid-svg-icons";

import type {
  AgentAttachment,
  AgentCardPart,
  AgentDatasetCandidatesPart,
  AgentDatasetPick,
  AgentDatasetSelection,
  AgentDelegationPart,
  AgentProposalPart,
  AgentSessionTurn,
  AgentSolveAttemptsPart,
  RunStatusDisplay,
} from "../../../../services/agents";
import { AgentChatCard } from "../../content/AgentChatCard";
import { AgentDatasetCandidatesCard } from "../../content/AgentDatasetCandidatesCard";
import { AgentSolveAttemptsCard } from "../../content/AgentSolveAttemptsCard";
import { AgentDelegationEntry } from "../../content/AgentDelegationEntry";
import { AgentReviewCard } from "../../content/AgentReviewCard";
import { SafeAgentContent } from "../../content/SafeAgentContent";
import { AgentRunStatusLine } from "../AgentRunStatusLine";
import { LlmConfigAction } from "../../../llmConfigs/LlmConfigAction";
import styles from "../AgentChatPanel.module.css";
import { planNodeStateFor } from "./chatPanelDerived";

/** The review-before-apply and plan callbacks a turn's cards may need. */
export interface AgentTurnActions {
  onComposePrompt: (prompt: string) => void;
  /** A link the agent wrote to another Curio page: the owner decides whether leaving the dataflow needs a confirmation first. */
  onInternalLink?: (to: string) => void;
  onOpenAgentChat?: (attachmentId: string) => void;
  delegateExists?: (attachmentId: string) => boolean;
  onRecordDatasetSelection?: (picks: AgentDatasetPick[]) => Promise<AgentDatasetSelection>;
  onImportDataset?: (
    file: File,
    discoverySource?: import("../../../../services/datasetCatalog/datasetCatalogTypes").DatasetDiscoverySourceInput,
  ) => Promise<string | null>;
  onApplyProposal?: (proposalId: string) => Promise<unknown>;
  /** dev/84: a package.install proposal applies THROUGH the install review dialog. */
  beginPackageReview: (proposalId: string, dirName: string) => Promise<unknown>;
  onDismissProposal?: (proposalId: string) => Promise<void>;
  onApplyPlanNode?: (proposalId: string, ref: string) => Promise<void>;
  onSavePlanGoal?: (proposalId: string, ref: string, goal: string) => Promise<void>;
  onApplyPlanEdges?: (proposalId: string, indices?: number[]) => Promise<void>;
  onSolvePlanNode?: (ref: string) => Promise<void>;
  onRunPlanNode?: (ref: string) => Promise<void>;
}

/**
 * One agent turn (split out of `AgentChatPanel.tsx` by memo dev/142, F4):
 * the avatar, the message, every typed content part it carries, and its
 * meta line. Agent rich content renders ONLY through the safe renderer
 * (REQ-SEC-002); error markers are server-composed plain text.
 */
export const AgentTurn: React.FC<{
  turn: AgentSessionTurn;
  attachment: AgentAttachment;
  tint: string;
  meta: RunStatusDisplay | null;
  actions: AgentTurnActions;
}> = ({ turn: t, attachment, tint, meta, actions }) => {
  const isFinderOnNode =
    attachment.coord.startsWith("agent.dataset-finder@") && attachment.target.kind === "node";
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
            .filter((p): p is AgentCardPart => p.type === "card")
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
                onComposePrompt={actions.onComposePrompt}
                // dev/114: in the Node Builder's chat the runtime minted these
                // from a dataset.discover delegation — the confirmation asks
                // the builder to build.
                variant={attachment.coord.startsWith("agent.node-builder@") ? "builder" : "finder"}
                // dev/126: a Dataset Finder attached to a NODE can record the
                // confirmed source for it — what the node's next Solve reads.
                onRecordSelection={
                  actions.onRecordDatasetSelection && isFinderOnNode ? actions.onRecordDatasetSelection : undefined
                }
                // dev/132: and the Import button under a portal row's download
                // steps — the same catalog import as the drawer footer.
                onImportDataset={actions.onImportDataset && isFinderOnNode ? actions.onImportDataset : undefined}
              />
            ))}
          {(t.content ?? [])
            .filter((p): p is AgentSolveAttemptsPart => p.type === "solveAttempts")
            .map((part, j) => (
              // dev/127: every attempt to fix this node, with the code it ran.
              <AgentSolveAttemptsCard
                key={`attempts-${part.nodeId}-${j}`}
                part={part}
                tintClassName={tint}
                onOpenChat={actions.onOpenAgentChat}
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
              />
            ))}
          {(t.content ?? [])
            .filter((p): p is AgentProposalPart => p.type === "proposal")
            .map((part, j) => (
              <AgentReviewCard
                key={part.proposalId ?? j}
                part={part}
                tintClassName={tint}
                onApply={
                  part.tool === "package.install" && actions.onApplyProposal
                    ? (proposalId) => actions.beginPackageReview(proposalId, part.pins?.dirName ?? "")
                    : actions.onApplyProposal
                }
                onDismiss={actions.onDismissProposal}
                onApplyPlanNode={actions.onApplyPlanNode}
                onSavePlanGoal={actions.onSavePlanGoal}
                onApplyPlanEdges={actions.onApplyPlanEdges}
                onSolvePlanNode={actions.onSolvePlanNode}
                onRunPlanNode={actions.onRunPlanNode}
                onOpenAgentChat={actions.onOpenAgentChat}
                delegateExists={actions.delegateExists}
                planNodeState={planNodeStateFor(attachment, part)}
              />
            ))}
        </div>
        {/* Per-reply execution status (dev/80 amendment): running while THIS
            reply streams, then its own duration + tokens. */}
        {meta ? (
          <div className={styles.turnMeta}>
            <AgentRunStatusLine display={meta} tintClassName={tint} />
          </div>
        ) : null}
      </div>
    </div>
  );
};
