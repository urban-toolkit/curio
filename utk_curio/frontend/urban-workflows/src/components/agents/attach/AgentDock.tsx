import React from "react";
import type { AgentAttachment } from "../../../api/agentsApi";
import { AgentAvatarBadge } from "./AgentAvatarBadge";
import styles from "./AgentDock.module.css";

/**
 * Canvas-agent dock: the same avatar chips as the node badges (per the
 * concept), clustered in a persistent bar centered at the top of the canvas.
 * Clicking an avatar opens its chat; the hover ✕ detaches. Renders nothing when
 * there are no canvas agents.
 *
 * The goal field here is NOT a chat composer, which is what #227 assumed when
 * it asked which of several attached agents answers a question typed into it.
 * Nothing is sent and nothing answers: the value is a persisted property of the
 * dataflow, handed to every agent that declares ``workflowGoal`` in its
 * manifest ``reads``. It read as a composer because it sat among the agent
 * chips with a placeholder-only label, so the label is now permanent.
 */
/** Short enough to be read in full at the field's narrowest (#227). */
export const GOAL_PLACEHOLDER = "What is this dataflow for?";

const GOAL_INPUT_ID = "curio-dataflow-goal";

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
        <span className={styles.goalField}>
          {/* A standing label, not a placeholder. The placeholder was the only
              thing naming this field, so it disappeared the moment anything was
              typed -- and it was too long to read in full besides (#227). */}
          <label className={styles.goalLabel} htmlFor={GOAL_INPUT_ID}>
            Goal
          </label>
          <input
            id={GOAL_INPUT_ID}
            className={styles.goalInput}
            type="text"
            value={goal ?? ""}
            onChange={(e) => onGoalChange?.(e.target.value)}
            placeholder={GOAL_PLACEHOLDER}
            // The half the placeholder had to drop to fit. It is the answer to
            // "who sees this?", which is worth keeping somewhere.
            title="The dataflow's goal, shared with every agent that reads it"
            aria-label="Dataflow goal"
          />
        </span>
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
