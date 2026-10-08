import React, { useCallback, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { NodePositionChange } from "reactflow";
import clsx from "clsx";

import { LEAVE_DASHBOARD, useLeaveGuard } from "../../hook/useLeaveGuard";
import ShareMenu from "../../components/menus/top/ShareMenu";
import { GlobalPageHeader } from "../../components/layout/GlobalPageHeader";
import { useFlowContext, useNodeActionsContext } from "../../providers/FlowProvider";
import { useToastContext } from "../../providers/ToastProvider";
import { useUserContext } from "../../providers/UserProvider";
import { isHostedGuest } from "../../components/apiSettings/useHostedGuest";
import { dashboardRefusal } from "../../standalone/dashboardPayload";
import { arrangedTilePositions } from "../../utils/dashboardLayout";
import { scenarioDashboard } from "../../utils/scenarios/scenarioDashboard";
import { dataflowPath } from "../../utils/shareLinks";
import headerStyles from "../../components/layout/GlobalPageHeader.module.css";
import styles from "./DashboardTopBar.module.css";

/**
 * May this viewer move the tiles?
 *
 * The owner of a saved dataflow, and not a hosted guest (``isHostedGuest``). A
 * visitor on a share link is ``viewerMode === "shared"`` and saving would throw;
 * a hosted guest is refused by the same rule on the canvas (``blockGuestSaves``),
 * so offering the control would only produce an error toast.
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
    && !isHostedGuest(user, enableUserAuth)
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
 * links, and, for the owner, the controls that move tiles around. None of
 * the editor's menus are here. There is no palette to drop nodes from, nothing
 * to run, no catalogs, and no save status, because a dashboard is not edited
 * except by explicitly saving a layout.
 *
 * *onArranged* is told when Arrange by scenario has moved the tiles, so the
 * page can frame them again.
 */
export function DashboardTopBar({ id, onArranged }: { id: string; onArranged?: () => void }) {
  const navigate = useNavigate();
  const { showToast } = useToastContext();
  const { workflowName } = useNodeActionsContext();
  const {
    projectName,
    projectDirty,
    dashboardLocked,
    setDashboardLocked,
    saveCurrentProject,
    nodes,
    edges,
    dashboardPins,
    scenarios,
    onNodesChange,
    updateDataNode,
    markDirty,
  } = useFlowContext();
  const canEditLayout = useCanEditLayout();
  // A page the server refused to build carries nothing to open the dataflow
  // with, so its link loads the dataflow as a page of its own.
  const refused = dashboardRefusal() !== null;

  // Arrange by scenario (#662): offered while a pinned tile is in a scenario.
  const byScenario = useMemo(
    () => scenarioDashboard(nodes ?? [], edges ?? [], dashboardPins ?? {}, scenarios ?? []),
    [nodes, edges, dashboardPins, scenarios],
  );
  const arrangeByScenario = () => {
    if (!byScenario) return;
    const positions = arrangedTilePositions(nodes, dashboardPins, byScenario.columns);
    const moves: NodePositionChange[] = [...positions].map(([nodeId, position]) => ({
      type: "position",
      id: nodeId,
      position,
    }));
    onNodesChange(moves);
    // The slots a Save layout writes, as a drag records them.
    for (const [nodeId, position] of positions) {
      const live = nodes.find((node) => node.id === nodeId)?.data;
      updateDataNode(nodeId, { ...live, dashboardX: position.x, dashboardY: position.y });
    }
    markDirty();
    onArranged?.();
  };

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
          reloadDocument={refused}
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
        {canEditLayout && !dashboardLocked && byScenario && (
          <button
            type="button"
            className={headerStyles.barButton}
            onClick={arrangeByScenario}
            data-testid="arrange-by-scenario-btn"
          >
            Arrange by scenario
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
