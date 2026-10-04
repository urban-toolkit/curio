/**
 * Whether the package registry has finished at least one real load and none is
 * in flight.
 *
 * A node whose type has no descriptor has two very different explanations:
 * the registry has not caught up yet, or nothing installed provides that type.
 * They were indistinguishable, so both rendered "Loading node…" and the second
 * one rendered it forever - which is all the streetvision example ever showed
 * (#233). This is the signal that separates them.
 *
 * "At least one real load" matters: ``refreshPackageRegistry`` returns early
 * with no session, and a canvas that concluded "not installed" from an absent
 * token would accuse every node on the board.
 *
 * It lives apart from ``packageRegistryBootstrap``, which does the loading and
 * pulls in every node adapter (vega included), so that light modules can read
 * it: the canvas's load fit waits on it (#683).
 */
let completedRealLoad = false;
let inFlight = 0;
const readyListeners = new Set<() => void>();

function emitReadyChange(): void {
  readyListeners.forEach((listener) => listener());
}

export function isRegistryReady(): boolean {
  return completedRealLoad && inFlight === 0;
}

export function subscribeToRegistryReady(listener: () => void): () => void {
  readyListeners.add(listener);
  return () => {
    readyListeners.delete(listener);
  };
}

/** A registry load has started. */
export function registryLoadStarted(): void {
  inFlight += 1;
  emitReadyChange();
}

/** A registry load has ended. A load that FAILED still counts as settled:
 *  ``loadInstalledPackages`` swallows its own errors and returns [], so waiting
 *  for a success that will never come is how the placeholder became permanent. */
export function registryLoadSettled(): void {
  inFlight -= 1;
  completedRealLoad = true;
  emitReadyChange();
}
