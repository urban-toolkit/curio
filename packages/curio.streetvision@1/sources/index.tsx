/**
 * Entry point for the curio.streetvision@1 dynamic behavior bundle.
 *
 * Webpack builds this into `../scripts/behaviors.js` (under the package
 * directory). The `scripts/` subdir is one of the archive validator's
 * allowed top-level dirs, so the bundle survives the catalog install
 * round-trip. When the frontend fetches the installed package list and
 * sees `manifest.behaviorScript: "scripts/behaviors.js"`, it loads this
 * bundle via a `<script>` tag injection. The side-effect calls below
 * register each behavior against the global registry exposed on
 * `window.curio` at app boot.
 *
 * React, ReactFlow, and the `registerBehavior` function are externalized
 * — they live on `window` so this bundle stays small and shares Curio's
 * own React instance (so hooks work correctly).
 */

import { useStreetViewFetcherBehavior } from './streetViewFetcherBehavior';
import { useHfCvInferenceBehavior } from './hfCvInferenceBehavior';
import { useCvGalleryBehavior } from './cvGalleryBehavior';

// `window.curio.registerBehavior` is exposed by Curio's main bundle at boot
// (src/registry/index.ts). We avoid a `declare global` for portability —
// babel-preset-typescript outside the host tsconfig refuses ambient
// declarations.
type CurioGlobal = {
  registerBehavior: (key: string, hook: any) => void;
};

function registerAll(curio: CurioGlobal) {
  curio.registerBehavior('street-view-fetcher', useStreetViewFetcherBehavior);
  curio.registerBehavior('hf-cv-inference', useHfCvInferenceBehavior);
  curio.registerBehavior('cv-gallery', useCvGalleryBehavior);
}

if (typeof window !== 'undefined') {
  const w = window as any;
  if (w.curio && typeof w.curio.registerBehavior === 'function') {
    registerAll(w.curio);
  } else {
    // Host hasn't published its registry yet. Stash a callback so the boot
    // sequence can drain pending registrations once `window.curio` lands.
    const pending: Array<(c: CurioGlobal) => void> = (w.__curioPendingPackages__ ??= []);
    pending.push(registerAll);
  }
}
