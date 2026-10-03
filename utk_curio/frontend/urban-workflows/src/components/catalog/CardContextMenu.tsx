import React, { useEffect } from "react";
import clsx from "clsx";
import menuStyles from "../menus/darkMenu.module.css";

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
      className={menuStyles.panel}
      // At the pointer, over everything on the page.
      style={{ position: "fixed", top: y, left: x, zIndex: 9999 }}
    >
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          role="menuitem"
          disabled={item.disabled}
          className={clsx(menuStyles.item, item.destructive && menuStyles.itemDestructive)}
          // Inline as well as in the class: the colour is the row's meaning,
          // and a test without the stylesheet still has to see it.
          style={item.destructive ? { color: "var(--curio-danger)" } : undefined}
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
