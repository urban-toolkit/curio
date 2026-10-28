import React, { useLayoutEffect, useState } from "react";
import type { AgentAttachment } from "../../../services/agents";
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

/** The least room left between the dataflow's title and the dock. */
const TITLE_GAP = 16;

/**
 * How far right of its centered place the dock goes to start past the
 * dataflow's title, which sits at the canvas's left (UpMenu's
 * `[data-curio-canvas-title]`) and which a long name stretches under the dock
 * on a narrow window. 0 while the two do not meet, so a dock with room stays
 * where its stylesheet puts it; never past the canvas's right edge.
 */
function useRoomBesideTitle(dock: HTMLDivElement | null): number {
  const [shift, setShift] = useState(0);
  useLayoutEffect(() => {
    const title = document.querySelector<HTMLElement>("[data-curio-canvas-title]");
    if (!dock || !title) return;
    const measure = () => {
      // The name as shown, or its input while it is being renamed.
      const name = title.firstElementChild?.getBoundingClientRect();
      const area = (dock.offsetParent ?? document.body).getBoundingClientRect();
      const box = dock.getBoundingClientRect();
      const centered = area.left + area.width / 2 - dock.offsetWidth / 2;
      const wanted = name && name.bottom > box.top && name.top < box.bottom
        ? name.right + TITLE_GAP - centered
        : 0;
      const room = area.right - TITLE_GAP - (centered + dock.offsetWidth);
      setShift(Math.max(0, Math.min(wanted, room)));
    };
    measure();
    // A rename changes the title's size, and so does the switch between the
    // name and its input; agents attached or detached change the dock's.
    const resized = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    resized?.observe(title);
    resized?.observe(dock);
    const swapped = new MutationObserver(measure);
    swapped.observe(title, { childList: true });
    window.addEventListener("resize", measure);
    return () => {
      resized?.disconnect();
      swapped.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [dock]);
  return shift;
}

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
  const [dock, setDock] = useState<HTMLDivElement | null>(null);
  const shift = useRoomBesideTitle(dock);
  if (attachments.length === 0 && !showGoal) return null;
  return (
    <div
      ref={setDock}
      className={styles.dock}
      // Past a long title (useRoomBesideTitle). No style at all while there
      // is room, so the stylesheet's centering stands.
      style={shift > 0 ? { transform: `translateX(calc(-50% + ${shift}px))` } : undefined}
      role="toolbar"
      aria-label="Canvas agents"
    >
      {showGoal && (
        // The dataflow's goal. Built-in agents declare `workflowGoal` in
        // their manifest `reads` (the Node Builder's content mode, and the
        // planning and reading delegates), and planning exists to turn
        // a goal into a plan. The context composer has always had a producer for it;
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
            data-tooltip="The dataflow's goal, shared with every agent that reads it"
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
