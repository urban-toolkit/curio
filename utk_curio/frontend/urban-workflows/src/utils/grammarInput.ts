/**
 * The one path from a grammar node's `data.input` to the frames it draws.
 *
 * The Vega-Lite and Autark nodes read their input here: the same gate on what
 * they accept and the same sentence when they refuse, the same fetch (Arrow
 * first, JSON as the fallback), the same schema and geometry column. Both take
 * several inputs, one per input circle, which arrive as an `outputs` bundle:
 * each becomes its own frame. An Autark document also takes an input that is
 * itself a bundle of named layers (a tuple, a Data Pool with tabs, an upstream
 * Autark node's tables), and a raster; those are the only things it asks of
 * this module that Vega does not. A raster is not fetched here: its frame says
 * where it is (an artifact, or one part of a tuple) or holds the collection an
 * upstream Autark node handed on, and the Autark node loads it.
 *
 * Never throws for an input problem: a refusal comes back as an `emptyReason`
 * and a `detail` the node shows in its body.
 *
 * No parsing of rows here, and no `vega` import: callers decide what to
 * materialize, and this stays testable under jest.
 */
import { fetchData, fetchPreviewData } from "../services/api";
import { AUTARK_LAYER_TYPES } from "./autarkLayerTypes";
import type { NodeEmptyReason } from "./nodeEmptyState";
import { activeGeometryName } from "./parsing";

export type FrameType = "dataframe" | "geodataframe" | "raster";

/**
 * Where a raster frame's raster is: an artifact (a Python node's rasterio
 * dataset, `part` naming its place in a tuple), or the envelope an upstream
 * Autark node handed on (utils/raster/rasterWire).
 */
export type RasterPayload =
  | { artifact: string; part?: number }
  | { envelope: any };

export type GrammarFrame = {
  /** The layer's own name, when it has one (a bundle item, a pool tab). */
  name: string | null;
  dataType: FrameType;
  /** A column-major frame or a FeatureCollection, as the wire carries it; for
   * a raster, a `RasterPayload`. */
  payload: any;
  /** Column name to pandas dtype, when the envelope carries one. */
  schema: Record<string, string> | null;
  /** The column the payload declares as its geometry (geodataframes only). */
  geometryName: string | null;
  /** The CRS urn a geodataframe declares, e.g. `urn:ogc:def:crs:EPSG::3395`. */
  crsName: string | null;
  /** The autk-db layer type (`roads`, `buildings`, ...) a layer record carries or a geodataframe's metadata names. */
  layerType?: string;
  /** Came out of a bundle, so it is named by position when it has no name. */
  fromBundle: boolean;
  /** Its position in the bundle. */
  index: number;
  /** The position of the input it came from, among the node's inputs: its
   * bundle position, or 0 for a single input and for the layers of one. */
  circle: number;
};

export type GrammarInput = {
  frames: GrammarFrame[];
  /** Set when the node has nothing to draw from this input and should say why. */
  emptyReason?: NodeEmptyReason;
  /** The sentence the node shows for it. */
  detail?: string;
  /** Bundle items that are not layers, named so the node can say so. */
  skipped?: string[];
};

export type ReadOptions = {
  /** What the node is called in a refusal: "the 2D Plot (Vega-Lite)". */
  label: string;
  /** Accept bundles of named layers (Autark), and expand an input that holds
   * layers into them. */
  bundles?: boolean;
  /** Accept several inputs, one frame each (an `outputs` bundle), but no
   * other bundle (Vega-Lite). */
  circles?: boolean;
  /** Accept rasters, as frames that say where the raster is (Autark). */
  rasters?: boolean;
  /** Read the 100-row preview instead of the whole artifact (starter specs). */
  preview?: boolean;
};

const FRAME_TYPES = new Set<string>(["dataframe", "geodataframe"]);
const BUNDLE_TYPES = new Set<string>(["outputs", "list", "dict"]);

/**
 * The layer type a geodataframe's own metadata names (`gdf.metadata =
 * {"layerType": "buildings"}`), which the sandbox sends with its rows.
 */
function declaredLayerType(payload: any): string | undefined {
  const declared = isObject(payload?.metadata) ? payload.metadata.layerType : undefined;
  return typeof declared === "string" && AUTARK_LAYER_TYPES.has(declared) ? declared : undefined;
}

