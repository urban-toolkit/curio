import React, { useEffect, useId, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faArrowUp } from "@fortawesome/free-solid-svg-icons";

import {
  skillsMatching,
  slashQuery,
  withSlashCommand,
  type RunSkill,
} from "../../../../services/agents";
import styles from "../AgentChatPanel.module.css";

/** The pill composer (memo dev/77): a one-row textarea that grows with content
 * (the caller's auto-grow ref), Enter sends, Shift+Enter falls through to the
 * native newline, an in-flight IME composition's commit-Enter never sends.
 *
 * With *loadSkills*, a message that starts with `/` opens the list of the
 * skills the chat's next run lists, read each time the list opens: typing
 * narrows it, the arrows move through it, Enter or Tab or a click puts
 * `/<name>` in the message, and Escape closes it without closing the chat.
 * Sent, `/<name>` hands that skill to the run with the message. */
export const Composer: React.FC<{
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  busy: boolean;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  loadSkills?: () => Promise<RunSkill[]>;
}> = ({ value, onChange, onSend, busy, textareaRef, loadSkills }) => {
  const listId = useId();
  const [caret, setCaret] = useState(value.length);
  const [skills, setSkills] = useState<RunSkill[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [active, setActive] = useState(0);
  // The text Escape closed the list at: it stays closed until the text changes.
  const [dismissedAt, setDismissedAt] = useState<string | null>(null);

  const query = loadSkills ? slashQuery(value, caret) : null;
  const open = query !== null && dismissedAt !== value;
  const matches = open && skills ? skillsMatching(skills, query) : [];

  useEffect(() => {
    if (!open || !loadSkills) return;
    let cancelled = false;
    setSkills(null);
    setLoadFailed(false);
    loadSkills()
      .then((rows) => {
        if (!cancelled) setSkills(rows);
      })
      .catch(() => {
        if (cancelled) return;
        setSkills([]);
        setLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
    // Read again each time the list opens, never on every key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => setActive(0), [query]);

  const pick = (name: string) => {
    const next = withSlashCommand(value, name);
    onChange(next);
    setCaret(next.length);
    setDismissedAt(null);
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.focus();
      // After React writes the new value, the caret goes after the space.
      window.setTimeout(() => textarea.setSelectionRange(next.length, next.length), 0);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (open && e.key === "Escape") {
      // The list's Escape, not the chat's: the panel closes on a window-level
      // Escape, which this one never reaches.
      e.preventDefault();
      e.stopPropagation();
      setDismissedAt(value);
      return;
    }
    if (open && matches.length > 0 && !e.nativeEvent.isComposing) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const step = e.key === "ArrowDown" ? 1 : matches.length - 1;
        setActive((index) => (index + step) % matches.length);
        return;
      }
      if ((e.key === "Enter" && !e.shiftKey) || e.key === "Tab") {
        e.preventDefault();
        pick(matches[Math.min(active, matches.length - 1)].name);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      onSend();
    }
  };

  const optionId = (index: number) => `${listId}-skill-${index}`;

  return (
    <div className={styles.footer}>
      {open ? (
        <div className={styles.skillMenu} id={listId} role="listbox" aria-label="Skills">
          {skills === null ? (
            <div className={styles.skillMenuNote}>Loading skills…</div>
          ) : loadFailed ? (
            <div className={styles.skillMenuNote}>Could not read this agent&apos;s skills.</div>
          ) : skills.length === 0 ? (
            <div className={styles.skillMenuNote}>This agent lists no skills.</div>
          ) : matches.length === 0 ? (
            <div className={styles.skillMenuNote}>No skill matches /{query}.</div>
          ) : (
            matches.map((skill, index) => (
              <div
                key={skill.name}
                id={optionId(index)}
                role="option"
                aria-selected={index === active}
                className={`${styles.skillOption} ${index === active ? styles.skillOptionActive : ""}`}
                // On mousedown, so the textarea keeps its focus.
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(skill.name);
                }}
                onMouseEnter={() => setActive(index)}
              >
                <span className={styles.skillOptionName}>
                  /{skill.name}
                  {skill.held ? <span className={styles.skillOptionHeld}> · in this chat</span> : null}
                </span>
                <span className={styles.skillOptionText}>{skill.description}</span>
              </div>
            ))
          )}
        </div>
      ) : null}
      <textarea
        ref={textareaRef}
        className={styles.input}
        value={value}
        rows={1}
        aria-label="Message this agent"
        placeholder="Message this agent…"
        aria-autocomplete={loadSkills ? "list" : undefined}
        aria-expanded={loadSkills ? open : undefined}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={open && matches.length > 0 ? optionId(Math.min(active, matches.length - 1)) : undefined}
        onChange={(e) => {
          onChange(e.target.value);
          setCaret(e.target.selectionStart ?? e.target.value.length);
        }}
        onSelect={(e) => setCaret(e.currentTarget.selectionStart ?? 0)}
        onKeyDown={onKeyDown}
      />
      <button
        type="button"
        className={styles.send}
        aria-label="Send"
        data-tooltip="Send"
        disabled={busy || !value.trim()}
        onClick={onSend}
      >
        {busy ? "…" : <FontAwesomeIcon icon={faArrowUp} />}
      </button>
    </div>
  );
};
