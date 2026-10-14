/**
 * Bundle entry point for the Notes package.
 *
 * Webpack compiles this file into `../scripts/behaviors.js`; Curio evaluates
 * that bundle at boot, which registers the `note` behavior named by the
 * template in manifest.json. React and ReactFlow are Curio's own, on `window`.
 */

import { useNoteBehavior } from './noteBehavior';

type CurioGlobal = {
  registerBehavior: (key: string, hook: any) => void;
};

function registerAll(curio: CurioGlobal) {
  curio.registerBehavior('note', useNoteBehavior);
}

if (typeof window !== 'undefined') {
  const w = window as any;
  if (w.curio && typeof w.curio.registerBehavior === 'function') {
    registerAll(w.curio);
  } else {
    // This bundle can load before Curio publishes its registry: queue it.
    const pending: Array<(c: CurioGlobal) => void> = (w.__curioPendingPackages__ ??= []);
    pending.push(registerAll);
  }
}
