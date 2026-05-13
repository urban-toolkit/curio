export enum NodeType {
  DATA_LOADING = "DATA_LOADING",
  DATA_EXPORT = "DATA_EXPORT",
  DATA_TRANSFORMATION = "DATA_TRANSFORMATION",
  COMPUTATION_ANALYSIS = "COMPUTATION_ANALYSIS",
  DATA_SUMMARY = "DATA_SUMMARY",
  FLOW_SWITCH = "FLOW_SWITCH",
  VIS_VEGA = "VIS_VEGA",
  VIS_SIMPLE = "VIS_SIMPLE",
  CONSTANTS = "CONSTANTS",
  DATA_POOL = "DATA_POOL",
  MERGE_FLOW = "MERGE_FLOW",
  COMMENTS = "COMMENTS",
  STREET_VISION = "STREET_VISION",
  CV_ANALYSIS = "CV_ANALYSIS",
  JS_COMPUTATION = "JS_COMPUTATION",
  AUTK_MAP = "AUTK_MAP",
  AUTK_PLOT = "AUTK_PLOT",
  AUTK_COMPUTE = "AUTK_COMPUTE",
  AUTK_DB = "AUTK_DB",
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
