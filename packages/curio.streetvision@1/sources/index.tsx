/**
 * Entry point for the curio.streetvision@1 dynamic lifecycle bundle.
 *
 * Webpack builds this into `../lifecycles.js` (alongside `manifest.json` in
 * the package directory). When the frontend fetches the installed package
 * list and sees `manifest.lifecycleScript: "lifecycles.js"`, it loads this
 * bundle via a `<script>` tag injection. The side-effect calls below
 * register each lifecycle against the global registry exposed on
 * `window.curio` at app boot.
 *
 * React, ReactFlow, and the `registerLifecycle` function are externalized
 * — they live on `window` so this bundle stays small and shares Curio's
 * own React instance (so hooks work correctly).
 */

import { useStreetViewFetcherLifecycle } from './streetViewFetcherLifecycle';
import { useHfCvInferenceLifecycle } from './hfCvInferenceLifecycle';
import { useCvGalleryLifecycle } from './cvGalleryLifecycle';

// `window.curio.registerLifecycle` is exposed by Curio's main bundle at boot
// (src/registry/index.ts). We avoid a `declare global` for portability —
// babel-preset-typescript outside the host tsconfig refuses ambient
// declarations.
type CurioGlobal = {
  registerLifecycle: (key: string, hook: any) => void;
};

function registerAll(curio: CurioGlobal) {
  curio.registerLifecycle('street-view-fetcher', useStreetViewFetcherLifecycle);
  curio.registerLifecycle('hf-cv-inference', useHfCvInferenceLifecycle);
  curio.registerLifecycle('cv-gallery', useCvGalleryLifecycle);
}

if (typeof window !== 'undefined') {
  const w = window as any;
  if (w.curio && typeof w.curio.registerLifecycle === 'function') {
    registerAll(w.curio);
  } else {
    // Host hasn't published its registry yet. Stash a callback so the boot
    // sequence can drain pending registrations once `window.curio` lands.
    const pending: Array<(c: CurioGlobal) => void> = (w.__curioPendingPackages__ ??= []);
    pending.push(registerAll);
  }
}
