import { useSyncExternalStore } from "react";

import { getCurrentProjectId, subscribe } from "../../registry/projectPackagesStore";
import { agentsDataflowId } from "../../services/agents";
import { useCollab } from "../CollaborationProvider";
import { canvasRole } from "../collab/participants";
import { useFlowContext } from "../FlowProvider";

/**
 * The dataflow whose agents this canvas drives (`agentsDataflowId`), for every
 * agent surface: the dock and its chats, a drop on the canvas, the agents
 * palette and the Agent Catalog drawer. On the owner's canvas it is the one the
 * flow state saves. On an invited editor's it is the one the route opened
 * (`projectPackagesStore`), since a tab on another account's dataflow saves none
 * and its `projectId` is null. Null on a watcher's canvas and on one never saved.
 */
export function useAgentsDataflowId(): string | null {
  const { projectId, viewerMode } = useFlowContext();
  const collab = useCollab();
  const opened = useSyncExternalStore(subscribe, getCurrentProjectId);
  return agentsDataflowId(canvasRole(viewerMode, collab), projectId, opened);
}
