import React, { useEffect, useId, useRef } from "react";
import clsx from "clsx";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import type { IconDefinition } from "@fortawesome/fontawesome-svg-core";

import headerStyles from "../../layout/GlobalPageHeader.module.css";
import menuStyles from "../darkMenu.module.css";
import styles from "./HeaderMenu.module.css";

export interface HeaderMenuProps {
  /** The menu's name. The trigger shows it and is announced as "<label> menu". */
  label: string;
  open: boolean;
  onToggle: () => void;
  /** Called on Escape and on a click anywhere outside the menu. */
  onClose: () => void;
  testId?: string;
  children: React.ReactNode;
}

/**
 * A menu on the top bar: a trigger, and under it a panel of rows.
 *
 * A disclosure rather than an ARIA menu: the rows are ordinary buttons (see
 * `HeaderMenuItem`), reachable with Tab, which is also what every test and
 * recording selects them by. The panel is the trigger's next sibling, so
 * "the first row of the File menu" stays a plain DOM question.
 *
 * Open state is the caller's, so one bar can keep only one menu open.
 */
export function HeaderMenu({ label, open, onToggle, onClose, testId, children }: HeaderMenuProps) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    const onClick = (event: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) onClose();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, onClose]);

  return (
    <div className={styles.wrapper} ref={wrapperRef}>
      <button
        type="button"
        className={clsx(headerStyles.barButton, headerStyles.menuCaret, open && headerStyles.barButtonActive)}
        aria-label={`${label} menu`}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        data-testid={testId}
        onClick={onToggle}
      >
        {label}
      </button>
      {open && (
        <div id={panelId} className={clsx(menuStyles.panel, styles.panel)}>
          {children}
        </div>
      )}
    </div>
  );
}

export interface HeaderMenuItemProps {
  icon: IconDefinition;
  onClick?: () => void;
  disabled?: boolean;
  testId?: string;
  children: React.ReactNode;
}

/** One row: a real button, its icon in a fixed column. */
export function HeaderMenuItem({ icon, onClick, disabled, testId, children }: HeaderMenuItemProps) {
  return (
    <button type="button" className={menuStyles.item} onClick={onClick} disabled={disabled} data-testid={testId}>
      <FontAwesomeIcon className={menuStyles.itemIcon} icon={icon} />
      <span>{children}</span>
    </button>
  );
}

export function HeaderMenuDivider() {
  return <div className={menuStyles.divider} role="separator" />;
}

export default HeaderMenu;
