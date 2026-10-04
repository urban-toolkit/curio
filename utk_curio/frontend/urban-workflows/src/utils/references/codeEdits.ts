/**
 * A signal that some node's code changed. A node's code is mirrored into its
 * data by direct mutation (useNodeState), not through the flow's state, so a
 * view that reads every node's code, such as a Parameter node's list of the
 * nodes that use it, listens here (`useSyncExternalStore`).
 */
let revision = 0;
const listeners = new Set<() => void>();

export function noteCodeEdit(): void {
  revision += 1;
  listeners.forEach((listener) => listener());
}

export function subscribeToCodeEdits(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function codeEditRevision(): number {
  return revision;
}
