/**
 * The steps a dashboard viewer's run leaves to the page (#1117): nodes only a
 * browser runs, such as an Autark compute node or a Spatial Join. While the
 * page runs one for the run, the node's result goes to the run, which keeps it
 * for this page alone (`runs/viewer.py`), and not where a signed-in canvas
 * saves it: a viewer has no session to save it with.
 */
import { dashboardRunsApi } from "./dashboardRunsApi";
import { rememberDashboardRunFiles } from "./dashboardRunFiles";

interface Asked {
  projectId: string;
  runId: string;
  token: string;
  nodeIds: Set<string>;
}

let asked: Asked | null = null;

/** The run *runId* leaves *nodeIds* to this page. */
export function askPage(projectId: string, runId: string, token: string, nodeIds: Iterable<string>): void {
  asked = { projectId, runId, token, nodeIds: new Set(nodeIds) };
}

/** No step is this page's to run for a viewer's run any more. */
export function forgetPageSteps(): void {
  asked = null;
}

/** Whether a viewer's run asked this page to run *nodeId*. */
export function askedOfPage(nodeId: string): boolean {
  return !!asked && asked.nodeIds.has(nodeId);
}

/**
 * Send what the page made of *nodeId* to the run that asked for it. The
 * output it answers is read, as the run's other outputs are, on the
 * dashboard's own routes with the run's token.
 */
export async function keepPageResult(nodeId: string, value: unknown): Promise<{ path: string; dataType: string }> {
  const run = asked;
  if (!run || !run.nodeIds.has(nodeId)) {
    throw new Error("No run of this dashboard asked the page for this node.");
  }
  const kept = await dashboardRunsApi.keepStep(run.projectId, run.runId, run.token, nodeId, value);
  rememberDashboardRunFiles(run.projectId, run.token, [kept.output.path, ...(kept.artifactIds ?? [])]);
  return kept.output;
}
