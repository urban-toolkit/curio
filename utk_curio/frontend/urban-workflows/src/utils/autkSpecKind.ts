import autkGrammar from "../contracts/autkGrammar.json";
import { withChipPlaceholders } from "./references/codeReferences";

/** What kind of step an Autark (UrbanSpec) document describes. */
export type AutkSpecKind = "render" | "compute" | "data" | "unknown";

/**
 * The step each top-level family describes. Keyed by the families
 * contracts/autkGrammar.json lists from the vendored schema, which a test
 * holds these keys to, so a family the grammar adds fails until it is routed
 * here. A family of null describes none of its own: a layout arranges views,
 * links join them and workspaces set where the sources load, so a document
 * with one is the step its other families describe.
 */
export const FAMILY_KIND = {
  map: "render",
  plot: "render",
  layout: null,
  links: null,
  workspaces: null,
  compute: "compute",
  data: "data",
} as const satisfies Record<string, Exclude<AutkSpecKind, "unknown"> | null>;

type AutkFamily = keyof typeof FAMILY_KIND;

/** The families, in the file's order. */
const AUTK_FAMILIES = autkGrammar.families as readonly AutkFamily[];

/** Drawing wins over computing, and computing over loading. */
const KIND_ORDER = ["render", "compute", "data"] as const;

/** Whether *spec* names *family*: a map or a plot as soon as it is named, a step list only when it holds a step. */
function namesFamily(spec: any, family: AutkFamily): boolean {
  return FAMILY_KIND[family] === "render"
    ? spec[family] != null
    : Array.isArray(spec[family]) && spec[family].length > 0;
}

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
  const kind = KIND_ORDER.find((k) =>
    AUTK_FAMILIES.some((family) => FAMILY_KIND[family] === k && namesFamily(spec, family))
  );
  return kind ?? "unknown";
}

/**
 * Whether an Autark document only draws its node's input: it draws (a map or
 * a plot), and has no data source and no pass of its own. A node of such a
 * document hands on its input as it came, and a run on the server forwards
 * it; a node that draws and also loads or computes hands on what it loads and
 * computes, as a compute step does (adapters/node/autkHandOn), and is the
 * browser's in a run. The canvas's one check for it, which the dashboard walk
 * and a scenario's saved outputs read (utils/dashboardLayout
 * `isPassThroughNode`) and the node itself; ``only_draws_its_input`` in
 * ``execution/autk_spec_kind.py`` is its twin.
 */
export function autkOnlyDrawsItsInput(spec: any): boolean {
  return classifyAutkSpec(spec) === "render" && !namesFamily(spec, "data") && !namesFamily(spec, "compute");
}

/**
 * ``classifyAutkSpec`` of a document as its node holds it, before its chips
 * are resolved: a chip standing on its own, `"color": [!! scenario input_1 !!]`,
 * holds its place (``withChipPlaceholders``), so the document is read for what
 * it declares rather than taken for no document.
 */
export function classifyAutkSpecString(specString: unknown): AutkSpecKind {
  const spec = parsedAutkSpec(specString);
  return spec === undefined ? "unknown" : classifyAutkSpec(spec);
}

/** ``autkOnlyDrawsItsInput`` of a document as its node holds it, its chips holding their places. */
export function autkOnlyDrawsItsInputString(specString: unknown): boolean {
  const spec = parsedAutkSpec(specString);
  return spec !== undefined && autkOnlyDrawsItsInput(spec);
}

/** A document as its node holds it, parsed with its chips holding their places; undefined for no JSON. */
function parsedAutkSpec(specString: unknown): unknown {
  if (typeof specString !== "string" || specString.trim() === "") return undefined;
  try {
    return JSON.parse(withChipPlaceholders(specString));
  } catch {
    return undefined;
  }
}
