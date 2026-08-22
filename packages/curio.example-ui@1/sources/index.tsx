/**
 * Bundle entry point for this package.
 *
 * Webpack compiles this file into `../scripts/behaviors.js`. At boot Curio
 * fetches that bundle for every installed package whose manifest declares
 * `behaviorScript` and evaluates it, so the side effect below is what actually
 * registers the hook. The key passed to `registerBehavior` must match the
 * template's `behavior` field in manifest.json.
 *
 * React, ReactDOM and ReactFlow are externalised to `window` so this bundle
 * shares Curio's own instances — two copies of React break every hook.
 */

import { useColumnFilterBehavior } from './columnFilterBehavior';

type CurioGlobal = {
  registerBehavior: (key: string, hook: any) => void;
};

function registerAll(curio: CurioGlobal) {
  curio.registerBehavior('column-filter', useColumnFilterBehavior);
}

if (typeof window !== 'undefined') {
  const w = window as any;
  if (w.curio && typeof w.curio.registerBehavior === 'function') {
    registerAll(w.curio);
  } else {
    // This bundle can load before Curio publishes its registry. Queue the
    // registration; the boot sequence drains the list once `window.curio` lands.
    const pending: Array<(c: CurioGlobal) => void> = (w.__curioPendingPackages__ ??= []);
    pending.push(registerAll);
  }
}
