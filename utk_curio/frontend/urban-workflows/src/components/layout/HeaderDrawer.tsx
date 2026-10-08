import React, { useCallback, useEffect, useRef } from "react";
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
  children: React.ReactNode;
}

/**
 * What the top bar's API Settings and Monitor open on the canvas and the
 * dashboard, in place of their pages, so the dataflow stays where it is.
 *
 * The catalog drawers' shell and header, wider and without the pin, one tier
 * above them: a catalog card can open API Settings over its own drawer. While
 * mounted it holds a layer of the modal stack, so every Escape listener below
 * it stands down and one Escape closes only this drawer.
 */
export const HeaderDrawer: React.FC<HeaderDrawerProps> = ({
  presented,
  onRequestClose,
  onExitComplete,
  title,
  titleId,
  name,
  children,
}) => {
  const drawerRef = useRef<HTMLElement>(null);
  const dragThrough = useDrawerDragThrough();

  useEffect(() => holdModalStack(), []);

  useEffect(() => {
    if (!presented) return;
    const onKey = (ev: KeyboardEvent) => {
      // This drawer is one layer of the stack itself: more is a modal on top.
      if (modalStackDepth() > 1) return;
      if (ev.key === "Escape") onRequestClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [presented, onRequestClose]);

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
      <button type="button" className={shell.scrim} aria-label={`Dismiss ${title}`} onClick={onRequestClose} />
      <aside
        ref={drawerRef}
        className={`${shell.drawer} ${shell.drawerWide}`}
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
          subtitle={null}
          closeAriaLabel={`Close ${title}`}
          onClose={onRequestClose}
        />
        <div className={shell.scrollBody}>{children}</div>
      </aside>
    </div>
  );
};

export default HeaderDrawer;
