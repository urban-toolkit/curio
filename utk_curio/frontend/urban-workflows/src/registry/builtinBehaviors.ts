/**
 * Registers the built-in behavior hooks at app startup.
 *
 * The pre-installed `curio.builtin@1` and `curio.streetvision@1` packages,
 * plus any third-party package authored against the same behavior keys
 * (e.g. `"code"`, `"vega"`), resolve their `manifest.behavior` field
 * through `getBehavior`.
 *
 * Side-effect import: just importing this module triggers all
 * registrations. Loaded from `registry/index.ts`.
 */

import {
  useCodeNodeBehavior,
  useDataExportBehavior,
  useVegaBehavior,
  useSimpleVisBehavior,
  useMergeFlowBehavior,
  useDataPoolBehavior,
  useDataSummaryBehavior,
  useAutkGrammarBehavior,
  useSpatialJoinBehavior,
} from '../adapters/node';
import { registerBehavior } from './behaviorRegistry';

registerBehavior('code', useCodeNodeBehavior);
registerBehavior('data-export', useDataExportBehavior);
registerBehavior('data-pool', useDataPoolBehavior);
registerBehavior('data-summary', useDataSummaryBehavior);
registerBehavior('vega', useVegaBehavior);
registerBehavior('simple-vis', useSimpleVisBehavior);
registerBehavior('autk-grammar', useAutkGrammarBehavior);
registerBehavior('merge-flow', useMergeFlowBehavior);
// curio.builtin@1 spatial-join node (stays in core because the builtin
// package's behaviors must be registered before ANY package registry runs).
registerBehavior('spatial-join', useSpatialJoinBehavior);
//
// The curio.streetvision@1 behaviors (street-view-fetcher, hf-cv-inference,
// cv-gallery) are NOT registered here — they ship as a pre-built `behaviors.js`
// bundle inside the package directory and self-register via the dynamic
// loader at `loadPackageBehaviorScripts` in packagesClient. See
// docs/EXTENDING.md §5 for the contract.
