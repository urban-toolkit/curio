/**
 * The open dataflow's Yjs doc on this tab, as `CollaborationProvider` holds
 * it: null while the canvas is not bound to it (a dataflow never saved, a
 * hosted guest's own canvas, no sign-in, the dashboard), and before the room
 * has joined the tab.
 *
 * Its own context, beside `useCollab`'s, so a component reads the doc without
 * every test's mock of the collaboration context having to name it.
 */
import { createContext, useContext } from "react";

import type { DataflowDocProvider } from "./docProvider";

/** The origin of this tab's changes to the doc made from the canvas
 *  (`useDataflowDoc`'s writer, an editor's first code). y-monaco's typing has
 *  its binding as origin, and the server's updates the provider. */
export const CANVAS_ORIGIN = "canvas";

/** What the server tells the tab that drew a connection it took out: the
 *  node at one of its ends was removed meanwhile (`dataflow_docs.py`). */
export const CONNECTION_DROPPED_EVENT = "connection_dropped";

export interface DocBinding {
    /** The provider, which holds the doc and its awareness. */
    provider: DataflowDocProvider;
    /** Whether the first sync is done: the doc holds the server's. */
    synced: boolean;
}

export const DataflowDocContext = createContext<DocBinding | null>(null);

/** The doc this tab is bound to, or null. */
export function useDocBinding(): DocBinding | null {
    return useContext(DataflowDocContext);
}
