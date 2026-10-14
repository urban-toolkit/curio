import React from "react";
import { useHref } from "react-router-dom";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faLink, faTableColumns } from "@fortawesome/free-solid-svg-icons";

import { useToastContext } from "../../../providers/ToastProvider";
import { copyText } from "../../../utils/clipboard";
import { absoluteUrl, dashboardPath, dataflowPath } from "../../../utils/shareLinks";
import menuStyles from "../darkMenu.module.css";
import { HeaderMenu, HeaderMenuItem } from "./HeaderMenu";
import { publishedApi, publishLinkToken, runLink } from "../../../services/published/publishedApi";

export const SAVE_FIRST_MESSAGE = "Save the dataflow first to share it.";
export const STALE_DASHBOARD_MESSAGE =
  "The dashboard shows the last saved version. Save to update it.";
export const RUN_LINK_COPIED =
  "Dashboard link copied. Whoever opens it can change the inputs and run it; their runs are not saved.";

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
  /** The owner, who may save the dataflow: the dashboard link they copy lets
   *  whoever opens it run the dashboard (backend `published/`). */
  canPublish?: boolean;
}

/**
 * The Share menu, on both top bars.
 *
 * One component because the dataflow and its dashboard are the same project
 * under two routes: a viewer given either link can reach the other, and the two
 * bars must not drift over what "share this" means.
 *
 * Both links are ordinary URLs into this app. A dataflow link opens the canvas,
 * read-only for anyone but the owner; a dashboard link opens the pinned tiles,
 * and the owner's lets whoever opens it run them (`copyDashboardLink`).
 */
export function ShareMenu({
  id,
  includeOpenDashboard,
  open,
  onToggle,
  onClose,
  projectDirty = false,
  canPublish = false,
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

  /**
   * The dashboard link. The owner's lets whoever opens it run the dashboard:
   * copying it publishes the dataflow as it is saved now, under a link token
   * that stays the same from one copy to the next. A dataflow that cannot be
   * published yet (nothing pinned, code that saves files) gets the plain link,
   * and says why. A visitor on a run link passes that link on.
   */
  const copyDashboardLink = async () => {
    if (!id || !canPublish) {
      const token = publishLinkToken();
      await copy(token ? runLink(dashboardUrl, token) : dashboardUrl, "dashboard link", "Dashboard link copied.");
      return;
    }
    onClose();
    let token: string | null = null;
    let refusal: string | null = null;
    try {
      token = (await publishedApi.publish(id, "link")).token;
    } catch (err: any) {
      refusal = err?.message || "The dashboard could not be published.";
    }
    const copied = await copyText(token ? runLink(dashboardUrl, token) : dashboardUrl, "dashboard link");
    if (!copied) {
      showToast("Could not copy the dashboard link.", "error");
    } else if (token) {
      showToast(projectDirty ? `${RUN_LINK_COPIED} ${STALE_DASHBOARD_MESSAGE}` : RUN_LINK_COPIED, "success");
    } else {
      showToast(`Dashboard link copied, for viewing only: ${refusal}`, "info");
    }
  };

  return (
    <HeaderMenu label="Share" open={open} onToggle={onToggle} onClose={onClose} testId="share-menu-btn">
      {includeOpenDashboard && (
        // A real anchor, not a navigate: the dashboard opens in its own tab so
        // the dataflow the user is editing stays where it is, and a
        // user-initiated link is never caught by a popup blocker.
        <a
          className={menuStyles.item}
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
            // Pins and tile geometry live in the spec, so an unsaved edit is
            // not in the page about to open.
            if (projectDirty) showToast(STALE_DASHBOARD_MESSAGE, "info");
          }}
        >
          <FontAwesomeIcon className={menuStyles.itemIcon} icon={faTableColumns} />
          <span>Open dashboard</span>
        </a>
      )}
      <HeaderMenuItem
        icon={faLink}
        onClick={() => void copyDashboardLink()}
      >
        Copy dashboard link
      </HeaderMenuItem>
      <HeaderMenuItem
        icon={faLink}
        onClick={() => void copy(dataflowUrl, "dataflow link", "Dataflow link copied.")}
      >
        Copy dataflow link
      </HeaderMenuItem>
    </HeaderMenu>
  );
}

export default ShareMenu;
