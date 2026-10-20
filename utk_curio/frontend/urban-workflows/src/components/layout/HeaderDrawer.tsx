import React, { useCallback, useEffect, useRef, useState } from "react";
import { DrawerHeader } from "../packages/publishing/DrawerHeader";
import shell from "../packages/publishing/CatalogDrawerShell.module.css";
import { useDrawerDragThrough } from "../packages/publishing/useDrawerDragThrough";
import { holdModalStack, modalStackDepth } from "../ModalShell";
import styles from "./HeaderDrawer.module.css";

export interface HeaderDrawerProps {
  presented: boolean;
  onRequestClose: () => void;
  onExitComplete: () => void;
  /** Its heading, and "Close <title>" on its close button. */
  title: string;
  titleId: string;
  /** Marks the root as `data-curio-<name>-drawer="true"`. */
  name: string;
  /** One line under the heading; none when left out. */
  subtitle?: string | null;
  /** The catalog drawers' pin: pinned, a scrim click or Escape leaves the
   *  drawer open, and only its close button closes it. */
  pinnable?: boolean;
  /** The 720 px of API Settings and Monitor; false gives the catalog
   *  drawers' 520 px. */
  wide?: boolean;
  children: React.ReactNode;
}

/**
 * A drawer opened over the canvas and the dashboard, so the dataflow stays
 * where it is: the top bar's API Settings and Monitor, in place of their
 * pages, and the dataflow's and its nodes' provenance.
 *
 * The catalog drawers' shell and header, one tier above them: a catalog card
 * can open API Settings over its own drawer. While mounted it holds a layer of
 * the modal stack, so every Escape listener below it stands down and one
 * Escape closes only this drawer.
 */
export const HeaderDrawer: React.FC<HeaderDrawerProps> = ({
  presented,
  onRequestClose,
  onExitComplete,
  title,
  titleId,
  name,
  subtitle = null,
  pinnable = false,
  wide = true,
  children,
}) => {
  const drawerRef = useRef<HTMLElement>(null);
  const dragThrough = useDrawerDragThrough();
  const [pinned, setPinned] = useState(false);

  useEffect(() => holdModalStack(), []);

  useEffect(() => {
    if (!presented) return;
    const onKey = (ev: KeyboardEvent) => {
      // This drawer is one layer of the stack itself: more is a modal on top.
      if (modalStackDepth() > 1) return;
      if (ev.key === "Escape" && !pinned) onRequestClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [presented, pinned, onRequestClose]);

  const handleTransitionEnd = useCallback(
    (e: React.TransitionEvent<HTMLElement>) => {
      if (e.target !== drawerRef.current || e.propertyName !== "transform" || presented) return;
      onExitComplete();
    },
    [onExitComplete, presented],
  );

  return (
    <div
      className={`${shell.overlayRoot} ${styles.overlayRoot} ${presented ? shell.overlayRootPresented : ""}`}
      {...{ [`data-curio-${name}-drawer`]: "true" }}
      aria-hidden={!presented}
      {...dragThrough}
    >
      <button
        type="button"
        className={shell.scrim}
        aria-label={`Dismiss ${title}`}
        onClick={() => {
          if (!pinned) onRequestClose();
        }}
      />
      <aside
        ref={drawerRef}
        className={wide ? `${shell.drawer} ${shell.drawerWide}` : shell.drawer}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onTransitionEnd={handleTransitionEnd}
      >
        <DrawerHeader
          kind={null}
          title={title}
          titleId={titleId}
          subtitle={subtitle}
          closeAriaLabel={`Close ${title}`}
          onClose={onRequestClose}
          pinned={pinned}
          onPinToggle={pinnable ? () => setPinned((v) => !v) : undefined}
        />
        <div className={shell.scrollBody}>{children}</div>
      </aside>
    </div>
  );
};

export default HeaderDrawer;
