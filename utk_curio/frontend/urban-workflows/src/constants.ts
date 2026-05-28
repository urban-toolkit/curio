/** Every canvas node maps to UniversalNode via this RF ``node.type``; real template id is ``data.nodeType``. */
export const CURIO_UNIVERSAL_NODE_TYPE = "__curioUniversalNode" as const;

/**
 * Canonical unversioned node-type identifiers.
 *
 * Each value is the canonical package-template id (`<packageId>/<templateId>`) that
 * resolves through the registry's unversioned-latest-major lookup. The
 * enum keys keep the legacy names so existing dispatch code in
 * `NotebookConvertor` / `useNodeState` etc. keeps compiling unchanged —
 * but at runtime they emit canonical strings.
 *
 * Legacy trill files that still use the old enum string ("DATA_LOADING")
 * are normalized at load time by `aliasNormalize(trill)` (see
 * `TrillGenerator`).
 */
export enum NodeType {
  DATA_LOADING = "curio.builtin/data-loading",
  DATA_EXPORT = "curio.builtin/data-export",
  DATA_TRANSFORMATION = "curio.builtin/data-transformation",
  COMPUTATION_ANALYSIS = "curio.builtin/computation-analysis",
  DATA_SUMMARY = "curio.builtin/data-summary",
  VIS_VEGA = "curio.builtin/vis-vega",
  VIS_SIMPLE = "curio.builtin/vis-simple",
  DATA_POOL = "curio.builtin/data-pool",
  MERGE_FLOW = "curio.builtin/merge-flow",
  JS_COMPUTATION = "curio.builtin/js-computation",
  AUTK_GRAMMAR = "curio.builtin/autk-grammar",
}

export enum EdgeType {
  BIDIRECTIONAL_EDGE = "BIDIRECTIONAL_EDGE",
  UNIDIRECTIONAL_EDGE = "UNIDIRECTIONAL_EDGE"
}

export enum SupportedType {
  DATAFRAME = "DATAFRAME",
  GEODATAFRAME = "GEODATAFRAME",
  VALUE = "VALUE", // int, float, boolean, ...
  LIST = "LIST",
  JSON = "JSON", // dictionary in python
  RASTER = "RASTER",
}

export enum WidgetType {
  CHECKBOX = "CHECKBOX", // boolean
  INPUT_VALUE = "INPUT_VALUE", // int, float
  INPUT_TEXT = "INPUT_TEXT", // string
  INPUT_LIST_VALUE = "INPUT_LIST_VALUE", // list of non-string values
  INPUT_LIST_TEXT = "INPUT_LIST_TEXT", // list of strings
  RANGE = "RANGE", // [number, number]
  SELECTION = "SELECTION", // string. parameters (option1, option2)
  FILE = "FILE", // string
}

export enum VisInteractionType {
  POINT = "POINT",
  INTERVAL = "INTERVAL",
  UNDETERMINED = "UNDETERMINED",
}

// resolution between plots
export enum ResolutionType {
  OVERWRITE = "OVERWRITE", // last interacted with overwrites other interactions
  MERGE_AND = "MERGE_AND", // all plots need to interact
  MERGE_OR = "MERGE_OR", // at least one plot needs to interact
}

export enum AccessLevelType {
  PROGRAMMER = "PROGRAMMER", // only programmers can access
  EXPERT = "EXPERT", // only experts can access
  ANY = "ANY", // both can access
}
