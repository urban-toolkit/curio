import { createAutkLifecycle } from './autkLifecycleFactory';

const DEFAULT_CODE = `// 'arg' is the upstream layer array or auto-wrapped FeatureCollection:
//   [{ name: string, type: string, geojson: GeoJSON.FeatureCollection }, ...]
// 'container' is a hidden offscreen canvas available for GPGPU work.
// 'ComputeGpgpu' and 'ComputeRender' are imported from autk-compute automatically.
//
// Return the (possibly transformed) layer array — it is forwarded to downstream nodes.

// Example: pass the layer array through unchanged.
return arg;`;

export const useAutkComputeLifecycle = createAutkLifecycle({
    // autk-compute's types reference autk-core which isn't installed; cast to skip resolution.
    moduleImport: () => import('autk-compute' as any),
    globals: ['ComputeGpgpu', 'ComputeRender'],
    container: 'hidden',
    defaultCode: DEFAULT_CODE,
    emitsOutput: true,
    autoWrapFeatureCollection: true,
});
