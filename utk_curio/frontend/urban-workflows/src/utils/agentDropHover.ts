/**
 * Which connection a palette-agent drag is currently over (#296).
 *
 * A module-scoped store rather than a window event or React state, for three
 * reasons that only matter because ``dragover`` fires continuously:
 *
 *   - **It dedupes.** ``setAgentDropHoverEdgeId`` returns early when the value
 *     has not changed, so a pointer resting on one edge does no React work at
 *     all. A ``CustomEvent`` would allocate and dispatch per pointer move.
 *   - **It has a snapshot.** ``getAgentDropHoverEdgeId`` gives
 *     ``useSyncExternalStore`` a correct initial value, so an edge that mounts
 *     mid-drag renders already-highlighted. An event stream has no "what is
 *     true right now".
 *   - **It re-renders two edges, not all of them.** Each subscriber derives its
 *     own boolean, so React bails out per edge on ``Object.is``. Canvas state
 *     (or a context around ``<ReactFlow>``) would re-render every edge, and
 *     ``MainCanvas`` itself, on every pointer move.
 *
 * Deliberately NOT in ``agentCatalogEvents.ts``: that module is stateless on
 * purpose - ``src/tests/palette/agentDropTarget.test.ts`` imports it with no DOM
 * setup and no cleanup, which is only safe while it holds no mutable singleton.
 *
 * It touches no ``window``, so it needs no SSR/jsdom guard and is importable
 * anywhere. Tests must call ``clearAgentDropHover()`` in ``afterEach``: the
 * value outlives a render tree.
 */

let hoveredEdgeId: string | null = null;
const listeners = new Set<() => void>();

/** The edge a drag is over right now, or null. */
export function getAgentDropHoverEdgeId(): string | null {
  return hoveredEdgeId;
}

/**
 * Point the hover at *edgeId* (or clear it with null). A repeat of the current
 * value notifies nobody - see the dedupe note above.
 */
export function setAgentDropHoverEdgeId(edgeId: string | null): void {
  if (edgeId === hoveredEdgeId) return;
  hoveredEdgeId = edgeId;
  listeners.forEach((listener) => listener());
}

/** No drag is over any connection. */
export function clearAgentDropHover(): void {
  setAgentDropHoverEdgeId(null);
}

/** Subscribe to hover changes; returns the unsubscribe. */
export function subscribeAgentDropHover(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
