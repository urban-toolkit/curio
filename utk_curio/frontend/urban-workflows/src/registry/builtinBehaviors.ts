/**
 * Registers the built-in behavior hooks at app startup.
 *
 * The pre-installed `curio.builtin@1` package, plus any package authored
 * against the same behavior keys
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
  useDataPoolBehavior,
  useDataSummaryBehavior,
  useAutkGrammarBehavior,
  useSpatialJoinBehavior,
  useParameterBehavior,
  useCompareScenariosBehavior,
  useRasterCalculatorBehavior,
  useRasterStatisticsBehavior,
} from '../adapters/node';
import { registerBehavior } from './behaviorRegistry';

registerBehavior('code', useCodeNodeBehavior);
registerBehavior('data-export', useDataExportBehavior);
registerBehavior('data-pool', useDataPoolBehavior);
registerBehavior('data-summary', useDataSummaryBehavior);
registerBehavior('vega', useVegaBehavior);
registerBehavior('simple-vis', useSimpleVisBehavior);
registerBehavior('autk-grammar', useAutkGrammarBehavior);
// curio.builtin@1 spatial-join node (stays in core because the builtin
// package's behaviors must be registered before ANY package registry runs).
registerBehavior('spatial-join', useSpatialJoinBehavior);
// curio.builtin@1 parameter node: one widget any node's code names as
// [!! @name !!] (#662).
registerBehavior('parameter', useParameterBehavior);
// curio.builtin@1 compare-scenarios node: stacks scenarios' outcomes, charts
// them in the scenarios' colors and lists what differs (#662).
registerBehavior('compare-scenarios', useCompareScenariosBehavior);
// curio.builtin@1 raster-calculator and raster-statistics nodes: Python nodes
// that start with a call to Curio's raster algebra.
registerBehavior('raster-calculator', useRasterCalculatorBehavior);
registerBehavior('raster-statistics', useRasterStatisticsBehavior);
//
// A package's own behaviors are NOT registered here: they ship as a
// pre-built `behaviors.js` bundle inside the package directory and
// self-register via the dynamic loader at `loadPackageBehaviorScripts` in
// packagesClient. See docs/EXTENDING.md §5 for the contract.
