import React, { useLayoutEffect, useState } from "react";
import clsx from "clsx";
import type { AgentAttachment } from "../../../services/agents";
import type { Person } from "../../../providers/collab/people";
import { usePeopleHere } from "../../../providers/collab/usePeopleHere";
import { AgentAvatarBadge } from "./AgentAvatarBadge";
import { PeopleHere, useAgentAtWorkText } from "./PeopleHere";
import styles from "./AgentDock.module.css";

/**
 * The canvas's dock, centered at the top of the canvas: who is here. The
 * canvas agents, as the same avatar chips as the node badges (per the
 * concept), and beside them a chip for each other person in the dataflow's
 * room, read from its doc's awareness, and for each agent at work there, with
 * the Activity button at the row's end (`PeopleHere`). A canvas agent at work
 * keeps its one chip, shown at work. Clicking an agent's avatar opens its
 * chat; the hover ✕ detaches. Your own chip is not in the row, so with nobody
 * else and no canvas agent the dock renders nothing.
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

/**
 * The dock's left edge, in pixels from the window's left, set on the page's
 * root while the dock shares the canvas title's row. The title, on the same
 * row from the left, is cut short where it would run under the dock
 * (`.workflowNameStyle` in UpMenu.module.css); a long dataflow name used to be
 * drawn over the dock and its goal field. Taken off, it is its default in
 * curioTokens.css, the window's width.
 */
export const DOCK_LEFT_PROPERTY = "--curio-canvas-dock-left";

/** Keep {@link DOCK_LEFT_PROPERTY} at *dock*'s left edge while it is drawn on
 *  the title's row, through its size, its container's and the window's, and
 *  take it off when the dock goes. */
function usePublishedLeftEdge(dock: HTMLElement | null, onTheTitlesRow: boolean): void {
  useLayoutEffect(() => {
    if (!dock || !onTheTitlesRow) return undefined;
    const root = document.documentElement;
    const publish = () => {
      root.style.setProperty(DOCK_LEFT_PROPERTY, `${Math.floor(dock.getBoundingClientRect().left)}px`);
    };
    publish();
    // Centered, the dock's left edge moves when its row grows or shrinks (an
    // agent, a person, the goal field) and when the canvas around it does.
    const resized = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(publish);
    resized?.observe(dock);
    if (dock.offsetParent) resized?.observe(dock.offsetParent);
    window.addEventListener("resize", publish);
    return () => {
      resized?.disconnect();
      window.removeEventListener("resize", publish);
      root.style.removeProperty(DOCK_LEFT_PROPERTY);
    };
  }, [dock, onTheTitlesRow]);
}

const NO_AGENTS: AgentAttachment[] = [];
const noop = () => undefined;

type BadgeProps = React.ComponentProps<typeof AgentAvatarBadge>;

/** A canvas agent at work, *work* in the room: its one chip, shown at work. */
function AgentAtWorkBadge({ work, ...badge }: Omit<BadgeProps, "atWork"> & { work: Person }) {
  const atWork = useAgentAtWorkText(work);
  return <AgentAvatarBadge {...badge} atWork={atWork} />;
}

export const AgentDock: React.FC<{
  /** The canvas agents: the owner's canvas has them, anyone else's none. */
  attachments?: AgentAttachment[];
  selectedId?: string | null;
  onSelect?: (attachmentId: string) => void;
  onDetach?: (attachmentId: string) => void;
  /** Shown whenever any agent is attached, canvas-target or not. */
  showGoal?: boolean;
  goal?: string;
  onGoalChange?: (goal: string) => void;
  /** A read-only canvas: the dock sits under its banner. */
  belowBanner?: boolean;
}> = ({
  attachments = NO_AGENTS,
  selectedId = null,
  onSelect = noop,
  onDetach = noop,
  showGoal,
  goal,
  onGoalChange,
  belowBanner = false,
}) => {
  const here = usePeopleHere();
  const [dock, setDock] = useState<HTMLDivElement | null>(null);
  // Under a read-only canvas's banner the dock is below the title's row.
  usePublishedLeftEdge(dock, !belowBanner);
  if (attachments.length === 0 && !showGoal && here.people.length === 0) return null;
  // A canvas agent at work is its chip among the canvas agents, shown at
  // work, never a second one in the row.
  const docked = new Set(attachments.map((a) => a.attachmentId));
  const working = new Map<string, Person>();
  const inRow = here.people.filter((person) => {
    const attachmentId = person.agent?.attachmentId;
    if (!attachmentId || !docked.has(attachmentId)) return true;
    working.set(attachmentId, person);
    return false;
  });
  return (
    <div
      ref={setDock}
      className={clsx(styles.dock, belowBanner && styles.dockBelowBanner)}
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
      {attachments.map((a) => {
        const badge = {
          attachment: a,
          active: selectedId === a.attachmentId,
          onOpen: () => onSelect(a.attachmentId),
          onDetach: () => onDetach(a.attachmentId),
        };
        const work = working.get(a.attachmentId);
        return work
          ? <AgentAtWorkBadge key={a.attachmentId} {...badge} work={work} />
          : <AgentAvatarBadge key={a.attachmentId} {...badge} />;
      })}
      {/* The Activity button ends the row whenever someone else is here, a
          canvas agent at work among them. */}
      {here.people.length > 0 && <PeopleHere people={inRow} pointerOf={here.pointerOf} onOpenAgent={onSelect} />}
    </div>
  );
};
