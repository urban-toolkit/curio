/**
 * Inline click-to-rename conversation title (memo dev/25; split out of
 * `AgentChatPanel.tsx` by memo dev/142, F4): only the custom portion after
 * "<name>: " is editable; the template-name prefix is fixed. Enter and blur
 * both commit (one save), Escape cancels, an empty or unchanged draft is a
 * cancel; the optimistic value shows until the reloaded attachment's title
 * supersedes it; cycling to another agent discards any in-progress rename.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import type { AgentAttachment } from "../../../../services/agents";

export interface ConversationTitleState {
  editing: boolean;
  draft: string;
  setDraft: (value: string) => void;
  /** The optimistic title while a rename round-trips, else the attachment's. */
  displayedTitle: string | null | undefined;
  error: string | null;
  inputRef: React.MutableRefObject<HTMLInputElement | null>;
  buttonRef: React.MutableRefObject<HTMLButtonElement | null>;
  start: () => void;
  finish: (commit: boolean) => void;
}

export function useConversationTitle(
  attachment: AgentAttachment,
  onSaveTitle: ((title: string) => Promise<void>) | undefined,
): ConversationTitleState {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [pendingTitle, setPendingTitle] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const editDone = useRef(true);
  const wasEditing = useRef(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);

  // Cycling to another agent discards any in-progress rename state.
  useEffect(() => {
    editDone.current = true;
    setEditing(false);
    setPendingTitle(null);
    setError(null);
  }, [attachment.attachmentId]);

  // The reloaded attachment is authoritative: once its title changes (the
  // save round-tripped), it supersedes the optimistic value.
  useEffect(() => {
    setPendingTitle(null);
  }, [attachment.title]);

  // Entering edit mode focuses the input with the current value selected;
  // leaving it hands focus back to the title control.
  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    } else if (wasEditing.current) {
      buttonRef.current?.focus();
    }
    wasEditing.current = editing;
  }, [editing]);

  const displayedTitle = pendingTitle ?? attachment.title;

  const start = useCallback(() => {
    if (!onSaveTitle) return;
    editDone.current = false;
    setDraft(displayedTitle ?? "");
    setError(null);
    setEditing(true);
  }, [onSaveTitle, displayedTitle]);

  const finish = useCallback(
    (commit: boolean) => {
      if (editDone.current) return;
      editDone.current = true;
      setEditing(false);
      const next = draft.trim();
      if (!commit || !onSaveTitle || !next || next === (displayedTitle ?? "")) return;
      setPendingTitle(next);
      onSaveTitle(next).catch((e) => {
        setPendingTitle(null);
        setError(e instanceof Error ? e.message : "Failed to rename the conversation");
      });
    },
    [draft, onSaveTitle, displayedTitle],
  );

  return { editing, draft, setDraft, displayedTitle, error, inputRef, buttonRef, start, finish };
}
