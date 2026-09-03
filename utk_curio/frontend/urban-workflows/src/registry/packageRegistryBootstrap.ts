/**
 * Package discovery. Keeps logic out of ``index.tsx`` so
 * ``packagesApi.refreshPackageRegistry`` (and providers) never depend on
 * ``window.curio`` — that hook could be absent if bundles split or evaluate
 * in an unexpected order, which left the palette empty despite a signed-in session.
 */

import { loadInstalledPackages } from './packagesClient';
import { getToken } from '../utils/authApi';

function notifyTemplatesAfterPackageRefresh(): void {
  const w = window as unknown as { curio?: { fetchStarters?: () => void | Promise<void> } };
  const fn = w.curio?.fetchStarters;
  if (typeof fn === 'function') {
    void Promise.resolve(fn()).catch(() => {});
  }
}

/**
 * Whether the registry has finished at least one real load and none is in
 * flight.
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

/**
 * Fetch installed packages, register descriptors, then reload ``/starters`` so
 * package default bodies appear in ``StarterProvider`` (required for
 * {@link usePackageNodeBehavior} injection on new kinds).
 *
 * Registers every installed package. The per-dataflow scope is applied when the
 * palette is read (``getPaletteNodeTypes``), so this does not need re-running
 * when the open dataflow changes -- only when the INSTALLED set does.
 */
export function refreshPackageRegistry(): Promise<void> {
  // Nothing to fetch without a session. ``/api/packages`` is ``@require_auth``
  // and its response is per-user, so an anonymous call could only ever 401 —
  // and although ``loadInstalledPackages`` suppresses its own warning for that
  // status, the browser still logs "Failed to load resource: 401" on the
  // sign-up page, the first screen a new user sees. Callers that matter run
  // after sign-in anyway: ``UserProvider.applyUser`` refreshes as soon as a
  // user resolves, and ``ToolsMenu`` refreshes again when ``user.id`` appears.
  if (!getToken()) return Promise.resolve();
  inFlight += 1;
  emitReadyChange();
  return loadInstalledPackages()
    .then(() => {
      notifyTemplatesAfterPackageRefresh();
    })
    .finally(() => {
      inFlight -= 1;
      // A load that FAILED still counts as settled: `loadInstalledPackages`
      // swallows its own errors and returns [], so waiting for a success that
      // will never come is how the placeholder became permanent.
      completedRealLoad = true;
      emitReadyChange();
    });
}
