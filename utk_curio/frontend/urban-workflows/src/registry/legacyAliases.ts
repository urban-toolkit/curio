/**
 * Maps legacy ``NodeType`` enum strings (e.g. "DATA_LOADING") to the
 * unversioned canonical pack-kind id ("curio.builtin/data-loading").
 *
 * Used by:
 *   - {@link aliasNormalize} at trill-load time, so any saved workflow
 *     written with the legacy string still resolves after Phase B.
 *   - {@link getNodeDescriptor} as a fall-through lookup when an exact
 *     match misses, covering descriptor lookups that bypass the trill
 *     loader.
 *
 * Dead types intentionally omitted: CONSTANTS, FLOW_SWITCH, COMMENTS were
 * removed in Phase B0. Projects referencing them render as
 * "unknown type" placeholders.
 */

export const LEGACY_TYPE_TO_CANONICAL: Readonly<Record<string, string>> = Object.freeze({
  DATA_LOADING: 'curio.builtin/data-loading',
  DATA_EXPORT: 'curio.builtin/data-export',
  DATA_TRANSFORMATION: 'curio.builtin/data-transformation',
  DATA_POOL: 'curio.builtin/data-pool',
  COMPUTATION_ANALYSIS: 'curio.builtin/computation-analysis',
  DATA_SUMMARY: 'curio.builtin/data-summary',
  JS_COMPUTATION: 'curio.builtin/js-computation',
  VIS_VEGA: 'curio.builtin/vis-vega',
  VIS_SIMPLE: 'curio.builtin/vis-simple',
  AUTK_PLOT: 'curio.builtin/autk-plot',
  AUTK_MAP: 'curio.builtin/autk-map',
  AUTK_COMPUTE: 'curio.builtin/autk-compute',
  AUTK_DB: 'curio.builtin/autk-db',
  MERGE_FLOW: 'curio.builtin/merge-flow',
});

/** Returns the canonical unversioned type for a legacy enum string, or undefined. */
export function legacyToCanonical(legacyType: string): string | undefined {
  return LEGACY_TYPE_TO_CANONICAL[legacyType];
}
