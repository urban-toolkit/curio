import { SupportedType } from "../constants";

export const formatDate = (date: Date) => {
    const month = date.toLocaleString("default", { month: "short" });
    const day = date.getDate();
    const year = date.getFullYear();
    const hours = date.getHours();
    const minutes = date.getMinutes();
    const seconds = date.getSeconds();

    return `${month} ${day} ${year} ${hours}:${minutes}:${seconds}`;
};

/** What a run that failed returned, as the provenance drawer names it. */
const RUN_ERROR = "ERROR";

/**
 * The kind of data each `dataType` names, by the names the sandbox gives them
 * (`detect_kind` in sandbox/util/codec.py): a port type, or an error for what
 * a failed run returned. A bundle of several values ("outputs") names none,
 * since its type does not say what it holds.
 */
const KIND_OF_DATA_TYPE = new Map<string, string>([
    ["int", SupportedType.VALUE],
    ["str", SupportedType.VALUE],
    ["float", SupportedType.VALUE],
    ["bool", SupportedType.VALUE],
    ["list", SupportedType.LIST],
    ["dict", SupportedType.JSON],
    ["dataframe", SupportedType.DATAFRAME],
    ["geodataframe", SupportedType.GEODATAFRAME],
    ["raster", SupportedType.RASTER],
    ["error", RUN_ERROR],
]);

const KIND_ORDER: string[] = [...Object.values(SupportedType), RUN_ERROR];

/**
 * The kinds of data a run read or returned, as the provenance drawer lists
 * them for each of a node's runs ("In: DATAFRAME | Out: GEODATAFRAME"): each kind
 * once, in the order of the port types. *dataTypes* is the `dataType` the data
 * carries, or a list of them.
 */
export const mapTypes = (dataTypes: string | string[] | null | undefined): string[] => {
    const given: unknown[] = Array.isArray(dataTypes) ? dataTypes : [dataTypes];
    const named = new Set(given.map((type) => (typeof type === "string" ? KIND_OF_DATA_TYPE.get(type) : undefined)));
    return KIND_ORDER.filter((kind) => named.has(kind));
};