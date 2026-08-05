import { useSoftArtifactBehavior } from "./softArtifactBehavior"

type curioGlobal = { registerBehavior: (key: string, hook: any) => void };
function registerAll(curio: curioGlobal) {
    curio.registerBehavior('soft-artifact', useSoftArtifactBehavior)
}

if (typeof window !== 'undefined') {
  const w = window as any;
  if (w.curio?.registerBehavior) registerAll(w.curio);
  else (w.__curioPendingPackages__ ??= []).push(registerAll);
}