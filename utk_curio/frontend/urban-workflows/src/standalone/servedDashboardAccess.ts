/**
 * May this browser's session edit the layout of the dashboard the page was
 * served with?
 *
 * A page served with its data has no session of its own and names no account,
 * so it cannot tell its owner from a viewer by itself. A browser that holds a
 * session asks the backend once (`GET /api/projects/<id>/dashboard/can-edit`),
 * which answers yes or no by the gate a save of the layout passes. On a yes the
 * page becomes the owner's: UserProvider learns who is signed in and
 * ProjectLoader loads the dataflow, as a page that fetches does, so Edit
 * layout, Save layout and Arrange work. Anything else is a no, and asks nothing
 * more: no session, a page the server refused to build (which asks for
 * nothing), a failed answer, or one slower than `ANSWER_TIMEOUT_MS`, past which
 * the page opens read-only, as it must where its server cannot be reached.
 */
import { apiFetch, clearToken, getToken, isUnauthorized } from "../utils/authApi";
import { EmbeddedDashboard, getEmbeddedDashboard } from "./dashboardPayload";

/** How long the page waits for the answer before it opens read-only. */
export const ANSWER_TIMEOUT_MS = 5000;

let askedFor: EmbeddedDashboard | null | undefined;
let answer: Promise<boolean> = Promise.resolve(false);

/** The answer for this page, asked once however many callers want it. */
export function mayEditServedDashboard(): Promise<boolean> {
  const payload = getEmbeddedDashboard();
  if (payload !== askedFor) {
    askedFor = payload;
    answer = ask(payload);
  }
  return answer;
}

async function ask(payload: EmbeddedDashboard | null): Promise<boolean> {
  const projectId = payload?.meta?.projectId;
  if (!payload || payload.refused || !projectId || !getToken()) return false;
  const asked = apiFetch<{ canEdit?: boolean }>(
    `/api/projects/${encodeURIComponent(projectId)}/dashboard/can-edit`,
  ).then(
    (body) => body?.canEdit === true,
    (err) => {
      // Only a 401 ends the session, as on any page.
      if (isUnauthorized(err)) clearToken();
      return false;
    },
  );
  let timer: ReturnType<typeof setTimeout> | undefined;
  const late = new Promise<boolean>((resolve) => {
    timer = setTimeout(() => resolve(false), ANSWER_TIMEOUT_MS);
  });
  try {
    return await Promise.race([asked, late]);
  } finally {
    clearTimeout(timer);
  }
}
