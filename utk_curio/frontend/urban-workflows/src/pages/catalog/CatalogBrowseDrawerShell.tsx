import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import styles from "./CatalogBrowseLayout.module.css";

export interface CatalogBrowseDrawerShellProps {
  /** True while a catalog item is selected and its detail should be visible. */
  presented: boolean;
  /** Called when the drawer grid slot should expand (true) or collapse (false). */
  onLayoutChange?: (slotOpen: boolean) => void;
  children: React.ReactNode;
}

/**
 * Shared right-hand detail drawer for the catalog browse pages. The entire
 * drawer column slides in from / out to the right and the page grid expands or
 * collapses in sync — matching the in-canvas drawer motion.
 */
export const CatalogBrowseDrawerShell: React.FC<CatalogBrowseDrawerShellProps> = ({
  presented,
  onLayoutChange,
  children,
}) => {
  const panelRef = useRef<HTMLElement>(null);
  const rafRef = useRef<number | null>(null);
  const lastContent = useRef<React.ReactNode>(null);
  if (presented && children != null) {
    lastContent.current = children;
  }

  const [mounted, setMounted] = useState(presented);
  const [open, setOpen] = useState(presented);

  useLayoutEffect(() => {
    onLayoutChange?.(presented);
    if (presented) {
      setMounted(true);
    } else {
      setOpen(false);
    }
  }, [presented, onLayoutChange]);

  useEffect(() => {
    if (!presented) return undefined;

    if (open) return undefined;

    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = requestAnimationFrame(() => setOpen(true));
    });
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, [presented, open]);

  const handleTransitionEnd = (event: React.TransitionEvent<HTMLElement>) => {
    if (event.target !== panelRef.current || event.propertyName !== "transform") return;
    if (!open) {
      setMounted(false);
      setOpen(false);
      lastContent.current = null;
    }
  };

  if (!mounted) return null;

  const content = presented ? children : lastContent.current;

  return (
    <div className={styles.browseDrawerColumn}>
      <aside
        ref={panelRef}
        className={`${styles.browseDrawer} ${open ? styles.browseDrawerOpen : ""}`}
        aria-hidden={!presented}
        onTransitionEnd={handleTransitionEnd}
      >
        {content}
      </aside>
    </div>
  );
};

export default CatalogBrowseDrawerShell;
