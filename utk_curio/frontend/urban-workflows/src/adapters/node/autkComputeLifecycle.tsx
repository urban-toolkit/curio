import { createAutkLifecycle } from './autkLifecycleFactory';

const DEFAULT_CODE = `// 'arg' is the upstream layer array or auto-wrapped FeatureCollection:
//   [{ name: string, type: string, geojson: GeoJSON.FeatureCollection }, ...]
// 'container' is a hidden offscreen canvas available for GPGPU work.
// 'ComputeGpgpu' and 'ComputeRender' are imported from @urban-toolkit/autk-compute automatically.
//
// Return the (possibly transformed) layer array — it is forwarded to downstream nodes.

// Example: pass the layer array through unchanged.
return arg;`;

export const useAutkComputeLifecycle = createAutkLifecycle({
    moduleImport: () => import('@urban-toolkit/autk-compute' as any),
    globals: ['ComputeGpgpu', 'ComputeRender'],
    container: 'hidden',
    defaultCode: DEFAULT_CODE,
    emitsOutput: true,
    autoWrapFeatureCollection: true,
});
