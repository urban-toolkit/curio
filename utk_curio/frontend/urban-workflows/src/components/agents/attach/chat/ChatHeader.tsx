import React from "react";
import clsx from "clsx";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faEllipsis, faPen, faTrashCan, faXmark } from "@fortawesome/free-solid-svg-icons";

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
}

/**
 * The dark header of the open chat, one row (DEC-042, dev/21): the agent's
 * glyph, the conversation's title, what the agent is attached to (its ids on
 * that line's tooltip), then More (Rename conversation, Clear conversation,
 * Tokens used) and Close. No Pin, no static "Agent Catalog" bar (that chrome
 * is the roster drawer's). The agents themselves are the rail's, beside it.
 */
export const ChatHeader: React.FC<{
  category: string | null | undefined;
  title: React.ReactNode;
  targetLabel: string;
  targetTooltip: string;
  titleError: string | null;
  /** Starts the rename; omitted, More offers none. */
  onRename?: () => void;
  /** Asks to clear the conversation; omitted, More offers none. */
  onClear?: () => void;
  /** What the conversation used; null while none was reported. */
  tokens: ChatTokens | null;
  onClose: () => void;
}> = ({ category, title, targetLabel, targetTooltip, titleError, onRename, onClear, tokens, onClose }) => {
  const menu = useMenuPopup();
  const offers = [onRename ? "rename" : null, onClear ? "clear" : null, tokens ? "tokens used" : null].filter(Boolean);
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
      {offers.length > 0 ? (
        <span className={styles.menuWrap}>
          <button
            ref={(el) => {
              menu.anchorRef.current = el;
            }}
            type="button"
            className={clsx(styles.headerBtn, menu.open !== null && styles.headerBtnOpen)}
            aria-label={`More: ${offers.join(", ")}`}
            aria-haspopup="menu"
            aria-expanded={menu.open !== null}
            data-tooltip="More"
            onClick={() => menu.toggle(true)}
          >
            <FontAwesomeIcon icon={faEllipsis} />
          </button>
          {menu.open !== null ? (
            <div
              ref={menu.menuRef}
              className={styles.menu}
              role="menu"
              aria-label="Chat menu"
              onKeyDown={menu.onMenuKeyDown}
            >
              {onRename ? (
                <button type="button" role="menuitem" className={styles.menuItem} onClick={() => choose(onRename)}>
                  <FontAwesomeIcon icon={faPen} className={styles.menuIcon} />
                  Rename conversation
                </button>
              ) : null}
              {onClear ? (
                <button
                  type="button"
                  role="menuitem"
                  className={clsx(styles.menuItem, styles.menuItemDanger)}
                  onClick={() => choose(onClear)}
                >
                  <FontAwesomeIcon icon={faTrashCan} className={styles.menuIcon} />
                  Clear conversation…
                </button>
              ) : null}
              {tokens ? (
                <>
                  {onRename || onClear ? <div role="separator" className={styles.menuSep} /> : null}
                  <div
                    role="menuitem"
                    aria-disabled="true"
                    className={styles.menuTokens}
                    aria-label={`Session token usage: ${formatTokenCount(total)} tokens, ${tokens.input.toLocaleString()} in and ${tokens.output.toLocaleString()} out, as the provider reported`}
                  >
                    <span className={styles.menuTokensTotal}>Tokens used: {formatTokenCount(total)}</span>
                    <span className={styles.menuTokensSub}>
                      {formatTokenCount(tokens.input)} in, {formatTokenCount(tokens.output)} out, over{" "}
                      {tokens.replies} {tokens.replies === 1 ? "reply" : "replies"}
                    </span>
                  </div>
                </>
              ) : null}
            </div>
          ) : null}
        </span>
      ) : null}
      <button type="button" className={styles.headerBtn} aria-label="Close chat" data-tooltip="Close chat" onClick={onClose}>
        <FontAwesomeIcon icon={faXmark} />
      </button>
    </div>
  );
};
