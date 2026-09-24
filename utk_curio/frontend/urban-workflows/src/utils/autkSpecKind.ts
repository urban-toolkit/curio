/** What kind of step an Autark (UrbanSpec) document describes. */
export type AutkSpecKind = "render" | "compute" | "data" | "unknown";

/**
 * Which kind of step an UrbanSpec describes (#282).
 *
 * ``render`` draws a map or plot; ``compute`` runs WGSL over upstream layers;
 * ``data`` only loads sources. The last two have nothing to draw, so the node
 * body reports what they produced instead of staying blank.
 *
 * Lives here rather than in the behavior so a caller can classify a node
 * without importing the Autark module, which pulls in the WebGPU renderer.
 * ``autkGrammarBehavior`` re-exports both functions, so existing imports and
 * the tests that use them are unaffected.
 */
export function classifyAutkSpec(spec: any): AutkSpecKind {
  if (!spec || typeof spec !== "object") return "unknown";
  if (spec.map != null || spec.plot != null) return "render";
  if (Array.isArray(spec.compute) && spec.compute.length > 0) return "compute";
  if (Array.isArray(spec.data) && spec.data.length > 0) return "data";
  return "unknown";
}

export function classifyAutkSpecString(specString: unknown): AutkSpecKind {
  if (typeof specString !== "string" || specString.trim() === "") return "unknown";
  try {
    return classifyAutkSpec(JSON.parse(specString));
  } catch {
    return "unknown";
  }
}
