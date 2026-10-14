import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import clsx from "clsx";
import menuStyles from "../menus/darkMenu.module.css";

/** Space kept between a menu and the window's edges. */
const WINDOW_MARGIN = 8;

/** *start* moved back just enough for *size* to end inside *limit*, but
 *  never past the margin at its start. */
function fitInside(start: number, size: number, limit: number): number {
  if (start + size <= limit - WINDOW_MARGIN) return start;
  return Math.max(WINDOW_MARGIN, limit - WINDOW_MARGIN - size);
}

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
  /** "overlay": over the canvas's catalog drawers (--curio-z-modal, as
   *  ModalShell's overlay layer), for a menu a card dropped from a drawer opens. */
  layer?: "default" | "overlay";
}

export const CardContextMenu: React.FC<CardContextMenuProps> = ({
  x,
  y,
  items,
  onSelect,
  onDismiss,
  ariaLabel,
  layer = "default",
}) => {
  // Opened near the window's right or bottom edge, the menu moves back inside
  // it, and a menu taller than the window scrolls: a package's nodes can be
  // many, and rows past the edge were out of reach.
  const panelRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);
  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (!panel) return;
    const { width, height } = panel.getBoundingClientRect();
    setSize((prev) => (prev && prev.width === width && prev.height === height ? prev : { width, height }));
  }, [items]);

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
      ref={panelRef}
      role="menu"
      aria-label={ariaLabel}
      data-curio-card-context-menu="true"
      className={menuStyles.panel}
      // At the pointer, over everything on the page.
      style={{
        position: "fixed",
        top: size ? fitInside(y, size.height, window.innerHeight) : y,
        left: size ? fitInside(x, size.width, window.innerWidth) : x,
        zIndex: layer === "overlay" ? "var(--curio-z-modal)" : 9999,
        maxHeight: window.innerHeight - 2 * WINDOW_MARGIN,
        overflowY: "auto",
      }}
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
