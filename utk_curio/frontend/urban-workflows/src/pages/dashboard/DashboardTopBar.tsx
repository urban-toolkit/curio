import React, { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import clsx from "clsx";

import logo from "assets/curio-2.png";
import { LEAVE_DASHBOARD, useLeaveGuard } from "../../hook/useLeaveGuard";
import ShareMenu from "../../components/menus/top/ShareMenu";
import { UserMenu } from "../../components/login/UserMenu";
import { useFlowContext, useNodeActionsContext } from "../../providers/FlowProvider";
import { useToastContext } from "../../providers/ToastProvider";
import { useUserContext } from "../../providers/UserProvider";
import { dataflowPath } from "../../utils/shareLinks";
import barStyles from "../../components/menus/top/UpMenu.module.css";
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
 * Built from the dataflow bar's stylesheet on purpose: this is the same product,
 * so the two bars look like each other. What it holds is deliberately almost
 * nothing, because the page is the content: a way back to the dataflow, the
 * share links, and, for the owner, the two controls that move tiles around.
 * None of the editor's menus are here. There is no palette to drop nodes from,
 * nothing to run, and no save status, because a dashboard is not edited except
 * by explicitly saving a layout.
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
  const barRef = useRef<HTMLDivElement>(null);

  // Close the menu on a click anywhere else, as the dataflow bar does.
  useEffect(() => {
    if (!shareOpen) return;
    const onClick = (event: MouseEvent) => {
      if (barRef.current && !barRef.current.contains(event.target as Node)) {
        setShareOpen(false);
      }
    };
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, [shareOpen]);

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
      <div className={clsx(barStyles.menuBar, "nowheel", "nodrag")} ref={barRef}>
        <img
          className={barStyles.logo}
          src={logo}
          alt="Curio"
          onClick={() => leave(() => navigate("/projects"))}
        />

        <Link
          className={barStyles.button}
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
          onClose={() => setShareOpen(false)}
        />

        {canEditLayout && (
          <button
            className={clsx(barStyles.button, !dashboardLocked && styles.buttonActive)}
            onClick={() => setDashboardLocked(!dashboardLocked)}
            data-testid="edit-layout-btn"
          >
            {dashboardLocked ? "Edit layout" : "Editing layout"}
          </button>
        )}
        {canEditLayout && !dashboardLocked && (
          <button
            className={barStyles.button}
            disabled={saving}
            onClick={() => void saveLayout()}
            data-testid="save-layout-btn"
          >
            {saving ? "Saving..." : "Save layout"}
          </button>
        )}

        <h1 className={styles.title} title={projectName || workflowName}>
          {projectName || workflowName}
        </h1>

        <UserMenu />
      </div>

      {leaveDialog}
    </>
  );
}

export default DashboardTopBar;
