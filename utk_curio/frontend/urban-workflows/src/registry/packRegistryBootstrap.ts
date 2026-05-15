/**
 * Pack discovery + `/node-types` sync. Keeps logic out of ``index.tsx`` so
 * ``packsApi.refreshPackRegistry`` (and providers) never depend on
 * ``window.curio`` — that hook could be absent if bundles split or evaluate
 * in an unexpected order, which left the palette empty despite a signed-in session.
 */

import { getAllNodeTypes } from './nodeRegistry';
import { loadInstalledPacks } from './packsClient';

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

function notifyTemplatesAfterPackRefresh(): void {
  const w = window as unknown as { curio?: { fetchTemplates?: () => void | Promise<void> } };
  const fn = w.curio?.fetchTemplates;
  if (typeof fn === 'function') {
    void Promise.resolve(fn()).catch(() => {});
  }
}

/**
 * Fetch installed packs, register descriptors, push merged port shapes, then
 * reload ``/templates`` so pack default bodies appear in ``TemplateProvider``
 * (required for {@link usePackNodeLifecycle} injection on new kinds).
 */
export function refreshPackRegistry(): Promise<void> {
  return loadInstalledPacks()
    .then(() => syncNodeTypeRegistry())
    .then(() => {
      notifyTemplatesAfterPackRefresh();
    });
}
