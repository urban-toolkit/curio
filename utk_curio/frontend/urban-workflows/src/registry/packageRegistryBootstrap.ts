/**
 * Package discovery. Keeps logic out of ``index.tsx`` so
 * ``packagesApi.refreshPackageRegistry`` (and providers) never depend on
 * ``window.curio`` — that hook could be absent if bundles split or evaluate
 * in an unexpected order, which left the palette empty despite a signed-in session.
 */

import { loadInstalledPackages } from './packagesClient';
import { getCurrentProjectPackages } from './projectPackagesStore';

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
 * The palette is intersected with the current project's lockfile (via
 * ``projectPackagesStore``) when a project is loaded; on the projects-list /
 * catalog routes the store is empty and every installed package shows.
 */
export function refreshPackageRegistry(): Promise<void> {
  return loadInstalledPackages(getCurrentProjectPackages()).then(() => {
    notifyTemplatesAfterPackageRefresh();
  });
}
