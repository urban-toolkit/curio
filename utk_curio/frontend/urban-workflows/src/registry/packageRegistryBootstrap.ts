/**
 * Package discovery + `/node-types` sync. Keeps logic out of ``index.tsx`` so
 * ``packagesApi.refreshPackageRegistry`` (and providers) never depend on
 * ``window.curio`` — that hook could be absent if bundles split or evaluate
 * in an unexpected order, which left the palette empty despite a signed-in session.
 */

import { getAllNodeTypes } from './nodeRegistry';
import { loadInstalledPackages } from './packagesClient';
import { getCurrentProjectPackages } from './projectPackagesStore';

/** POST merged descriptor port shapes — idempotent on the backend. */
export function syncNodeTypeRegistry(): Promise<void> {
  const nodeTypes: Record<
    string,
    { inputTypes: string[]; outputTypes: string[] }
  > = {};
  for (const desc of getAllNodeTypes()) {
    nodeTypes[desc.id] = {
      inputTypes: desc.inputPorts.flatMap((p) => p.types),
      outputTypes: desc.outputPorts.flatMap((p) => p.types),
    };
  }
  const base = process.env.BACKEND_URL ?? '';
  return fetch(`${base}/node-types`, {
    method: 'POST',
    headers: { 'Content-type': 'application/json; charset=UTF-8' },
    body: JSON.stringify({ nodeTypes }),
  })
    .then(() => {})
    .catch(() => {});
}

function notifyTemplatesAfterPackageRefresh(): void {
  const w = window as unknown as { curio?: { fetchStarters?: () => void | Promise<void> } };
  const fn = w.curio?.fetchStarters;
  if (typeof fn === 'function') {
    void Promise.resolve(fn()).catch(() => {});
  }
}

/**
 * Fetch installed packages, register descriptors, push merged port shapes, then
 * reload ``/starters`` so package default bodies appear in ``StarterProvider``
 * (required for {@link usePackageNodeLifecycle} injection on new kinds).
 *
 * The palette is intersected with the current project's lockfile (via
 * ``projectPackagesStore``) when a project is loaded; on the projects-list /
 * catalog routes the store is empty and every installed package shows.
 */
export function refreshPackageRegistry(): Promise<void> {
  return loadInstalledPackages(getCurrentProjectPackages())
    .then(() => syncNodeTypeRegistry())
    .then(() => {
      notifyTemplatesAfterPackageRefresh();
    });
}
