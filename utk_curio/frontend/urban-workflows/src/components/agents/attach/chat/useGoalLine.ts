/**
 * The dataflow's goal as the chat's Goal line edits it: its button opens the
 * goal in a field; Enter or Save keeps the trimmed draft, an emptied one
 * clears the goal; Escape or Cancel leaves the goal as it was. Leaving the
 * field keeps it open: Save and Cancel are what close it, so a click on Cancel
 * never saves on its way. An unchanged draft saves nothing. The goal is the
 * dataflow's, not one agent's, so a field left open stays open when the chat
 * switches to another agent.
 */
import { useCallback, useEffect, useRef, useState } from "react";

export interface GoalLineState {
  editing: boolean;
  draft: string;
  setDraft: (value: string) => void;
  inputRef: React.MutableRefObject<HTMLInputElement | null>;
  /** The button that opens the field: Edit, or Add while there is no goal. */
  buttonRef: React.MutableRefObject<HTMLButtonElement | null>;
  start: () => void;
  finish: (save: boolean) => void;
}

export function useGoalLine(
  goal: string | undefined,
  onSaveGoal: ((goal: string) => void) | undefined,
): GoalLineState {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const wasEditing = useRef(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);

  // Opening the field focuses it with the goal selected; closing it hands
  // focus back to the button that opens it.
  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    } else if (wasEditing.current) {
      buttonRef.current?.focus();
    }
    wasEditing.current = editing;
  }, [editing]);

  const start = useCallback(() => {
    if (!onSaveGoal) return;
    setDraft(goal ?? "");
    setEditing(true);
  }, [goal, onSaveGoal]);

  const finish = useCallback(
    (save: boolean) => {
      if (!editing) return;
      setEditing(false);
      const next = draft.trim();
      if (save && onSaveGoal && next !== (goal ?? "").trim()) onSaveGoal(next);
    },
    [editing, draft, goal, onSaveGoal],
  );

  return { editing, draft, setDraft, inputRef, buttonRef, start, finish };
}
