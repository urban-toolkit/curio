import React, { useCallback, useEffect, useMemo, useRef } from "react";
import { Link, useParams } from "react-router-dom";
import ReactFlow, {
  ConnectionMode,
  EdgeChange,
  FitViewOptions,
  NodeChange,
  useReactFlow,
} from "reactflow";

import { CURIO_UNIVERSAL_NODE_TYPE, EdgeType } from "../../constants";
import UniversalNode from "../../components/UniversalNode";
import BiDirectionalEdge from "../../components/edges/BiDirectionalEdge";
import UniDirectionalEdge from "../../components/edges/UniDirectionalEdge";
import VersionBadge from "../../components/VersionBadge";
import { Loading } from "../../components/login/Loading";
import { useProjectLoadState } from "../../components/ProjectLoader";
import { useFlowContext } from "../../providers/FlowProvider";
import { fitViewWithMenuOffset } from "../../utils/fitViewWithMenuOffset";
import { dataflowPath } from "../../utils/shareLinks";
import DashboardTopBar, { useCanEditLayout } from "./DashboardTopBar";
import { DASHBOARD_FIT_OPTIONS, useDashboardFit } from "./useDashboardFit";
import styles from "./DashboardPage.module.css";
import "reactflow/dist/style.css";
import "../../components/MainCanvas.css";

export const NOTHING_PINNED_TITLE = "Nothing is pinned to this dashboard yet.";
export const NOTHING_PINNED_BODY =
  "Open the dataflow and use Pin to dashboard on the nodes you want to show here.";
export const READ_ONLY_NOTICE =
  "Viewing a shared dashboard (read-only). Open the dataflow to make a copy.";
export const LOAD_FAILED_TITLE = "This dashboard could not be opened.";
export const LOAD_FAILED_BODY =
  "It may have been deleted, or the link may not be shared with you.";
export const STALE_TILES_HINT =
  "Tiles render from the outputs saved to the Data Catalog. Run the dataflow and save it to refresh them.";

/**
 * A dataflow's pinned nodes, as a page of their own.
 *
 * It mounts its own React Flow rather than a grid of divs, because that is what
 * the node components are: their behaviours read the graph through React Flow's
 * hooks, and the chain that feeds a tile (a Merge, a Data Pool) is made of nodes
 * that have to be mounted to do their work. So every node is here. The unpinned
 * ones are laid out invisibly by ``prepareDashboardNodes``, which is also what
 * decides where the tiles sit.
 *
 * Nothing on this page runs a dataflow. Tiles draw from the outputs a run
 * already saved, restored by ``ProjectLoader``; a chart compiles its spec
 * against them (``UniversalNode``'s auto-render effect).
 */