function isObject(value: unknown): value is Record<string, any> {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

function refused(dataType: unknown, label: string): GrammarInput {
  return {
    frames: [],
    emptyReason: "input-type-rejected",
    detail: `${dataType} is not a valid input type for ${label}.`,
  };
}

function frameOf(
  dataType: FrameType,
  payload: any,
  envelope: any,
  input: any,
  place: { fromBundle: boolean; index: number; circle?: number; name?: string | null; layerType?: string },
): GrammarFrame {
  const geo = dataType === "geodataframe";
  return {
    name: place.name ?? envelope?.layerName ?? null,
    dataType,
    payload,
    // The dtypes sit BESIDE `data` on parseOutput's envelope; a FeatureCollection
    // assembled elsewhere may carry its own.
    schema: envelope?.schema ?? payload?.schema ?? input?.schema ?? null,
    geometryName: geo ? activeGeometryName(payload) : null,
    crsName: geo ? payload?.crs?.properties?.name ?? null : null,
    layerType: place.layerType ?? envelope?.layerType ?? (geo ? declaredLayerType(payload) : undefined),
    fromBundle: place.fromBundle,
    index: place.index,
    circle: place.circle ?? 0,
  };
}

type RasterOptions = { rasters?: boolean; source?: string };

function rasterFrameOf(
  payload: RasterPayload,
  name: string | null,
  place: { fromBundle: boolean; index: number; circle?: number },
): GrammarFrame {
  return {
    name,
    dataType: "raster",
    payload,
    schema: null,
    geometryName: null,
    crsName: null,
    layerType: "raster",
    fromBundle: place.fromBundle,
    index: place.index,
    circle: place.circle ?? 0,
  };
}

/**
 * The frame for a `{dataType: "raster"}` value: the collection it holds, or,
 * for a Python raster (its data is the file's path), the artifact `source`
 * that holds it, with `part` its place in a tuple. Null when rasters are not
 * read or there is nothing to say where it is.
 */
function rasterFrame(
  item: any,
  opts: RasterOptions,
  place: { fromBundle: boolean; index: number; circle?: number; part?: number },
): GrammarFrame | null {
  if (!opts.rasters || !isObject(item) || item.dataType !== "raster") return null;
  const name = typeof item.layerName === "string" && item.layerName ? item.layerName : null;
  if (isObject(item.data) && item.data.type === "FeatureCollection") {
    return rasterFrameOf({ envelope: item }, name, place);
  }
  if (typeof item.data === "string" && opts.source) {
    const payload: RasterPayload = place.part == null
      ? { artifact: opts.source }
      : { artifact: opts.source, part: place.part };
    return rasterFrameOf(payload, name, place);
  }
  return null;
}

/** Strip Curio's `{dataType, data}` envelopes down to the value inside. */
function unwrap(value: any): any {
  return isObject(value) && "data" in value && "dataType" in value ? unwrap(value.data) : value;
}

function asFeatureCollection(value: any): any | null {
  const inner = unwrap(value);
  if (!isObject(inner)) return null;
  if (inner.geojson?.type === "FeatureCollection") return inner.geojson;
  if (inner.type === "FeatureCollection") return inner;
  return null;
}

/**
 * The layers in an already-fetched payload, peeling the envelopes the sandbox
 * adds around a persisted artifact. No gate and no aliasing: the Autark node
 * also reads its own backend-loaded tables through this.
 *
 * Bundle items that are references (a node's input circles) come back in
 * `refs` for the caller to fetch.
 *
 * With `rasters`, a raster becomes a frame too; `source` is the artifact the
 * payload was read from, which is where a Python raster in it is loaded from.
 */
export function framesFromPayload(value: any, opts: RasterOptions = {}): {
  frames: GrammarFrame[];
  refs: Array<{ index: number; ref: any }>;
  skipped: string[];
} {
  const frames: GrammarFrame[] = [];
  const refs: Array<{ index: number; ref: any }> = [];
  const skipped: string[] = [];
  if (value == null || value === "") return { frames, refs, skipped };

  // Peel generic envelopes (`dict`, `list`, ...) until a shape this reads.
  let arg: any = value;
  while (
    isObject(arg)
    && typeof arg.dataType === "string"
    && arg.dataType !== "outputs"
    && !(opts.rasters && arg.dataType === "raster")
    && !FRAME_TYPES.has(arg.dataType)
    && "data" in arg
  ) {
    arg = arg.data;
  }
  if (arg == null) return { frames, refs, skipped };

  if (isObject(arg) && FRAME_TYPES.has(arg.dataType)) {
    if (arg.data != null) {
      frames.push(frameOf(arg.dataType, arg.data, arg, null, { fromBundle: false, index: 0 }));
    }
    return { frames, refs, skipped };
  }

  if (isObject(arg) && arg.dataType === "raster") {
    const frame = rasterFrame(arg, opts, { fromBundle: false, index: 0 });
    if (frame) frames.push(frame);
    else skipped.push("raster at position 0");
    return { frames, refs, skipped };
  }

  if (isObject(arg) && arg.dataType === "outputs" && Array.isArray(arg.data)) {
    arg.data.forEach((item: any, index: number) => {
      const raster = rasterFrame(item, opts, { fromBundle: true, index, circle: index, part: index });
      if (isObject(item) && typeof item.path === "string" && item.path) {
        refs.push({ index, ref: item });
      } else if (isObject(item) && FRAME_TYPES.has(item.dataType) && item.data != null) {
        frames.push(frameOf(item.dataType, item.data, item, null, { fromBundle: true, index, circle: index }));
      } else if (raster) {
        frames.push(raster);
      } else {
        skipped.push(`${isObject(item) ? item.dataType ?? "an item" : "an item"} at position ${index}`);
      }
    });
    return { frames, refs, skipped };
  }

  // A layer array from an upstream Autark node: `{name, type, geojson}` records.
  if (Array.isArray(arg)) {
    arg.forEach((item: any, index: number) => {
      const fc = asFeatureCollection(item);
      if (!fc) {
        skipped.push(`an item at position ${index}`);
        return;
      }
      const record = unwrap(item);
      const name = isObject(record) && record.name ? String(record.name) : null;
      // A record's `type` is its autk-db layer type; a bare FeatureCollection's
      // own `type` is not.
      const layerType = isObject(record) && record.geojson && typeof record.type === "string"
        ? record.type
        : undefined;
      frames.push(frameOf("geodataframe", fc, null, null, { fromBundle: true, index, name, layerType }));
    });
    return { frames, refs, skipped };
  }

  // A bare FeatureCollection, or `{geojson: FeatureCollection}`.
  const fc = asFeatureCollection(arg);
  if (fc) frames.push(frameOf("geodataframe", fc, null, null, { fromBundle: false, index: 0 }));
  return { frames, refs, skipped };
}

/** Turn `data.input` into the frames a grammar node draws. */
export async function readGrammarInput(input: any, opts: ReadOptions): Promise<GrammarInput> {
  if (input == null || input === "") return { frames: [] };

  const accepts = (type: unknown) =>
    typeof type === "string" && (
      FRAME_TYPES.has(type)
      || (!!opts.bundles && BUNDLE_TYPES.has(type))
      || (!!opts.circles && type === "outputs")
      || (!!opts.rasters && type === "raster")
    );

  // A reference that names its type is gated before anything is fetched.
  const declared: string | undefined = isObject(input) && typeof input.dataType === "string"
    ? input.dataType
    : undefined;
  if (declared !== undefined && !accepts(declared)) return refused(declared, opts.label);

  // A reference can name the table it is read as, as an envelope's
  // `layerName` does: Compare Scenarios' difference map names it after what
  // it maps (#662).
  const named = isObject(input) && typeof input.layerName === "string" && input.layerName ? input.layerName : null;

  // A raster artifact is not fetched here: the frame names it, and the node
  // asks for the raster itself when it loads it.
  if (declared === "raster" && isObject(input) && typeof input.path === "string" && input.path) {
    return { frames: [rasterFrameOf({ artifact: input.path }, named, { fromBundle: false, index: 0 })] };
  }

  const read = (path: string) => (opts.preview ? fetchPreviewData(path) : fetchData(path));
  const source = isObject(input) && typeof input.path === "string" && input.path ? input.path : undefined;
  const envelope: any = source ? await read(source) : input;
  if (envelope == null) return { frames: [] };

  // One restored without its type (a project saved without `data_type`) is
  // gated on what the artifact turns out to be.
  const dataType = declared ?? envelope.dataType;
  if (declared === undefined && !accepts(dataType)) return refused(dataType, opts.label);

  if (FRAME_TYPES.has(dataType)) {
    const payload = envelope.data;
    if (payload == null) return { frames: [] };
    return { frames: [frameOf(dataType, payload, envelope, input, { fromBundle: false, index: 0, name: named })] };
  }

  const rasterOpts: RasterOptions = { rasters: opts.rasters };
  const found = framesFromPayload(envelope, { ...rasterOpts, source });
  const frames = [...found.frames];
  const skipped = [...found.skipped];
  for (const { index, ref } of found.refs) {
    if (opts.rasters && ref.dataType === "raster") {
      frames.push(rasterFrameOf({ artifact: ref.path }, null, { fromBundle: true, index, circle: index }));
      continue;
    }
    const fetched = await read(ref.path);
    const type = ref.dataType ?? fetched?.dataType;
    if (FRAME_TYPES.has(type) && fetched?.data != null) {
      frames.push(frameOf(type, fetched.data, fetched, ref, { fromBundle: true, index, circle: index }));
      continue;
    }
    // An input that is itself a bundle of layers (an Autark node's tables, a
    // tuple, a pool with tabs) or a raster brings each of them, under the
    // input's position.
    const inner = (opts.bundles || opts.rasters) && fetched != null
      ? framesFromPayload(fetched, { ...rasterOpts, source: ref.path }).frames.filter(
        (frame) => opts.bundles || frame.dataType === "raster",
      )
      : [];
    if (inner.length > 0) {
      for (const frame of inner) frames.push({ ...frame, fromBundle: true, index, circle: index });
    } else {
      skipped.push(`${type ?? "an item"} at position ${index}`);
    }
  }
  // Stable, so the layers one input brought keep their order.
  frames.sort((a, b) => a.circle - b.circle || a.index - b.index);

  if (frames.length === 0) {
    return {
      frames: [],
      emptyReason: "input-type-rejected",
      detail: `This ${dataType} holds nothing ${opts.label} can draw.`,
      ...(skipped.length ? { skipped } : {}),
    };
  }
  return { frames, ...(skipped.length ? { skipped } : {}) };
}
