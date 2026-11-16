/**
 * The headers of every request a page sends the backend, and the query of
 * its room's socket's handshake: the session's token, and the dataflow the
 * page shows. A start of several backend processes (`curio.py start
 * --backend-processes N`) sends each request and socket to the process that
 * owns that dataflow (`cli/backend_group.py`), where its room, its doc, its
 * runs and its agents are kept, a request whose path names no dataflow too:
 * a run's `/api/runs/<run>`, `/processPythonCode`, `/storeOutput`,
 * `/nodeRuntime`. With one process the header changes nothing.
 *
 * The page's dataflow is the one its route names, the canvas's
 * (`/dataflow/<id>`) or the dashboard's (`/dashboard/<id>`), even while the
 * canvas still holds the dataflow before it. For a hosted guest that is the
 * dataflow the page shows, never the id of its own copy, which only the room's
 * events name (`CollaborationProvider`): the server keeps a guest's copy with
 * the dataflow it copies. On `/dataflow/new` it is the id a new dataflow gets
 * on its first save, the one its reads are on (`services/dataflowReads.ts`).
 * Any other page names none: the projects, a catalog, the monitor.
 *
 * Every client writes the token's header here and nowhere else
 * (`tests/utils/authorizationHeaderByHand.test.ts`), so none sends the
 * session's token without the dataflow.
 */
import route from "../contracts/dataflowRoute.json";
import { openDataflowId } from "../services/dataflowReads";
import { basePath } from "./basePath";
import { sharedDataflowOf } from "./shareLinks";

/** The header a request names its dataflow in, which the router reads. */
export const DATAFLOW_HEADER: string = route.header;
/** The query argument a socket's handshake names its dataflow in. */
export const DATAFLOW_QUERY: string = route.query;

/** The page's route: its pathname without the app's base path. */
function pageRoute(): string {
  const pathname = window.location.pathname;
  const base = basePath();
  return base && pathname.startsWith(base) ? pathname.slice(base.length) || "/" : pathname;
}

/** The dataflow the page shows, or null on a page that shows none. */
export function pageDataflow(): string | null {
  if (typeof window === "undefined") return null;
  const page = pageRoute();
  const routed = sharedDataflowOf(page);
  if (routed) return routed;
  return /^\/dataflow(?:\/|$)/.test(page) ? openDataflowId() : null;
}

/**
 * *headers*, with the session's *token* and the dataflow the request names:
 * *dataflow*, for a request that names its own in its path, its body or its
 * query, as a run of another dataflow does, else the page's. A header with
 * nothing to say is left out.
 */
export function requestHeaders(
  token: string | null | undefined,
  headers: Record<string, string> = {},
  dataflow?: string | null,
): Record<string, string> {
  const named = dataflow || pageDataflow();
  return {
    ...headers,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(named ? { [DATAFLOW_HEADER]: named } : {}),
  };
}

/** The query of the handshake of the room's socket of *dataflow*. */
export function socketQuery(dataflow: string): Record<string, string> {
  return { [DATAFLOW_QUERY]: dataflow };
}
