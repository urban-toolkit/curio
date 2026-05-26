/**
 * Registers the built-in lifecycle hooks at app startup.
 *
 * The pre-installed `curio.builtin@1` and `curio.streetvision@1` packages,
 * plus any third-party package authored against the same lifecycle keys
 * (e.g. `"code"`, `"vega"`), resolve their `manifest.lifecycle` field
 * through `getLifecycle`.
 *
 * Side-effect import: just importing this module triggers all
 * registrations. Loaded from `registry/index.ts`.
 */

import {
  useCodeNodeLifecycle,
  useDataExportLifecycle,
  useVegaLifecycle,
  useSimpleVisLifecycle,
  useMergeFlowLifecycle,
  useDataPoolLifecycle,
  useDataSummaryLifecycle,
  useAutkMapLifecycle,
  useAutkPlotLifecycle,
  useAutkComputeLifecycle,
  useAutkDbLifecycle,
  useSpatialJoinLifecycle,
  useStreetViewFetcherLifecycle,
  useHfCvInferenceLifecycle,
  useCvGalleryLifecycle,
} from '../adapters/node';
import { registerLifecycle } from './lifecycleRegistry';

registerLifecycle('code', useCodeNodeLifecycle);
registerLifecycle('data-export', useDataExportLifecycle);
registerLifecycle('data-pool', useDataPoolLifecycle);
registerLifecycle('data-summary', useDataSummaryLifecycle);
registerLifecycle('vega', useVegaLifecycle);
registerLifecycle('simple-vis', useSimpleVisLifecycle);
registerLifecycle('autk-plot', useAutkPlotLifecycle);
registerLifecycle('autk-map', useAutkMapLifecycle);
registerLifecycle('autk-compute', useAutkComputeLifecycle);
registerLifecycle('autk-db', useAutkDbLifecycle);
registerLifecycle('merge-flow', useMergeFlowLifecycle);
// curio.builtin@1 spatial-join + curio.streetvision@1 nodes.
registerLifecycle('spatial-join', useSpatialJoinLifecycle);
registerLifecycle('street-view-fetcher', useStreetViewFetcherLifecycle);
registerLifecycle('hf-cv-inference', useHfCvInferenceLifecycle);
registerLifecycle('cv-gallery', useCvGalleryLifecycle);
