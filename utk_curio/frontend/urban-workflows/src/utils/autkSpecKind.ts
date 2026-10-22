import autkGrammar from "../contracts/autkGrammar.json";
import { withChipPlaceholders } from "./references/codeReferences";

/** What kind of step an Autark (UrbanSpec) document describes. */
export type AutkSpecKind = "render" | "compute" | "data" | "unknown";

/**
 * The step each top-level family describes. Keyed by the families
 * contracts/autkGrammar.json lists from the vendored schema, which a test
 * holds these keys to, so a family the grammar adds fails until it is routed
 * here.
 */
export const FAMILY_KIND = {
  map: "render",
  plot: "render",
  compute: "compute",
  data: "data",
} as const satisfies Record<string, Exclude<AutkSpecKind, "unknown">>;

type AutkFamily = keyof typeof FAMILY_KIND;

/** The families, in the file's order. */
const AUTK_FAMILIES = autkGrammar.families as readonly AutkFamily[];

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
  // A list is no document, though it answers to `map` (Array.prototype.map).
  if (!spec || typeof spec !== "object" || Array.isArray(spec)) return "unknown";
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

/**
 * ``classifyAutkSpec`` of a document as its node holds it, before its chips
 * are resolved: a chip standing on its own, `"color": [!! scenario input_1 !!]`,
 * holds its place (``withChipPlaceholders``), so the document is read for what
 * it declares rather than taken for no document.
 */
export function classifyAutkSpecString(specString: unknown): AutkSpecKind {
  if (typeof specString !== "string" || specString.trim() === "") return "unknown";
  try {
    return classifyAutkSpec(JSON.parse(withChipPlaceholders(specString)));
  } catch {
    return "unknown";
  }
}
