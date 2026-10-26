/**
 * The file a node's output names, to download: a Data Export node's.
 *
 * Asked by the output's artifact id at `/output-file` (backend
 * `api/routes.py`), which the sandbox answers only for a file in the folder of
 * the run that made the output. An output a dashboard viewer's run made is
 * read on its dashboard's route (`runs/dashboardRunFiles.ts`).
 */
import { getToken } from "../utils/authApi";
import { backendUrl } from "../utils/backendUrl";
import { dashboardRunRead } from "./runs/dashboardRunFiles";

export type FetchedOutputFile =
  | { ok: true; blob: Blob }
  | { ok: false; status: number; message: string };

export async function fetchOutputFile(fileName: string): Promise<FetchedOutputFile> {
  const params = new URLSearchParams({ fileName });
  const dashboard = dashboardRunRead(fileName, "output-file", params);
  const url = dashboard?.url ?? `${backendUrl()}/output-file?${params.toString()}`;
  const token = getToken();
  const response = await fetch(url, {
    headers: {
      ...(dashboard?.headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body?.message === "string" && body.message) message = body.message;
    } catch {
      // A body that is not JSON says no more than its status.
    }
    return { ok: false, status: response.status, message };
  }
  return { ok: true, blob: await response.blob() };
}
