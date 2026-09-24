import React, { useEffect } from "react";
import type * as CSS from "csstype";

/**
 * The right-click menu a browse card opens, in one place.
 *
 * Every browse grid in the app is the same object: a card you select, with a
 * detail drawer on the right offering what can be done to it. Only the projects
 * page answered a right-click, though - the Node, Data and Agent Catalogs let
 * the event through to the browser, so the same gesture on the same-shaped card
 * produced an app menu on one page and Back/Reload/View Page Source on the
 * other three (#285).
 *
 * The projects page's menu was written inline, which is why nothing else could
 * have one without copying it. It lives here now, and all four grids render it.
 * Keep it that way: a fifth grid should import this rather than grow its own.
 *
 * The dismissal rules are the component's, not the caller's. The projects page
 * registered its own document-click listener and had no Escape at all; putting
 * both here means a new surface cannot forget either one.
 */

export interface CardContextMenuItem {
  /** Returned to `onSelect`. The caller's own action id. */
  id: string;
  label: string;
  /**
   * Red, and phrased as a way out. Reserve it for actions that destroy
   * something: the catalogs' "Remove from all projects" detaches an item and
   * leaves it in the catalog, and the drawer paints that in the light
   * way-out style rather than in danger red - so the menu does too.
   */
  destructive?: boolean;
  disabled?: boolean;
}

export interface CardContextMenuProps {
  /** Viewport coordinates, straight from the contextmenu event. */
  x: number;
  y: number;
  items: CardContextMenuItem[];
  onSelect: (id: string) => void;
  onDismiss: () => void;
  /** Names the menu for assistive tech, e.g. "Dataset actions". */
  ariaLabel: string;
}

export const CardContextMenu: React.FC<CardContextMenuProps> = ({
  x,
  y,
  items,
  onSelect,
  onDismiss,
  ariaLabel,
}) => {
  useEffect(() => {
    const dismiss = () => onDismiss();
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onDismiss();
    };
    document.addEventListener("click", dismiss);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("click", dismiss);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [onDismiss]);

  if (items.length === 0) return null;

  return (
    <div
      role="menu"
      aria-label={ariaLabel}
      data-curio-card-context-menu="true"
      style={{ ...menuStyle, top: y, left: x }}
    >
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          role="menuitem"
          disabled={item.disabled}
          style={
            item.destructive
              ? { ...itemStyle, color: "var(--curio-danger)" }
              : item.disabled
                ? { ...itemStyle, opacity: 0.5, cursor: "not-allowed" }
                : itemStyle
          }
          onClick={() => {
            onSelect(item.id);
            onDismiss();
          }}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
};

export default CardContextMenu;

/* ---- Styles ---- */

const menuStyle: CSS.Properties = {
  position: "fixed",
  backgroundColor: "var(--curio-top-bar-bg)",
  border: "1px solid var(--curio-border-context-menu)",
  borderRadius: "var(--curio-radius-sm)",
  zIndex: 9999,
  minWidth: "160px",
  boxShadow: "var(--curio-shadow-context-menu)",
};

const itemStyle: CSS.Properties = {
  // These are <button>s rather than clickable <div>s, so the browser's own
  // button chrome has to be reset for the row to look as it did. Worth the
  // extra lines: the divs were unreachable by keyboard and announced as nothing.
  display: "block",
  width: "100%",
  textAlign: "left",
  background: "none",
  border: "none",
  padding: "8px 16px",
  color: "var(--curio-text-on-dark)",
  fontSize: "var(--curio-font-size-md)",
  cursor: "pointer",
};
