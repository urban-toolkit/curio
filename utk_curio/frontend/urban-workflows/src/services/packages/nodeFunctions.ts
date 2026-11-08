/**
 * What a node's code can call, as the header above its code lists it
 * (`GET /api/packages/node-functions`): Curio's functions for the node's
 * engine, and, for a Python node, those of the modules a run hands it.
 *
 * Read once per dataflow and node type, however many nodes of the type the
 * canvas holds, and kept until the installed packages change: each refresh of
 * the package registry tells `forgetNodeFunctions` what they are, and when
 * they changed, the headers on the canvas read their lists again. A read
 * that fails lists nothing, and a page with no session, such as a dashboard
 * a viewer opens with no sign-in, reads nothing and lists nothing.
 */
import { useEffect, useSyncExternalStore } from "react";
import { getToken } from "../../utils/authApi";
import { packagesApi } from "./packagesApi";
import type { NodeFunctionsPayload } from "./types";

export type NodeFunctionsState =
  | { state: "loading" }
  | { state: "ready"; functions: NodeFunctionsPayload }
  | { state: "failed" };

/** What a node with no type, which no list is read for, lists: nothing. */
const NOTHING: NodeFunctionsState = { state: "ready", functions: { engine: null, curio: [], modules: [] } };

let entries = new Map<string, NodeFunctionsState>();
/** A list not read yet: a new one each time the lists are forgotten, so a
 * header whose read was on its way when they were reads again. */
let loading: NodeFunctionsState = { state: "loading" };
/** Bumped as the lists are forgotten, so a read on its way then is not kept. */
let generation = 0;
/** What the installed packages were at the last refresh that said. */
let packagesSeen: string | null = null;
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

const keyOf = (nodeType: string, dataflowId?: string | null) => `${dataflowId ?? ""}\n${nodeType}`;

/** The list of a node of *nodeType* in the dataflow *dataflowId*, as read so
 * far: loading until its read comes back. */
export function nodeFunctionsOf(nodeType: string, dataflowId?: string | null): NodeFunctionsState {
  return entries.get(keyOf(nodeType, dataflowId)) ?? loading;
}

/** Reads the list of a node of *nodeType* in the dataflow *dataflowId*,
 * unless it is read or being read. */
export function readNodeFunctions(nodeType: string, dataflowId?: string | null): void {
  const key = keyOf(nodeType, dataflowId);
  if (entries.has(key)) return;
  entries.set(key, loading);
  const asked = generation;
  const settle = (state: NodeFunctionsState) => {
    if (asked !== generation) return;
    entries = new Map(entries).set(key, state);
    notify();
  };
  // A call that throws at once fails as one that answers with an error does.
  Promise.resolve()
    .then(() => packagesApi.nodeFunctions(nodeType, dataflowId))
    .then(
      (functions) => settle({ state: "ready", functions }),
      () => settle({ state: "failed" }),
    );
}

/**
 * Forgets every list read when the installed packages changed: *packages*
 * says what they are now, and the first refresh's only records it. With no
 * *packages*, forgets them at once.
 */
export function forgetNodeFunctions(packages?: string): void {
  if (packages !== undefined) {
    const changed = packagesSeen !== null && packagesSeen !== packages;
    packagesSeen = packages;
    if (!changed) return;
  }
  generation += 1;
  loading = { state: "loading" };
  entries = new Map();
  notify();
}

/** The list of a node of *nodeType* in the dataflow *dataflowId*, read on
 * first use and again after the packages change; nothing for no type, and
 * nothing with no session, whose read could only be refused. */
export function useNodeFunctions(nodeType: string | null | undefined, dataflowId?: string | null): NodeFunctionsState {
  const asks = !!nodeType && !!getToken();
  const read = () => (asks && nodeType ? nodeFunctionsOf(nodeType, dataflowId) : NOTHING);
  const state = useSyncExternalStore(subscribe, read, read);
  useEffect(() => {
    if (asks && nodeType) readNodeFunctions(nodeType, dataflowId);
  }, [asks, nodeType, dataflowId, state]);
  return state;
}
