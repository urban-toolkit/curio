/**
 * Package discovery. Keeps logic out of ``index.tsx`` so
 * ``packagesApi.refreshPackageRegistry`` (and providers) never depend on
 * ``window.curio`` — that hook could be absent if bundles split or evaluate
 * in an unexpected order, which left the palette empty despite a signed-in session.
 */

import { loadInstalledPackages } from './packagesClient';
import { getToken } from '../utils/authApi';
import { isStandaloneDashboard } from '../standalone/dashboardPayload';
import { registryLoadSettled, registryLoadStarted } from './registryReadiness';

function notifyTemplatesAfterPackageRefresh(): void {
  const w = window as unknown as { curio?: { fetchStarters?: () => void | Promise<void> } };
  const fn = w.curio?.fetchStarters;
  if (typeof fn === 'function') {
    void Promise.resolve(fn()).catch(() => {});
  }
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
  //
  // A standalone dashboard is the exception: it has no session and never will,
  // but it was served with the descriptors inside it, so there IS a real load
  // to do. Returning early here would leave the registry never ready
  // (`registryReadiness`), and `UnresolvedNode` would show "Loading node..." on
  // every tile forever rather than render the page the viewer was sent.
  if (!getToken() && !isStandaloneDashboard()) return Promise.resolve();
  registryLoadStarted();
  return loadInstalledPackages()
    .then(() => {
      notifyTemplatesAfterPackageRefresh();
    })
    .finally(registryLoadSettled);
}
