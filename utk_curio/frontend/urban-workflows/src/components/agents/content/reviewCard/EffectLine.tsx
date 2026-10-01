import React from "react";

import type { AgentProposalPart } from "../../../../services/agents";
import styles from "../AgentReviewCard.module.css";
import { EFFECT_LINE, nodeKindExecutable, planEffectLine } from "./reviewCardText";

/** What one Apply click does, per proposal kind — stated on the card. A plan's
 * line is dynamic and honest about removals (dev/52, dev/59); a node.create
 * says whether Solve can run the kind (dev/119, DEC-076). */
export const EffectLine: React.FC<{ part: AgentProposalPart }> = ({ part }) => {
  const planLine = planEffectLine(part);
  if (planLine) return <div className={styles.meta}>{planLine}</div>;
  if (!EFFECT_LINE[part.tool]) return null;
  return (
    <div className={styles.meta}>
      {EFFECT_LINE[part.tool]}
      {part.tool === "node.create" && part.source ? (
        // dev/115 (Amendment A2) → dev/118 (DEC-075) → dev/119 (DEC-076):
        // Apply places the node as proposed; the user's Solve runs, fixes and
        // verifies the code of every kind the sandbox can run. Whether it can
        // is the ROSTER's answer (pins.executable), falling back to the
        // registry descriptor; unknown says nothing rather than guessing.
        <>
          {nodeKindExecutable(part.pins) === true
            ? " Solve runs it in the sandbox and fixes errors before its code is trusted."
            : nodeKindExecutable(part.pins) === false
              ? " This kind has no code to run: Solve writes it, the browser or its own service renders it; it is never called verified."
              : null}
        </>
      ) : null}
    </div>
  );
};
