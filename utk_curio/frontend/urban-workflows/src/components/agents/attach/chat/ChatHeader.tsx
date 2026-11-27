import React from "react";
import clsx from "clsx";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCheck, faEllipsis, faFileLines, faPen, faTrashCan, faXmark } from "@fortawesome/free-solid-svg-icons";

import { formatTokenCount } from "../../../../services/agents";
import { agentCategoryIcon, agentCategoryKey } from "../../../menus/nodes/agentsPalette/agentCategoryStyle";
import styles from "../AgentChatPanel.module.css";
import { useMenuPopup } from "./useMenuPopup";

/** The tile an agent's glyph sits on, in its category's tint: the header's
 *  and the rail's. */
export function agentChipClass(category: string | null | undefined): string {
  return styles[`chip_${agentCategoryKey(category)}` as keyof typeof styles];
}

/** The tokens a conversation used, as its provider reported them. */
export interface ChatTokens {
  input: number;
  output: number;
  /** The replies that reported theirs. */
  replies: number;
  /** A reply runs, which can still add to them: the count pulses. */
  live: boolean;
}

/** What Show run details puts under each reply, under its name in More. */
export const RUN_DETAILS_SAYS = "Skills, time, tokens and tools under each reply";

/** What Edit initial intent edits, under its name in More. */
export const EDIT_INTENT_SAYS = "What this chat's agent starts from";

/**
 * The dark header of the open chat, one row (DEC-042, dev/21): the agent's
 * glyph, the conversation's title, what the agent is attached to (its ids on
 * that line's tooltip), then More and Close. More holds Rename conversation,
 * Edit initial intent, the viewer's Show run details, Clear conversation and
 * Tokens used. No Pin, no static "Agent Catalog" bar (that chrome is the
 * roster drawer's). The agents themselves are the rail's, beside it.
 */
export const ChatHeader: React.FC<{
  category: string | null | undefined;
  title: React.ReactNode;
  targetLabel: string;
  targetTooltip: string;
  titleError: string | null;
  /** Starts the rename; omitted, More offers none. */
  onRename?: () => void;
  /** Opens the instructions this chat's agent starts from for editing;
   *  omitted, More offers none. */
  onEditIntent?: () => void;
  /** The viewer's own Show run details, and its switch. */
  runDetails: { shown: boolean; onToggle: () => void };
  /** Asks to clear the conversation; omitted, More offers none. */
  onClear?: () => void;
  /** What the conversation used; null while none was reported. */
  tokens: ChatTokens | null;
  onClose: () => void;
}> = ({
  category,
  title,
  targetLabel,
  targetTooltip,
  titleError,
  onRename,
  onEditIntent,
  runDetails,
  onClear,
  tokens,
  onClose,
}) => {
  const menu = useMenuPopup();
  // More is named by what it does, which no reply's tokens change: its name
  // holds still while they arrive.
  const actions = [
    onRename ? "rename" : null,
    onEditIntent ? "edit initial intent" : null,
    "run details",
    onClear ? "clear" : null,
  ].filter(Boolean);
  const named = `More: ${actions.join(", ")}`;
  const choose = (action: () => void) => {
    menu.close();
    action();
  };
  const total = tokens ? tokens.input + tokens.output : 0;
  return (
    // Addressable from outside the CSS-module hash, so the #228 baseline can
    // clip to the header rather than spend its diff budget on an empty
    // transcript (agent-chat-names-its-node).
    <div className={styles.header} data-curio-chat-header="true">
      <span className={clsx(styles.headerGlyph, agentChipClass(category))} aria-hidden="true">
        <FontAwesomeIcon icon={agentCategoryIcon(category)} />
      </span>
      {title}
      <span className={styles.headerTarget} data-curio-chat-target="" data-tooltip={targetTooltip}>
        {targetLabel}
      </span>
      {titleError ? <span className={styles.titleError}>{titleError}</span> : null}
      <span className={styles.headerSpacer} />
      <span className={styles.menuWrap}>
        <button
          ref={(el) => {
            menu.anchorRef.current = el;
          }}
          type="button"
          className={clsx(styles.headerBtn, menu.open !== null && styles.headerBtnOpen)}
          aria-label={named}
          aria-haspopup="menu"
          aria-expanded={menu.open !== null}
          data-tooltip="More"
          onClick={() => menu.toggle(true)}
        >
          <FontAwesomeIcon icon={faEllipsis} />
        </button>
        {menu.open !== null ? (
          <div ref={menu.menuRef} className={styles.menu} role="menu" aria-label="Chat menu" onKeyDown={menu.onMenuKeyDown}>
            {onRename ? (
              <button type="button" role="menuitem" className={styles.menuItem} onClick={() => choose(onRename)}>
                <FontAwesomeIcon icon={faPen} className={styles.menuIcon} />
                Rename conversation
              </button>
            ) : null}
            {onEditIntent ? (
              <button type="button" role="menuitem" className={styles.menuItem} onClick={() => choose(onEditIntent)}>
                <FontAwesomeIcon icon={faFileLines} className={styles.menuIcon} />
                <span className={styles.menuItemText}>
                  Edit initial intent…
                  <span className={styles.menuItemSays}>{EDIT_INTENT_SAYS}</span>
                </span>
              </button>
            ) : null}
            <button
              type="button"
              role="menuitemcheckbox"
              aria-checked={runDetails.shown}
              className={styles.menuItem}
              onClick={() => choose(runDetails.onToggle)}
            >
              <span className={clsx(styles.menuCheck, runDetails.shown && styles.menuCheckOn)} aria-hidden="true">
                {runDetails.shown ? <FontAwesomeIcon icon={faCheck} /> : null}
              </span>
              <span className={styles.menuItemText}>
                Show run details
                <span className={styles.menuItemSays}>{RUN_DETAILS_SAYS}</span>
              </span>
            </button>
            {onClear ? (
              <>
                <div role="separator" className={styles.menuSep} />
                <button
                  type="button"
                  role="menuitem"
                  className={clsx(styles.menuItem, styles.menuItemDanger)}
                  onClick={() => choose(onClear)}
                >
                  <FontAwesomeIcon icon={faTrashCan} className={styles.menuIcon} />
                  Clear conversation…
                </button>
              </>
            ) : null}
            {tokens ? (
              <>
                <div role="separator" className={styles.menuSep} />
                {/* Read, not chosen: disabled, yet the focus and the arrows
                    reach it, so the keyboard reads it too. */}
                <div
                  role="menuitem"
                  aria-disabled="true"
                  tabIndex={-1}
                  className={styles.menuTokens}
                  aria-label={`Session token usage: ${formatTokenCount(total)} tokens, ${tokens.input.toLocaleString()} in and ${tokens.output.toLocaleString()} out, as the provider reported`}
                >
                  <span className={clsx(styles.menuTokensTotal, tokens.live && styles.menuTokensLive)}>
                    Tokens used: {formatTokenCount(total)}
                  </span>
                  <span className={styles.menuTokensSub}>
                    {formatTokenCount(tokens.input)} in, {formatTokenCount(tokens.output)} out, over {tokens.replies}{" "}
                    {tokens.replies === 1 ? "reply" : "replies"}
                  </span>
                </div>
              </>
            ) : null}
          </div>
        ) : null}
      </span>
      <button type="button" className={styles.headerBtn} aria-label="Close chat" data-tooltip="Close chat" onClick={onClose}>
        <FontAwesomeIcon icon={faXmark} />
      </button>
    </div>
  );
};
