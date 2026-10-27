/**
 * The artifacts a dashboard viewer's runs made (#1117), and where the page
 * reads them: the dashboard's own output routes (`runs/viewer_routes.py`),
 * which read each in the session its kept output was made in. The plain
 * `/get` reads the caller's own session, and a viewer has none.
 *
 * `fetchData`, `fetchPreviewData` and `fetchRaster` (`services/api.ts`) ask
 * here after the page's embedded outputs, so every reader of an artifact finds
 * them, and so does `fetchOutputFile` (`services/outputFiles.ts`).
 */
import { backendUrl } from "../../utils/backendUrl";
import { RUN_TOKEN_HEADER } from "./dashboardRunsApi";

export type DashboardRead = "get" | "get-preview" | "raster" | "output-file";

interface Remembered {
  projectId: string;
  token: string | null;
}

const files = new Map<string, Remembered>();

/** The artifacts of a step's output, read on *projectId*'s dashboard from now on. */
export function rememberDashboardRunFiles(
  projectId: string,
  token: string | null,
  fileNames: readonly (string | null | undefined)[],
): void {
  for (const fileName of fileNames) {
    if (fileName) files.set(fileName, { projectId, token });
  }
}

/** Forget them all: the page went away, or a test starts over. */
export function forgetDashboardRunFiles(): void {
  files.clear();
}

/**
 * Where *fileName* is read, when a dashboard viewer's run made it: the route's
 * address with *query* (its `fileName` included) and the headers to send.
 * Undefined for any other artifact.
 */
export function dashboardRunRead(
  fileName: string,
  read: DashboardRead,
  query: URLSearchParams,
): { url: string; headers: Record<string, string> } | undefined {
  const remembered = files.get(fileName);
  if (!remembered) return undefined;
  const path = `/api/projects/${encodeURIComponent(remembered.projectId)}/dashboard/outputs/${read}`;
  return {
    url: `${backendUrl()}${path}?${query.toString()}`,
    headers: remembered.token ? { [RUN_TOKEN_HEADER]: remembered.token } : {},
  };
}
