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
 * canvas still holds the dataflow before it. On `/dataflow/new` it is the id a
 * new dataflow gets on its first save, the one its reads are on
 * (`services/dataflowReads.ts`). Any other page names none: the projects, a
 * catalog, the monitor.
 *
 * A hosted guest's canvas of a dataflow its account owns, an example, works
 * on the guest's own copy of it, which the server keeps on the process the
 * copy's own id names (`collaboration/owner_guard.py`). The canvas's load of
 * the dataflow answers with that id (`copy_id`, `nameDataflow`), and from then
 * on the canvas names the copy wherever it would name the dataflow: in every
 * request's header, a request that names the dataflow itself included, and in
 * its room's socket's query. Until that answer the canvas names the dataflow,
 * on the reads of its load, which any process answers, and its room's socket
 * waits for it: `ProjectLoader` marks a hosted guest's load
 * (`awaitDataflowName`), and the socket opens once the name is known
 * (`dataflowNameKnown`). An account's load is not marked, as its answer names
 * no copy: its socket opens at once, apart from the load. The guest's
 * dashboard of the dataflow names the copy the same way, once its load
 * answers with the copy's id, or, on a page served with its data, once
 * `ProjectLoader` reads it there: its viewer runs are kept on the copy's
 * process. Ids in paths and bodies are the dataflow's. A request sent once
 * the page has left the canvas or the dashboard, a node's outcome as its
 * canvas closes, names the dataflow itself: the record it writes is a file
 * beside the copy, which any process writes.
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

/** A canvas's route: `/dataflow/<id>`, `/dataflow/new` or `/dataflow`. */
const CANVAS_ROUTE = /^\/dataflow(?:\/|$)/;
/** A dashboard's route: `/dashboard/<id>`. */
const DASHBOARD_ROUTE = /^\/dashboard\//;

/** The page's route: its pathname without the app's base path. */
function pageRoute(): string {
  const pathname = window.location.pathname;
  const base = basePath();
  return base && pathname.startsWith(base) ? pathname.slice(base.length) || "/" : pathname;
}

/** Whether the page shows a dataflow it loaded: a canvas or a dashboard. */
function showsADataflow(): boolean {
  if (typeof window === "undefined") return false;
  const page = pageRoute();
  return CANVAS_ROUTE.test(page) || DASHBOARD_ROUTE.test(page);
}

/** The dataflow the page shows, or null on a page that shows none. */
export function pageDataflow(): string | null {
  if (typeof window === "undefined") return null;
  const page = pageRoute();
  const routed = sharedDataflowOf(page);
  if (routed) return routed;
  return CANVAS_ROUTE.test(page) ? openDataflowId() : null;
}

/** Each dataflow a canvas or a dashboard loaded whose load, or whose page's
 *  data, answered with a hosted guest's own copy of it, and that copy's id. */
const copies = new Map<string, string>();
/** The dataflow whose load the canvas waits on for the id it names it by. */
let awaited: string | null = null;
const listeners = new Set<() => void>();

function changed(): void {
  for (const listener of listeners) {
    try {
      listener();
    } catch {
      // One listener's failure must not keep the others from hearing.
    }
  }
}

/**
 * A hosted guest's canvas starts loading *dataflow* (`ProjectLoader`): until
 * the load answers with the id the dataflow is named by (`nameDataflow`), or
 * ends (`releaseDataflowName`), its room's socket waits (`dataflowNameKnown`).
 * What the page already knew of the dataflow's name stays meanwhile.
 */
export function awaitDataflowName(dataflow: string): void {
  if (awaited === dataflow) return;
  awaited = dataflow;
  changed();
}

/**
 * The load of *dataflow* answered, or a dashboard's page read the data it
 * was served with: from now on the canvas or the dashboard names it *copy*, a
 * hosted guest's own copy of it, or, with none, the dataflow itself.
 */
export function nameDataflow(dataflow: string, copy?: string | null): void {
  const before = copies.get(dataflow);
  if (copy) copies.set(dataflow, copy);
  else copies.delete(dataflow);
  const waited = awaited === dataflow;
  if (waited) awaited = null;
  if (waited || before !== (copy || undefined)) changed();
}

/** The load of *dataflow* ended without naming it, or the page left it: its
 *  socket waits no more, and names what the page knew of it. */
export function releaseDataflowName(dataflow: string): void {
  if (awaited !== dataflow) return;
  awaited = null;
  changed();
}

/** Whether the canvas knows the id *dataflow* is named by: no load of it is
 *  in flight whose answer may name a copy. */
export function dataflowNameKnown(dataflow: string): boolean {
  return awaited !== dataflow;
}

/** Hear every change to the ids the canvas names its dataflows by. */
export function subscribeDataflowNames(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Forget every dataflow's name, as a page that starts: for tests. */
export function resetDataflowNames(): void {
  copies.clear();
  awaited = null;
}

/**
 * The id a request or a socket about *dataflow* names it by: on a canvas or a
 * dashboard, a hosted guest's own copy of it once the page's load of it, or
 * the data its page was served with, answered with one, else *dataflow*
 * itself.
 */
export function dataflowName(dataflow: string): string {
  return (showsADataflow() && copies.get(dataflow)) || dataflow;
}

/**
 * *headers*, with the session's *token* and the dataflow the request names:
 * *dataflow*, for a request that names its own in its path, its body or its
 * query, as a run of another dataflow does, else the page's, each by the id
 * the page names it by (`dataflowName`). A header with nothing to say is
 * left out.
 */
export function requestHeaders(
  token: string | null | undefined,
  headers: Record<string, string> = {},
  dataflow?: string | null,
): Record<string, string> {
  const shown = dataflow || pageDataflow();
  const named = shown ? dataflowName(shown) : null;
  return {
    ...headers,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(named ? { [DATAFLOW_HEADER]: named } : {}),
  };
}

/** The query of the handshake of the room's socket of *dataflow*, by the id
 *  the page names it by (`dataflowName`). */
export function socketQuery(dataflow: string): Record<string, string> {
  return { [DATAFLOW_QUERY]: dataflowName(dataflow) };
}
