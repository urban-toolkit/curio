import React, { useState } from "react";
import type { AgentProposalPart } from "../../../services/agents";
import styles from "./AgentReviewCard.module.css";
import { BackendTrustBlock } from "./reviewCard/BackendTrustBlock";
import { EffectLine } from "./reviewCard/EffectLine";
import { JustificationBlock } from "./reviewCard/JustificationBlock";
import { PackageDraftDetails } from "./reviewCard/PackageDraftDetails";
import { ReviewActions } from "./reviewCard/ReviewActions";
import { SourceBlock } from "./reviewCard/SourceBlock";

// The names tests and callers reach through this module (memo dev/142, F4).
export { nodeKindExecutable } from "./reviewCard/reviewCardText";
export type { PlanNodeReviewState } from "./reviewCard/reviewCardText";

/**
 * The review card of an install (memo dev/41; the blueprint's planned
 * `AgentReviewCard`): a package, a package draft, a dataset, a Discovery
 * download or an agent changes the account, so it waits for the person who
 * asked. The agent proposes; the USER confirms here: Apply and Dismiss are
 * system review controls (the sanctioned exception family to "no agent action
 * buttons", same as the DEC-035 install dialog). The proposed content is model
 * output: it renders as inert plain text (REQ-SEC-002), never markup.
 * Non-pending proposals render inert with their outcome label. An agent's
 * change to the dataflow has no review: it lands, and its card is
 * `AgentChangeCard`.
 *
 * Since memo dev/142 (F4) the card COMPOSES one section per concern: source,
 * a draft's justification, package-draft details, the backend trust edge, the
 * effect line and the actions. It keeps only what spans them: the busy /
 * error state of an action.
 */
export const AgentReviewCard: React.FC<{
  part: AgentProposalPart;
  /** Tint class carrying the agent's category color for the accent dot. */
  tintClassName?: string;
  /** The card awaits settlement only. */
  onApply?: (proposalId: string) => Promise<unknown>;
  onDismiss?: (proposalId: string) => Promise<void>;
  /** An install on an invited editor's chat: it waits for the dataflow
   * owner's review, which the card says in place of Apply and Dismiss. */
  waitsForOwner?: boolean;
}> = ({ part, tintClassName, onApply, onDismiss, waitsForOwner = false }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const act = async (fn?: (proposalId: string) => Promise<unknown>) => {
    if (!fn || busy) return;
    setBusy(true);
    setError(null);
    try {
      await fn(part.proposalId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The review action failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.card} role="group" aria-label={`Review proposal: ${part.summary}`}>
      <div className={`${styles.header} ${tintClassName ?? ""}`}>
        <span className={styles.accentDot} aria-hidden="true" />
        <span>{part.summary}</span>
        <span className={styles.kind}>review</span>
      </div>
      {part.source ? <SourceBlock source={part.source} /> : null}
      <JustificationBlock part={part} />
      {part.tool === "package.draft.apply" && part.draft ? <PackageDraftDetails draft={part.draft} /> : null}
      {part.tool === "package.draft.apply" && part.backend ? <BackendTrustBlock backend={part.backend} /> : null}
      <div className={styles.preview}>{part.preview}</div>
      <EffectLine part={part} />
      <ReviewActions
        part={part}
        busy={busy}
        onApply={onApply ? () => void act(onApply) : undefined}
        onDismiss={onDismiss ? () => void act(onDismiss) : undefined}
        waitsForOwner={waitsForOwner}
      />
      {error ? <div className={styles.error}>{error}</div> : null}
    </div>
  );
};