export const DashboardPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    dashboardPins,
    dashboardLocked,
    updateDataNode,
    markDirty,
  } = useFlowContext();
  const loadState = useProjectLoadState();
  const canEditLayout = useCanEditLayout();
  const reactFlow = useReactFlow();
  const canvasRef = useRef<HTMLDivElement>(null);

  const pinnedIds = useMemo(
    () => nodes.filter((node) => dashboardPins[node.id]).map((node) => node.id),
    [nodes, dashboardPins],
  );
  useDashboardFit(pinnedIds, canvasRef);

  const nodeTypes = useMemo(() => ({ [CURIO_UNIVERSAL_NODE_TYPE]: UniversalNode }), []);
  const edgeTypes = useMemo(() => ({
    [EdgeType.BIDIRECTIONAL_EDGE]: BiDirectionalEdge,
    [EdgeType.UNIDIRECTIONAL_EDGE]: UniDirectionalEdge,
  }), []);

  // The same test hooks the canvas exposes, so the Playwright helpers that read
  // the graph work on this page too. The fit frames the tiles exactly as the
  // page itself does, whatever padding the caller asks for, so a screenshot
  // shows the dashboard a visitor sees. It is scoped to the visible tiles:
  // handed no nodes, the helper would fall back to all of them and wait on
  // dimensions the hidden ones never get.
  useEffect(() => {
    (window as any).__curio_reactFlow = reactFlow;
    (window as any).__curio_fitViewWithMenuOffset = (_options?: FitViewOptions) => {
      const tiles = reactFlow.getNodes().filter((node) => node.style?.display !== "none");
      if (tiles.length === 0) return false;
      return fitViewWithMenuOffset(reactFlow, { ...DASHBOARD_FIT_OPTIONS, nodes: tiles });
    };
    return () => {
      if ((window as any).__curio_reactFlow === reactFlow) {
        delete (window as any).__curio_reactFlow;
        delete (window as any).__curio_fitViewWithMenuOffset;
      }
    };
  }, [reactFlow]);

  /**
   * Tile moves, and nothing else.
   *
   * Removals are dropped: React Flow deletes a selected node on Backspace, and
   * the provider's handler would apply it, so a stray keypress on a dashboard
   * would delete a node out of the dataflow. ``deleteKeyCode={null}`` below
   * covers the keyboard; this covers everything else that can ask.
   */
  const handleNodesChange = useCallback((changes: NodeChange[]) => {
    const allowed = changes.filter((change) => change.type !== "remove");
    if (allowed.some((change) => change.type === "position" && change.position)) {
      markDirty();
    }
    onNodesChange(allowed);
  }, [onNodesChange, markDirty]);

  const handleEdgesChange = useCallback((changes: EdgeChange[]) => {
    onEdgesChange(changes.filter((change) => change.type !== "remove"));
  }, [onEdgesChange]);

  /** Where the user dropped the tile, into the field the spec persists. */
  const handleNodeDragStop = useCallback((_event: React.MouseEvent, node: any) => {
    const live = reactFlow.getNode(node.id)?.data ?? node.data;
    updateDataNode(node.id, {
      ...live,
      dashboardX: node.position.x,
      dashboardY: node.position.y,
    });
  }, [reactFlow, updateDataNode]);

  const dataflowLink = id ? dataflowPath(id) : "/projects";

  return (
    <div className={styles.page}>
      {id ? <DashboardTopBar id={id} /> : null}
      {loadState === "loaded" && !canEditLayout ? (
        // The notice the canvas gives a visitor, for the same reason: the page
        // looks editable (tiles, a Share menu) and is not.
        <div className={styles.banner} data-testid="shared-view-banner">
          {READ_ONLY_NOTICE}
        </div>
      ) : null}
      <div className={styles.canvas} ref={canvasRef}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={handleNodesChange}
          onEdgesChange={handleEdgesChange}
          onNodeDragStop={handleNodeDragStop}
          connectionMode={ConnectionMode.Loose}
          nodesDraggable={!dashboardLocked}
          nodesConnectable={false}
          elementsSelectable={!dashboardLocked}
          panOnDrag={!dashboardLocked}
          zoomOnScroll={!dashboardLocked}
          zoomOnPinch={!dashboardLocked}
          zoomOnDoubleClick={false}
          selectionKeyCode={null}
          multiSelectionKeyCode={null}
          // A dashboard has nothing to delete.
          deleteKeyCode={null}
          minZoom={0.05}
          // Never enlarge a tile past the size it was authored at.
          maxZoom={1}
          proOptions={{ hideAttribution: false }}
        />
        {loadState === "loading" || loadState === "idle" ? (
          <div className={styles.state}>
            <Loading />
          </div>
        ) : null}
        {loadState === "failed" ? (
          <div className={styles.state} data-testid="dashboard-load-failed">
            <span className={styles.stateTitle}>{LOAD_FAILED_TITLE}</span>
            <span>{LOAD_FAILED_BODY}</span>
          </div>
        ) : null}
        {loadState === "loaded" && pinnedIds.length === 0 ? (
          <div className={styles.state} data-testid="dashboard-empty">
            <span className={styles.stateTitle}>{NOTHING_PINNED_TITLE}</span>
            <span>{NOTHING_PINNED_BODY}</span>
            <Link className={styles.stateLink} to={dataflowLink}>
              Open the dataflow
            </Link>
          </div>
        ) : null}
      </div>
      <VersionBadge />
    </div>
  );
};

export default DashboardPage;
