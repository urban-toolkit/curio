/**
 * The parts a Data Export node's input holds, as its zip names them.
 *
 * `curio_export` writes a tuple, a list or a dict that holds a table or a
 * raster as one zip, a file per part (sandbox/util/bundle_zip.py), and its
 * Part dropdown offers each of those parts. This reads them from the input as
 * the canvas has it, the envelope `/get` answers for it, and labels each as
 * the zip does (`part_label`): the label of the bundle part it was read from
 * (`metadata.partLabel`), its key in a dict, a frame's own layer name, its
 * kind and place. Any other input is written as one file, and has no parts.
 * `dataExportParts.cases.json` beside it holds the cases both sides run.
 *
 * The value the dropdown writes to the Part widget names one part as
 * `curio_export`'s `part` finds it (`bundle_zip.pick`): its label when no
 * other part has it, else its position from 0.
 */

/** One part of an input of several, in its order. */
export interface ExportPart {
  /** Its place, from 0. */
  index: number;
  /** Its label, which names its file in the zip. */
  label: string;
  /** Its key, in a dict. */
  key?: string;
}

/** A part's kind, as its label says it when nothing else names the part. */
const KIND_NAMES: Record<string, string> = {
  raster: "Raster",
  dataframe: "Table",
  geodataframe: "Geo table",
  list: "Array",
  dict: "Object",
  str: "Text",
  int: "Number",
  float: "Number",
  bool: "Flag",
  null: "Empty",
};

/** The kinds a zip writes as a file of their own. */
const FILE_KINDS = new Set(["dataframe", "geodataframe", "raster"]);
/** The envelopes that hold several values. */
const CONTAINERS = new Set(["outputs", "list", "dict"]);

const isRecord = (value: unknown): value is Record<string, any> =>
  value !== null && typeof value === "object" && !Array.isArray(value);

const isText = (value: unknown): value is string => typeof value === "string" && value !== "";

/** A part's label by its kind and its place: `Table · part 1`. */
export function kindLabel(index: number, kind: string): string {
  const base =
    KIND_NAMES[kind] ??
    kind
      .replace(/_/g, " ")
      .replace(/\w\S*/g, (word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase());
  return `${base} · part ${index + 1}`;
}

/** The kind of the value *item*, one envelope of an input's parts. */
function kindOf(item: unknown): string | null {
  if (!isRecord(item) || typeof item.dataType !== "string") return null;
  return item.dataType === "" ? "null" : item.dataType;
}

/** The label of the part *item* at *index*, its key *key* in a dict. */
function labelOf(item: unknown, index: number, key: string | undefined): string {
  const kind = kindOf(item) ?? "unknown";
  const record = isRecord(item) ? item : {};
  // A geo table keeps its metadata in its FeatureCollection, a table beside its rows.
  const metadata = kind === "geodataframe" ? record.data?.metadata : kind === "dataframe" ? record.metadata : null;
  const meta = isRecord(metadata) ? metadata : {};
  if (isText(meta.partLabel)) return meta.partLabel;
  if (key !== undefined) return key;
  if (kind === "geodataframe") {
    // A layer an Autark node hands on is named by it, unless it has a name of its own.
    if (isText(meta.name)) return meta.name;
    if (isText(record.layerName)) return record.layerName;
  }
  return kindLabel(index, kind);
}

/**
 * The parts *envelope*, an input's value as `/get` answers it, holds, in their
 * order, or null when `curio_export` writes it as one file: anything but a
 * tuple, a list or a dict that holds a table, a GeoDataFrame or a raster.
 */
export function exportParts(envelope: unknown): ExportPart[] | null {
  if (!isRecord(envelope) || !CONTAINERS.has(envelope.dataType)) return null;
  const data = envelope.data;
  const items: Array<[string | undefined, unknown]> =
    envelope.dataType === "dict"
      ? isRecord(data)
        ? Object.entries(data)
        : []
      : Array.isArray(data)
        ? data.map((item) => [undefined, item])
        : [];
  if (!items.some(([, item]) => FILE_KINDS.has(kindOf(item) ?? ""))) return null;
  return items.map(([key, item], index) => ({
    index,
    label: labelOf(item, index, key),
    ...(key !== undefined ? { key } : {}),
  }));
}

/** The value the Part widget gets for *part*: its label when no other part
 * has it, else its position. */
export function partValue(parts: readonly ExportPart[], part: ExportPart): string {
  const unique = parts.filter((other) => other.label === part.label).length === 1;
  return unique ? part.label : String(part.index);
}

/**
 * The part the Part widget's *value* names, as `curio_export` finds it
 * (`bundle_zip.pick`): a label, then a key, then a position from 0. Null for
 * empty (every part) and for a value no part has.
 */
export function partNamed(parts: readonly ExportPart[], value: string): ExportPart | null {
  if (value === "") return null;
  const byLabel = parts.find((part) => part.label === value);
  if (byLabel) return byLabel;
  const byKey = parts.find((part) => part.key !== undefined && part.key === value);
  if (byKey) return byKey;
  if (/^\d+$/.test(value.trim())) {
    const position = Number(value.trim());
    if (position < parts.length) return parts[position];
  }
  return null;
}
