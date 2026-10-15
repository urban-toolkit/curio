/**
 * What a Data Loading node loads, read from its code (plans/data-loading-expressive-preview-memo.md).
 *
 * Two answers, both derived and never stored:
 *
 * - the **sources**: a Data Catalog dataset, a file on disk, an external API,
 *   data defined in the code, or a loader the rules do not recognise;
 * - the **data type**: the strongest evidence wins, in this order:
 *   the catalog record's format, what the code reads (a reader call or a file
 *   extension), the node's last run in this tab, the run journal (only for the
 *   code that is in the node now), the template's single declared output type,
 *   a background run, and otherwise nothing.
 *
 * The catalog ids come from `datasetIdsInCode`, the one scanner of
 * `curio_load_data` / `curio_data_path` / `curio_load_collection`, so the
 * preview and the lineage never read a loader differently.
 *
 * Addresses are what the preview prints, so they never carry a secret: an API is
 * shown by its host only (no path, no query, no user:pass@), and a
 * `curio_secret("…")` argument is never an address.
 */
import type { DatasetFormat } from "./datasetCatalogTypes";
import { datasetIdsInCode } from "./datasetLoaderSnippets";

export type LoaderSourceKind = "catalog" | "disk" | "api" | "inline" | "unknown";

/** A dataset format, or what a run or the code says when no format is known. */
export type LoaderDataType =
  | DatasetFormat
  | "dataframe"
  | "geodataframe"
  | "raster"
  | "unknown";

/** Where the data type came from, strongest first. */
export type LoaderTypeEvidence =
  | "catalog"
  | "code"
  | "run"
  | "journal"
  | "ports"
  | "probe"
  | "none";

export interface LoaderSource {
  kind: LoaderSourceKind;
  /** What the preview prints: a dataset id, a file path, an API host, a call. Never a secret. */
  address: string;
  /** The catalog title, when the dataset is known. */
  title?: string;
  /** Catalog sources only: the id that opens the dataset's details. */
  datasetId?: string;
  /** The type this one source reads, when it says. */
  dataType?: LoaderDataType;
}

export interface LoaderProfile {
  dataType: LoaderDataType;
  typeEvidence: LoaderTypeEvidence;
  /** In order of first appearance in the code; empty only for empty code. */
  sources: LoaderSource[];
  /** How many other data types the sources read (the preview shows "+N"). */
  extraTypes: number;
  /** The code reads a saved connection key, so it is never run without a click. */
  usesSecret: boolean;
  /** The code is over the scan cap: only its head was read, and it is never probed. */
  truncated: boolean;
}

/** What a catalog lookup gives the profile. */
export interface LoaderDatasetInfo {
  title?: string;
  format?: DatasetFormat;
}

export interface LoaderEvidence {
  /** The installed catalog dataset with this id, if any. */
  lookupDataset?: (datasetId: string) => LoaderDatasetInfo | undefined;
  /** The `dataType` of the node's last artifact in this tab (flow outputs). */
  runDataType?: string | null;
  /** The `dataType` of the journal's last run, already matched to this code. */
  journalDataType?: string | null;
  /** The template's declared output types, when it declares exactly one. */
  portTypes?: readonly string[] | null;
  /** The `dataType` a background run returned for this code. */
  probeDataType?: string | null;
}

/** Only the head of a pasted literal or a generated loader is read. */
export const LOADER_SCAN_CHARS = 64_000;

const DATA_EXTENSIONS: Record<string, DatasetFormat> = {
  csv: "csv",
  tsv: "csv",
  parquet: "parquet",
  pq: "parquet",
  geojson: "geojson",
  json: "json",
  shp: "shp",
  gpkg: "gpkg",
  tif: "geotiff",
  tiff: "geotiff",
  nc: "netcdf",
  nc4: "netcdf",
  pbf: "osm",
  osm: "osm",
};

