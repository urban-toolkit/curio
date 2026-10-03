import React, { useCallback, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import clsx from "clsx";

import { LEAVE_DASHBOARD, useLeaveGuard } from "../../hook/useLeaveGuard";
import ShareMenu from "../../components/menus/top/ShareMenu";
import { GlobalPageHeader } from "../../components/layout/GlobalPageHeader";
import { useFlowContext, useNodeActionsContext } from "../../providers/FlowProvider";
import { useToastContext } from "../../providers/ToastProvider";
import { useUserContext } from "../../providers/UserProvider";
import { dataflowPath } from "../../utils/shareLinks";
import headerStyles from "../../components/layout/GlobalPageHeader.module.css";
import styles from "./DashboardTopBar.module.css";

/**
 * May this viewer move the tiles?
 *
 * The owner of a saved dataflow, and not a guest account under auth. A visitor
 * on a share link is ``viewerMode === "shared"`` and saving would throw; a guest
 * is refused by the rule the canvas already applies (``blockGuestSaves``), so
 * offering the control would only produce an error toast.
 *
 * Exported because the page reads it too: whoever cannot edit is told the
 * dashboard is read-only.
 */
export function useCanEditLayout(): boolean {
  const { user, enableUserAuth } = useUserContext();
  const { viewerMode, projectId } = useFlowContext();
  return (
    viewerMode === "owner"
    && !!projectId
    && !(enableUserAuth && user?.is_guest)
  );
}

/** The dashboard's leave guard: the layout is unsaved work only while it is
 *  unlocked for editing. Shared by the top bar and the empty state. */
export function useDashboardLeaveGuard() {
  const { projectDirty, dashboardLocked } = useFlowContext();
  return useLeaveGuard(projectDirty && !dashboardLocked, LEAVE_DASHBOARD);
}

/**
 * The dashboard's own top bar.
 *
 * The same GlobalPageHeader every other page wears, so the dashboard reads as
 * the same product. What it puts in the bar is deliberately almost nothing,
 * because the page is the content: a way back to the dataflow, the share
 * links, and, for the owner, the two controls that move tiles around. None of
 * the editor's menus are here. There is no palette to drop nodes from, nothing
 * to run, no catalogs, and no save status, because a dashboard is not edited
 * except by explicitly saving a layout.
 */
export function DashboardTopBar({ id }: { id: string }) {
  const navigate = useNavigate();
  const { showToast } = useToastContext();
  const { workflowName } = useNodeActionsContext();
  const {
    projectName,
    projectDirty,
    dashboardLocked,
    setDashboardLocked,
    saveCurrentProject,
  } = useFlowContext();
  const canEditLayout = useCanEditLayout();

  const [shareOpen, setShareOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  // The menu closes itself on a click anywhere else or on Escape.
  const closeShare = useCallback(() => setShareOpen(false), []);

  // Unsaved tile geometry is real work: warn before dropping it.
  const { leave, dialog: leaveDialog } = useDashboardLeaveGuard();

  const saveLayout = async () => {
    setSaving(true);
    try {
      // ``omitOutputs``: this page writes where the tiles sit. Which outputs the
      // dataflow has is the canvas's business, and nothing here ran.
      await saveCurrentProject(undefined, { omitOutputs: true });
      setDashboardLocked(true);
      showToast("Dashboard layout saved.", "success");
    } catch (err) {
      showToast((err as Error)?.message || "Could not save the layout.", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <GlobalPageHeader className={clsx(styles.bar, "nowheel", "nodrag")} onLeave={(go) => leave(go)}>
        <h1 className={styles.title} title={projectName || workflowName}>
          {projectName || workflowName}
        </h1>

        <Link
          className={headerStyles.barButton}
          to={dataflowPath(id)}
          data-testid="open-dataflow-link"
          onClick={(event) => {
            if (projectDirty && !dashboardLocked) {
              event.preventDefault();
              leave(() => navigate(dataflowPath(id)));
            }
          }}
        >
          Open dataflow
        </Link>

        <ShareMenu
          id={id}
          includeOpenDashboard={false}
          open={shareOpen}
          onToggle={() => setShareOpen((open) => !open)}
          onClose={closeShare}
        />

        {canEditLayout && (
          <button
            type="button"
            className={clsx(headerStyles.barButton, !dashboardLocked && headerStyles.barButtonActive)}
            aria-pressed={!dashboardLocked}
            onClick={() => setDashboardLocked(!dashboardLocked)}
            data-testid="edit-layout-btn"
          >
            {dashboardLocked ? "Edit layout" : "Editing layout"}
          </button>
        )}
        {canEditLayout && !dashboardLocked && (
          <button
            type="button"
            className={headerStyles.barButton}
            disabled={saving}
            onClick={() => void saveLayout()}
            data-testid="save-layout-btn"
          >
            {saving ? "Saving..." : "Save layout"}
          </button>
        )}
      </GlobalPageHeader>

      {leaveDialog}
    </>
  );
}

export default DashboardTopBar;
