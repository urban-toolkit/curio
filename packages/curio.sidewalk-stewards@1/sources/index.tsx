import { useSidewalkTileEditBehavior } from './sidewalkTileEditBehavior';

import { useSidewalkPreparation } from './sidewalkPreparation';

type CurioGlobal = { registerBehavior: (key: string, hook: unknown) => void };
function register(curio: CurioGlobal) {
  curio.registerBehavior('sidewalk-tile-edit', useSidewalkTileEditBehavior);
  curio.registerBehavior('sidewalk-prepare', useSidewalkPreparation);
}

if (typeof window !== 'undefined') {
  const host = window as any;
  if (typeof host.curio?.registerBehavior === 'function') register(host.curio);
  else {
    const pending: Array<(curio: CurioGlobal) => void> = (host.__curioPendingPackages__ ??= []);
    pending.push(register);
  }
}
