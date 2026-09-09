/**
 * dev/118 (DEC-075): which node kinds the sandbox can RUN — the frontend twin
 * of `workflow_spec.is_executable_kind` (the `code` category). KEEP IN SYNC
 * with `utk_curio/backend/app/execution/workflow_spec.py` CODE_TYPES /
 * NAMESPACED_TO_LEGACY. Everything else renders in the browser: Solve writes
 * it and Play renders it, and no card may call it "verified".
 */
const EXECUTABLE_KINDS = new Set([
  "curio.builtin/data-loading",
  "curio.builtin/data-transformation",
  "curio.builtin/data-export",
  "curio.builtin/computation-analysis",
  "curio.builtin/js-computation",
  // legacy uppercase ids still found in old trill files
  "DATA_LOADING",
  "DATA_TRANSFORMATION",
  "DATA_EXPORT",
  "COMPUTATION_ANALYSIS",
  "CONSTANTS",
  "FLOW_SWITCH",
  "JS_COMPUTATION",
]);

export function isExecutableNodeType(nodeType: unknown): boolean {
  if (typeof nodeType !== "string" || !nodeType) return false;
  return EXECUTABLE_KINDS.has(nodeType.split("@", 1)[0]);
}
