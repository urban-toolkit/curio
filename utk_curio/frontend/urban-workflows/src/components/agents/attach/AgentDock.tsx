import React from "react";
import type { AgentAttachment } from "../../../api/agentsApi";
import { AgentAvatarBadge } from "./AgentAvatarBadge";
import styles from "./AgentDock.module.css";

/**
 * Canvas-agent dock: the same avatar chips as the node badges (per the
 * concept), clustered in a persistent bar centered at the top of the canvas.
 * Clicking an avatar opens its chat; the hover ✕ detaches. Renders nothing when
 * there are no canvas agents.
 */
export const AgentDock: React.FC<{
  attachments: AgentAttachment[];
  selectedId: string | null;
  onSelect: (attachmentId: string) => void;
  onDetach: (attachmentId: string) => void;
  /** Shown whenever any agent is attached, canvas-target or not. */
  showGoal?: boolean;
  goal?: string;
  onGoalChange?: (goal: string) => void;
}> = ({ attachments, selectedId, onSelect, onDetach, showGoal, goal, onGoalChange }) => {
  if (attachments.length === 0 && !showGoal) return null;
  return (
    <div className={styles.dock} role="toolbar" aria-label="Canvas agents">
      {showGoal && (
        // The dataflow's goal. Five built-in agents declare `workflowGoal` in
        // their manifest `reads` (Node Content Builder, Connection Builder,
        // Workflow Suggester, Plan Coherence Validator, and the mission
        // composites), and the Dataflow Task Planner exists to turn a goal
        // into a plan. The context composer has always had a producer for it;
        // what disappeared with the old AI-assistance chrome was the only
        // place to type one, so the value was permanently "" and those agents
        // ran without the input their prompts are written around.
        <input
          className={styles.goalInput}
          type="text"
          value={goal ?? ""}
          onChange={(e) => onGoalChange?.(e.target.value)}
          placeholder="What is this dataflow for? (shared with your agents)"
          aria-label="Dataflow goal"
        />
      )}
      {attachments.map((a) => (
        <AgentAvatarBadge
          key={a.attachmentId}
          attachment={a}
          active={selectedId === a.attachmentId}
          onOpen={() => onSelect(a.attachmentId)}
          onDetach={() => onDetach(a.attachmentId)}
        />
      ))}
    </div>
  );
};
