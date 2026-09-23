import React from "react";
import { useHref } from "react-router-dom";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faLink, faTableColumns } from "@fortawesome/free-solid-svg-icons";

import { useToastContext } from "../../../providers/ToastProvider";
import { copyText } from "../../../utils/clipboard";
import { absoluteUrl, dashboardPath, dataflowPath } from "../../../utils/shareLinks";
import styles from "./UpMenu.module.css";

export const SAVE_FIRST_MESSAGE = "Save the dataflow first to share it.";
export const STALE_DASHBOARD_MESSAGE =
  "The dashboard shows the last saved version. Save to update it.";

export interface ShareMenuProps {
  /** The project id both links are built from; ``null`` before the first save. */
  id: string | null;
  /** The dataflow's bar offers the dashboard; the dashboard's own bar does not. */
  includeOpenDashboard: boolean;
  open: boolean;
  onToggle: () => void;
  onClose: () => void;
  /** Unsaved edits are not in what a visitor would open. */
  projectDirty?: boolean;
}

/**
 * The Share menu, on both top bars.
 *
 * One component because the dataflow and its dashboard are the same project
 * under two routes: a viewer given either link can reach the other, and the two
 * bars must not drift over what "share this" means.
 *
 * Both links are ordinary URLs into this app. A dataflow link opens the canvas,
 * read-only for anyone but the owner; a dashboard link opens the pinned tiles.
 * Neither mints a token or changes what the project already grants.
 */
export function ShareMenu({
  id,
  includeOpenDashboard,
  open,
  onToggle,
  onClose,
  projectDirty = false,
}: ShareMenuProps) {
  const { showToast } = useToastContext();
  // ``useHref`` applies the router's basename, which a hand-built path would
  // drop on a deployment served under a sub-path.
  const dashboardHref = useHref(dashboardPath(id ?? "x"));
  const dataflowHref = useHref(dataflowPath(id ?? "x"));
  const dashboardUrl = id ? absoluteUrl(dashboardHref) : "";
  const dataflowUrl = id ? absoluteUrl(dataflowHref) : "";

  const copy = async (value: string, label: string, done: string) => {
    onClose();
    if (!id) {
      showToast(SAVE_FIRST_MESSAGE, "info");
      return;
    }
    // A menu row has nowhere to show CopyButton's copied/failed state, so the
    // result is reported the way the rest of this bar reports things.
    const copied = await copyText(value, label);
    showToast(copied ? done : `Could not copy the ${label}.`, copied ? "success" : "error");
  };

  return (
    <div className={styles.dropdownWrapper}>
      <button className={styles.button} onClick={onToggle} data-testid="share-menu-btn">
        Share ⏷
      </button>
      {open && (
        <div className={styles.dropDownMenu} onClick={(e) => e.stopPropagation()}>
          {includeOpenDashboard && (
            <div className={styles.dropDownRow}>
              <FontAwesomeIcon className={styles.dropDownIcon} icon={faTableColumns} />
              {/* A real anchor, not a navigate: the dashboard opens in its own
                  tab so the dataflow the user is editing stays where it is, and
                  a user-initiated link is never caught by a popup blocker. */}
              <a
                className={styles.noStyleButton}
                href={id ? dashboardUrl : undefined}
                target={id ? "_blank" : undefined}
                rel="noopener noreferrer"
                data-testid="open-dashboard-link"
                onClick={(event) => {
                  onClose();
                  if (!id) {
                    event.preventDefault();
                    showToast(SAVE_FIRST_MESSAGE, "info");
                    return;
                  }
                  // Pins and tile geometry live in the spec, so an unsaved edit
                  // is not in the page about to open.
                  if (projectDirty) showToast(STALE_DASHBOARD_MESSAGE, "info");
                }}
              >
                Open dashboard
              </a>
            </div>
          )}
          <div
            className={styles.dropDownRow}
            onClick={() => void copy(dashboardUrl, "dashboard link", "Dashboard link copied.")}
          >
            <FontAwesomeIcon className={styles.dropDownIcon} icon={faLink} />
            <button className={styles.noStyleButton}>Copy dashboard link</button>
          </div>
          <div
            className={styles.dropDownRow}
            onClick={() => void copy(dataflowUrl, "dataflow link", "Dataflow link copied.")}
          >
            <FontAwesomeIcon className={styles.dropDownIcon} icon={faLink} />
            <button className={styles.noStyleButton}>Copy dataflow link</button>
          </div>
        </div>
      )}
    </div>
  );
}

export default ShareMenu;
