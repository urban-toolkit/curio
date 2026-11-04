import React, { useCallback, useEffect, useRef, useState } from "react";
import { DrawerHeader } from "../packages/publishing/DrawerHeader";
import shell from "../packages/publishing/CatalogDrawerShell.module.css";
import { useDrawerDragThrough } from "../packages/publishing/useDrawerDragThrough";
import { holdDrawerLayer, isTopDrawer } from "../ModalShell";
import styles from "./HeaderDrawer.module.css";

export interface HeaderDrawerProps {
  presented: boolean;
  onRequestClose: () => void;
  onExitComplete: () => void;
  /** Its heading, its dialog's name, and "Close <title>" on its close button. */
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
  /** Beside the canvas rather than over it (Define scenario): no scrim, so
   *  the canvas and the top bar stay usable, and under the top bar at the
   *  catalog drawers' tier, so a drawer opened while it is open slides in over
   *  it. It takes the focus as it opens, and its body scrolls with the thin
   *  scrollbar. */
  beside?: boolean;
  /** Controls kept under the scroll body, such as a form's buttons. */
  footer?: React.ReactNode;
  /** The panel's `data-testid`. */
  testId?: string;
  children: React.ReactNode;
}

/**
 * A drawer opened over the canvas and the dashboard, so the dataflow stays
 * where it is: the top bar's API Settings and Monitor, in place of their
 * pages, the dataflow's and its nodes' provenance, and Define scenario beside
 * the canvas.
 *
 * The catalog drawers' shell and header, one tier above them: a catalog card
 * can open API Settings over its own drawer. While mounted it holds a drawer's
 * layer of the modal stack, so every Escape listener under the drawers stands
 * down, and it answers Escape only while it is the top layer (`isTopDrawer`):
 * one Escape closes the drawer on top alone.
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
  beside = false,
  footer = null,
  testId,
  children,
}) => {
  const drawerRef = useRef<HTMLElement>(null);
  const dragThrough = useDrawerDragThrough();
  const [pinned, setPinned] = useState(false);

  useEffect(() => holdDrawerLayer(), []);

  useEffect(() => {
    if (!presented) return;
    const onKey = (ev: KeyboardEvent) => {
      // A modal, a menu, or a drawer opened over this one takes the Escape.
      if (!isTopDrawer(drawerRef.current)) return;
      if (ev.key === "Escape" && !pinned) onRequestClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [presented, pinned, onRequestClose]);

  // Beside the canvas nothing else takes the focus: the panel does, as the
  // catalog drawers' panels do. Over it, API Settings puts it on the field a
  // card asked for itself.
  useEffect(() => {
    if (presented && beside) drawerRef.current?.focus();
  }, [presented, beside]);

  const handleTransitionEnd = useCallback(
    (e: React.TransitionEvent<HTMLElement>) => {
      if (e.target !== drawerRef.current || e.propertyName !== "transform" || presented) return;
      onExitComplete();
    },
    [onExitComplete, presented],
  );

  const rootClass = [
    shell.overlayRoot,
    styles.overlayRoot,
    presented ? shell.overlayRootPresented : "",
    beside ? styles.beside : "",
    beside && presented ? styles.besidePresented : "",
  ].join(" ");

  return (
    <div
      className={rootClass}
      {...{ [`data-curio-${name}-drawer`]: "true" }}
      aria-hidden={!presented}
      {...dragThrough}
    >
      {beside ? null : (
        <button
          type="button"
          className={shell.scrim}
          aria-label={`Dismiss ${title}`}
          onClick={() => {
            if (!pinned) onRequestClose();
          }}
        />
      )}
      <aside
        ref={drawerRef}
        className={wide ? `${shell.drawer} ${shell.drawerWide}` : shell.drawer}
        role="dialog"
        aria-modal={beside ? undefined : "true"}
        aria-labelledby={titleId}
        tabIndex={-1}
        data-curio-open-drawer={presented || undefined}
        data-testid={testId}
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
        <div className={beside ? `${shell.scrollBody} ${styles.besideBody}` : shell.scrollBody}>{children}</div>
        {footer}
      </aside>
    </div>
  );
};

export default HeaderDrawer;
