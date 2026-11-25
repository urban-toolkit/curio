import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faPen, faPlus } from "@fortawesome/free-solid-svg-icons";

import styles from "../AgentChatPanel.module.css";
import type { GoalLineState } from "./useGoalLine";

/** What the line offers while the dataflow has no goal. Short enough to be
 *  read whole at the panel's narrowest (#227). */
export const GOAL_EMPTY = "Add what this dataflow is for";

/** The field's placeholder, as short. */
export const GOAL_PLACEHOLDER = "What is this dataflow for?";

/** Who reads the goal, on the label's hover. */
export const GOAL_TOOLTIP = "The dataflow's goal. The agents on this dataflow read it.";

/**
 * The dataflow's goal (the spec's `task`), the line under the header of every
 * agent's chat. Nothing typed here is sent and no agent answers it: the agents
 * read it, with each message (the planning and reading delegates as "Task:",
 * the Dataflow Builder, Dataset Finder and Researcher as "Mission:") or through
 * dataflow.read (the Node Builder), and it is saved with the dataflow.
 *
 * It sat in the canvas's dock, among the agents' chips, where it read as a
 * chat box (#227); here it is a labelled line with its own Edit button.
 */
export const GoalLine: React.FC<{
  goal: string;
  state: GoalLineState;
}> = ({ goal, state }) => (
  // A sibling of the header, never inside it: the header's frame
  // (agent-chat-names-its-node) clips to `data-curio-chat-header`.
  <div className={styles.goalLine} data-curio-chat-goal="">
    <span className={styles.goalLabel} data-tooltip={GOAL_TOOLTIP}>
      Goal
    </span>
    {state.editing ? (
      <>
        <input
          ref={state.inputRef}
          className={styles.goalInput}
          type="text"
          aria-label="Dataflow goal"
          placeholder={GOAL_PLACEHOLDER}
          value={state.draft}
          onChange={(e) => state.setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.nativeEvent.isComposing) return;
            if (e.key === "Enter") {
              e.preventDefault();
              state.finish(true);
            } else if (e.key === "Escape") {
              // The panel's Escape closes the chat; this one only ends the edit.
              e.stopPropagation();
              state.finish(false);
            }
          }}
        />
        <button type="button" className={styles.intentSave} onClick={() => state.finish(true)}>
          Save
        </button>
        <button type="button" className={styles.intentCancel} onClick={() => state.finish(false)}>
          Cancel
        </button>
      </>
    ) : goal ? (
      <>
        <span className={styles.goalText}>{goal}</span>
        <button
          ref={state.buttonRef}
          type="button"
          className={styles.goalEdit}
          aria-label="Edit the goal"
          data-tooltip="Edit the goal"
          onClick={state.start}
        >
          <FontAwesomeIcon icon={faPen} />
        </button>
      </>
    ) : (
      <button ref={state.buttonRef} type="button" className={styles.goalAdd} onClick={state.start}>
        <FontAwesomeIcon icon={faPlus} />
        {GOAL_EMPTY}
      </button>
    )}
  </div>
);
