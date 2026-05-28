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
  useAutkGrammarLifecycle,
  useSpatialJoinLifecycle,
} from '../adapters/node';
import { registerLifecycle } from './lifecycleRegistry';

registerLifecycle('code', useCodeNodeLifecycle);
registerLifecycle('data-export', useDataExportLifecycle);
registerLifecycle('data-pool', useDataPoolLifecycle);
registerLifecycle('data-summary', useDataSummaryLifecycle);
registerLifecycle('vega', useVegaLifecycle);
registerLifecycle('simple-vis', useSimpleVisLifecycle);
registerLifecycle('autk-grammar', useAutkGrammarLifecycle);
registerLifecycle('merge-flow', useMergeFlowLifecycle);
// curio.builtin@1 spatial-join node (stays in core because the builtin
// package's lifecycles must be registered before ANY package registry runs).
registerLifecycle('spatial-join', useSpatialJoinLifecycle);
//
// The curio.streetvision@1 lifecycles (street-view-fetcher, hf-cv-inference,
// cv-gallery) are NOT registered here — they ship as a pre-built `lifecycles.js`
// bundle inside the package directory and self-register via the dynamic
// loader at `loadPackageLifecycleScripts` in packagesClient. See
// docs/EXTENDING.md §5 for the contract.
