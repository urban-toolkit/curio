import React from "react";
import clsx from "clsx";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faLightbulb } from "@fortawesome/free-solid-svg-icons";

import styles from "../AgentChatPanel.module.css";
import { useMenuPopup } from "./useMenuPopup";

/** The newest reply's suggested messages, its first one first, each once. */
export function suggestionsOf(part: { primary: string; alternatives: string[] } | null): string[] {
  if (!part) return [];
  const all = [part.primary, ...part.alternatives].map((text) => text.trim()).filter(Boolean);
  return all.filter((text, i) => all.indexOf(text) === i);
}

/**
 * The newest reply's suggested messages, behind one button above the message
 * box, which says how many there are (memo dev/39, docs/08). The box stays
 * empty for the person's own words: a suggestion goes into it only when they
 * pick one from the button's menu, and nothing is sent until they press Send.
 */
export const SuggestedPromptsRow: React.FC<{
  suggestions: string[];
  /** Puts the picked suggestion in the message box. */
  onPick: (prompt: string) => void;
}> = ({ suggestions, onPick }) => {
  const menu = useMenuPopup();
  if (suggestions.length === 0) return null;
  const count = `${suggestions.length} suggestion${suggestions.length === 1 ? "" : "s"}`;
  return (
    <div className={styles.suggestedRow}>
      <span className={styles.menuWrap}>
        <button
          ref={(el) => {
            menu.anchorRef.current = el;
          }}
          type="button"
          className={clsx(styles.suggestedButton, menu.open !== null && styles.suggestedButtonOpen)}
          aria-haspopup="menu"
          aria-expanded={menu.open !== null}
          onClick={() => menu.toggle(true)}
        >
          <FontAwesomeIcon icon={faLightbulb} aria-hidden="true" />
          {count}
        </button>
        {menu.open !== null ? (
          <div
            ref={menu.menuRef}
            className={styles.suggestedMenu}
            role="menu"
            aria-label="Suggested messages"
            onKeyDown={menu.onMenuKeyDown}
          >
            {suggestions.map((text) => (
              <button
                key={text}
                type="button"
                role="menuitem"
                className={styles.suggestedItem}
                onClick={() => {
                  menu.close();
                  onPick(text);
                }}
              >
                {text}
              </button>
            ))}
          </div>
        ) : null}
      </span>
    </div>
  );
};
