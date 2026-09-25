import { AUTK_FAMILIES, AutkFamily } from "../generated/autkGrammar";

/** What kind of step an Autark (UrbanSpec) document describes. */
export type AutkSpecKind = "render" | "compute" | "data" | "unknown";

/**
 * The step each top-level family describes. Keyed by the families of the
 * vendored schema, so a family the grammar adds fails typecheck until it is
 * routed here.
 */
const FAMILY_KIND: Record<AutkFamily, Exclude<AutkSpecKind, "unknown">> = {
  map: "render",
  plot: "render",
  compute: "compute",
  data: "data",
};

/** Drawing wins over computing, and computing over loading. */
const KIND_ORDER = ["render", "compute", "data"] as const;

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
  // A map or plot counts as soon as it is named; a step list only when it
  // holds a step.
  const names = (family: AutkFamily) =>
    FAMILY_KIND[family] === "render"
      ? spec[family] != null
      : Array.isArray(spec[family]) && spec[family].length > 0;
  const kind = KIND_ORDER.find((k) =>
    AUTK_FAMILIES.some((family) => FAMILY_KIND[family] === k && names(family))
  );
  return kind ?? "unknown";
}

export function classifyAutkSpecString(specString: unknown): AutkSpecKind {
  if (typeof specString !== "string" || specString.trim() === "") return "unknown";
  try {
    return classifyAutkSpec(JSON.parse(specString));
  } catch {
    return "unknown";
  }
}
