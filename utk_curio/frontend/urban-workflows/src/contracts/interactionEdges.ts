/**
 * The one rule for interaction edges (`interactionEdges.json`): an edge that
 * carries a selection between two views, and never data.
 *
 * A node's own interaction handle is `in/out`. A view of a node has one of
 * its own, `in/out@<id>`: the node's handle, the mark, then the view's `id`.
 * An edge is an interaction edge when a saved dataflow types it so, an agent's
 * plan gives it that kind, or both its handles are interaction handles. Every
 * module of the canvas that tells an interaction handle or edge asks here, and
 * one that declares or writes a node's own handle reads `INTERACTION_HANDLE`
 * (src/tests/contracts/interactionHandleGuard.test.ts). The backend's twin is
 * `execution/run_plan.py`; both run `interactionEdges.cases.json`.
 */
import rule from './interactionEdges.json';

/** A node's own interaction handle. */
export const INTERACTION_HANDLE: string = rule.handle;

/** What a view's interaction handle starts with: a node's own, then the mark. */
const VIEW_HANDLE_PREFIX = rule.handle + rule.viewMark;

/** The id of the view *handle* names (`in/out@<id>`): null for a node's own handle, and for any other. */
export function interactionHandleView(handle: unknown): string | null {
  if (typeof handle !== 'string' || !handle.startsWith(VIEW_HANDLE_PREFIX)) return null;
  const id = handle.slice(VIEW_HANDLE_PREFIX.length);
  return id === '' ? null : id;
}

/** Whether *handle* is an interaction handle: a node's own, or a view's. */
export function isInteractionHandle(handle: unknown): boolean {
  return handle === INTERACTION_HANDLE || interactionHandleView(handle) !== null;
}

/**
 * The interaction handle of the view whose id is *view*: a node's own handle,
 * the mark, then the id; a node's own handle for no id. A view's dot, a load
 * and an agent's plan write a view's handle through it.
 */
export function interactionViewHandle(view: string | null | undefined): string {
  return typeof view === 'string' && view !== '' ? VIEW_HANDLE_PREFIX + view : INTERACTION_HANDLE;
}

/**
 * The handle an interaction edge keeps at one end: the one it names when that
 * is an interaction handle, a view's among them, else a node's own. A load and
 * an agent's applied edge put an interaction edge on the canvas through it.
 */
export function interactionHandleOr(handle: unknown): string {
  return isInteractionHandle(handle) ? (handle as string) : INTERACTION_HANDLE;
}

/** An edge as the canvas, a saved dataflow or an agent's plan holds it. */
export type EdgeLike = { type?: unknown; kind?: unknown; sourceHandle?: unknown; targetHandle?: unknown };

/** Whether *edge* is an interaction edge: typed so, of that kind, or with an interaction handle at both ends. */
export function isInteractionEdge(edge: EdgeLike | null | undefined): boolean {
  if (!edge || typeof edge !== 'object') return false;
  return edge.type === rule.edgeType
    || edge.kind === rule.planKind
    || (isInteractionHandle(edge.sourceHandle) && isInteractionHandle(edge.targetHandle));
}