// A literal that names a file: a data extension at its end (a URL's path, or a
// local path). `.zip`, `.xlsx` and the like name a file too but say nothing of
// its type, so they are files of unknown format.
const FILE_LITERAL_RE = /(["'])((?:[^"'\\\n]|\\.){1,400}?\.(?:csv|tsv|parquet|pq|geojson|json|shp|gpkg|tif|tiff|nc|nc4|pbf|osm|zip|xlsx|xls|feather|gz))\1/gi;
const URL_LITERAL_RE = /(["'])(https?:\/\/[^"'\s]{1,2000})\1/gi;
// A reader handed a literal path that has no recognised extension.
const READER_LITERAL_RE = /\b(?:read_csv|read_table|read_parquet|read_feather|read_excel|read_json|read_file|open_rasterio|open_dataset|open_mfdataset|rasterio\.open)\(\s*(["'])([^"'\n]{1,400})\1/g;
// A reader handed something else: a path built at run time.
const READER_CALL_RE = /\b(?:read_csv|read_table|read_parquet|read_feather|read_excel|read_json|read_file|open_rasterio|open_dataset|open_mfdataset|rasterio\.open)\(/;
// Socrata's client names the portal as its first argument: `Socrata("data.cityofchicago.org", …)`.
const SOCRATA_RE = /\bSocrata\(\s*(["'])([A-Za-z0-9.-]{1,253})\1/g;
const HTTP_CALL_RE = /\b(?:requests|httpx|session)\.(?:get|post|request)\(|\burlopen\(|\burllib\.request\b|\bfetch\(/;
const INLINE_RE = /\b(?:pd|pandas)\.DataFrame\(\s*[[{]|\b(?:gpd|geopandas)\.GeoDataFrame\(\s*[[{]|\bGeoDataFrame\(\s*[[{]|\bDataFrame\.from_(?:dict|records)\(\s*[[{]|^\s*return\s+[[{]/m;
const SECRET_RE = /\bcurio_secret\(/;

/** Remove `#` comments, leaving `#` inside string literals alone. */
export function stripPythonComments(code: string): string {
  const out: string[] = [];
  for (const line of code.split("\n")) {
    let quote: string | null = null;
    let cut = line.length;
    for (let i = 0; i < line.length; i += 1) {
      const ch = line[i];
      if (quote) {
        if (ch === "\\") i += 1;
        else if (ch === quote) quote = null;
      } else if (ch === '"' || ch === "'") {
        quote = ch;
      } else if (ch === "#") {
        cut = i;
        break;
      }
    }
    out.push(line.slice(0, cut));
  }
  return out.join("\n");
}

/**
 * The host of *url*, and nothing else: no scheme, path, query, fragment,
 * port or credentials. ``null`` when it is not a URL.
 */
export function urlHost(url: string): string | null {
  const m = /^[a-z][a-z0-9+.-]*:\/\/(?:[^@/?#\s]*@)?([^/?#:\s]+)/i.exec(url.trim());
  return m ? m[1].toLowerCase() : null;
}

/** The format a file name or a URL's path ends in, if it names one. */
export function formatOfPath(path: string): DatasetFormat | undefined {
  const withoutQuery = path.split(/[?#]/)[0];
  const m = /\.([A-Za-z0-9]{1,8})$/.exec(withoutQuery);
  return m ? DATA_EXTENSIONS[m[1].toLowerCase()] : undefined;
}

/** What a sandbox `dataType` says about a loader, or undefined when it says nothing useful. */
export function loaderTypeFromRunType(dataType: string | null | undefined): LoaderDataType | undefined {
  switch (String(dataType ?? "").trim().toLowerCase()) {
    case "dataframe":
      return "dataframe";
    case "geodataframe":
      return "geodataframe";
    case "raster":
      return "raster";
    case "dict":
    case "list":
      return "json";
    default:
      return undefined;
  }
}

/** A port type (`DATAFRAME`, `GEODATAFRAME`, `RASTER`, …) as a loader type. */
function loaderTypeFromPortType(type: string): LoaderDataType | undefined {
  return loaderTypeFromRunType(type.toLowerCase() === "json" ? "dict" : type);
}

/** What the code's reader calls say, when no source names a format. */
function codeReaderType(code: string): LoaderDataType | undefined {
  if (/\bcurio_load_collection\(/.test(code)) return "collection";
  if (/\bread_csv\(|\bread_table\(/.test(code)) return "csv";
  if (/\bread_parquet\(/.test(code)) return "parquet";
  if (/\bopen_mfdataset\(|\bxr\.open_dataset\(|\bxarray\.open_dataset\(/.test(code)) return "netcdf";
  if (/\bopen_rasterio\(|\brasterio\.open\(/.test(code)) return "geotiff";
  if (/\bread_json\(|\bjson\.loads?\(|\.json\(\)/.test(code)) return "json";
  if (/\bGeoDataFrame\(|\bgpd\.read_file\(|\bgeopandas\.read_file\(/.test(code)) return "geodataframe";
  if (/\bDataFrame\(/.test(code)) return "dataframe";
  return undefined;
}

/** The middle of a long path elided, keeping its file name whole. */
export function shortenPath(path: string, max = 48): string {
  if (path.length <= max) return path;
  const slash = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  const name = slash >= 0 ? path.slice(slash + 1) : path;
  if (name.length + 2 >= max) return `…${name.slice(-(max - 1))}`;
  return `${path.slice(0, max - name.length - 2)}…/${name}`;
}

interface Found {
  at: number;
  source: LoaderSource;
}

function findSources(code: string, lookup?: LoaderEvidence["lookupDataset"]): LoaderSource[] {
  const found: Found[] = [];
  const add = (at: number, source: LoaderSource) => {
    const key = `${source.kind}::${source.address}`;
    if (found.some((f) => `${f.source.kind}::${f.source.address}` === key)) return;
    found.push({ at, source });
  };

  for (const id of datasetIdsInCode(code)) {
    const info = lookup?.(id);
    add(code.indexOf(id), {
      kind: "catalog",
      address: id,
      datasetId: id,
      ...(info?.title ? { title: info.title } : {}),
      ...(info?.format ? { dataType: info.format } : {}),
    });
  }

  for (const m of code.matchAll(URL_LITERAL_RE)) {
    const host = urlHost(m[2]);
    if (!host) continue;
    const format = formatOfPath(m[2]);
    add(m.index ?? 0, { kind: "api", address: host, ...(format ? { dataType: format } : {}) });
  }
  for (const m of code.matchAll(SOCRATA_RE)) {
    add(m.index ?? 0, { kind: "api", address: m[2].toLowerCase() });
  }

  const catalogIds = new Set(found.map((f) => f.source.address));
  const fileAt = (literal: string, at: number) => {
    if (/^[a-z][a-z0-9+.-]*:\/\//i.test(literal)) return;
    if (catalogIds.has(literal)) return;
    const format = formatOfPath(literal);
    add(at, { kind: "disk", address: literal, ...(format ? { dataType: format } : {}) });
  };
  for (const m of code.matchAll(FILE_LITERAL_RE)) fileAt(m[2], m.index ?? 0);
  for (const m of code.matchAll(READER_LITERAL_RE)) fileAt(m[2], m.index ?? 0);

  if (found.length === 0 && HTTP_CALL_RE.test(code)) {
    // An API reached through a URL built at run time.
    add(code.search(HTTP_CALL_RE), { kind: "api", address: "" });
  }
  if (found.length === 0 && READER_CALL_RE.test(code)) {
    // A reader handed a path built at run time.
    add(code.search(READER_CALL_RE), { kind: "disk", address: "" });
  }
  if (found.length === 0 && INLINE_RE.test(code)) {
    add(code.search(INLINE_RE), { kind: "inline", address: "" });
  }

  return found.sort((a, b) => a.at - b.at).map((f) => f.source);
}

const EMPTY_PROFILE: LoaderProfile = {
  dataType: "unknown",
  typeEvidence: "none",
  sources: [],
  extraTypes: 0,
  usesSecret: false,
  truncated: false,
};

/** Whether *code* has anything to load: not empty, not only comments. */
export function hasLoaderCode(code: unknown): boolean {
  return typeof code === "string" && stripPythonComments(code).trim().length > 0;
}

/**
 * The profile of a loader's *code*, with whatever *evidence* the caller has.
 * Pure: the same code and evidence always give the same profile.
 */
export function detectLoaderProfile(code: unknown, evidence: LoaderEvidence = {}): LoaderProfile {
  if (!hasLoaderCode(code)) return EMPTY_PROFILE;
  const raw = code as string;
  const truncated = raw.length > LOADER_SCAN_CHARS;
  const scanned = stripPythonComments(truncated ? raw.slice(0, LOADER_SCAN_CHARS) : raw);

  let sources = findSources(scanned, evidence.lookupDataset);
  if (sources.length === 0) sources = [{ kind: "unknown", address: "" }];
  const usesSecret = SECRET_RE.test(scanned);

  const sourceTypes = sources
    .map((s) => s.dataType)
    .filter((t): t is LoaderDataType => !!t && t !== "unknown");
  const distinct = Array.from(new Set(sourceTypes));
  const fromCatalog = sources.find((s) => s.kind === "catalog" && s.dataType)?.dataType;

  const pick = (): { dataType: LoaderDataType; typeEvidence: LoaderTypeEvidence } => {
    // The first source's type leads; a catalog record outranks a guess from a
    // file name only when it is that first source.
    const first = sources.find((s) => s.dataType)?.dataType;
    if (first) {
      return { dataType: first, typeEvidence: first === fromCatalog && sources[0].kind === "catalog" ? "catalog" : "code" };
    }
    const reader = codeReaderType(scanned);
    if (reader) return { dataType: reader, typeEvidence: "code" };
    const run = loaderTypeFromRunType(evidence.runDataType);
    if (run) return { dataType: run, typeEvidence: "run" };
    const journal = loaderTypeFromRunType(evidence.journalDataType);
    if (journal) return { dataType: journal, typeEvidence: "journal" };
    const ports = (evidence.portTypes ?? []).map(loaderTypeFromPortType).filter(Boolean);
    if (ports.length === 1 && evidence.portTypes?.length === 1) {
      return { dataType: ports[0] as LoaderDataType, typeEvidence: "ports" };
    }
    const probe = loaderTypeFromRunType(evidence.probeDataType);
    if (probe) return { dataType: probe, typeEvidence: "probe" };
    return { dataType: "unknown", typeEvidence: "none" };
  };

  const { dataType, typeEvidence } = pick();
  return {
    dataType,
    typeEvidence,
    sources,
    extraTypes: Math.max(0, distinct.filter((t) => t !== dataType).length),
    usesSecret,
    truncated,
  };
}

/**
 * Whether a background run may find this loader's type: the code says
 * nothing, it is short enough to have been read whole, and it does not spend a
 * saved connection key on an API the user did not ask to call.
 */
export function needsTypeProbe(profile: LoaderProfile): boolean {
  if (profile.dataType !== "unknown") return false;
  if (profile.sources.length === 0) return false;
  if (profile.truncated) return false;
  if (profile.usesSecret && profile.sources.some((s) => s.kind === "api")) return false;
  return true;
}

/** The `dataType` of an artifact as the flow's outputs hold it (an object or its JSON). */
export function artifactDataType(output: unknown): string | null {
  let value = output;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch {
      return null;
    }
  }
  if (value && typeof value === "object" && typeof (value as any).dataType === "string") {
    return (value as any).dataType;
  }
  return null;
}
