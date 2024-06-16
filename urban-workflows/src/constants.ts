export enum BoxType {
  DATA_LOADING = "DATA_LOADING",
  DATA_EXPORT = "DATA_EXPORT",
  DATA_CLEANING = "DATA_CLEANING",
  DATA_TRANSFORMATION = "DATA_TRANSFORMATION",
  COMPUTATION_ANALYSIS = "COMPUTATION_ANALYSIS",
  FLOW_SWITCH = "FLOW_SWITCH",
  VIS_UTK = "VIS_UTK",
  VIS_VEGA = "VIS_VEGA",
  VIS_TABLE = "VIS_TABLE",
  VIS_TEXT = "VIS_TEXT",
  VIS_IMAGE = "VIS_IMAGE",
  CONSTANTS = "CONSTANTS",
  DATA_POOL = "DATA_POOL",
  MERGE_FLOW = "MERGE_FLOW",
  COMMENTS = "COMMENTS",
}

export enum EdgeType {
  BIDIRECTIONAL_EDGE = "BIDIRECTIONAL_EDGE",
}

export enum SupportedType {
  DATAFRAME = "DATAFRAME",
  GEODATAFRAME = "GEODATAFRAME",
  VALUE = "VALUE", // int, float, boolean, ...
  LIST = "LIST",
  JSON = "JSON", // dictionary in python
  RASTER = "RASTER"
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

export enum ResolutionTypeUTK{
    PICKING = "PICKING", // all coordinates of the object need to be selected for the object to be considered selected
    BRUSHING = "BRUSHING", // at least one coordinate of the object need to be selected for the object to be considered selected
    NONE = "NONE"
}

export enum AccessLevelType{
    PROGRAMMER = "PROGRAMMER", // only programmers can access
    EXPERT = "EXPERT", // only experts can access
    ANY = "ANY" // both can access
}
