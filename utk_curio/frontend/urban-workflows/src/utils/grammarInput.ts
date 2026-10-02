/**
 * The one path from a grammar node's `data.input` to the frames it draws.
 *
 * The Vega-Lite and Autark nodes read their input here: the same gate on what
 * they accept and the same sentence when they refuse, the same fetch (Arrow
 * first, JSON as the fallback), the same schema and geometry column. A
 * Vega-Lite spec draws one dataset. An Autark document also takes a bundle of
 * named layers (a tuple, a Data Pool with tabs, an upstream Autark node's
 * tables), and that is the only thing it asks of this module that Vega does not.
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

export type FrameType = "dataframe" | "geodataframe";

export type GrammarFrame = {
  /** The layer's own name, when it has one (a bundle item, a pool tab). */
  name: string | null;
  dataType: FrameType;
  /** A column-major frame or a FeatureCollection, as the wire carries it. */
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
  /** Accept bundles of named layers (Autark). */
  bundles?: boolean;
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
  place: { fromBundle: boolean; index: number; name?: string | null; layerType?: string },
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
  };
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
 * Bundle items that are references (a Merge node's slots) come back in
 * `refs` for the caller to fetch.
 */
export function framesFromPayload(value: any): {
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

  if (isObject(arg) && arg.dataType === "outputs" && Array.isArray(arg.data)) {
    arg.data.forEach((item: any, index: number) => {
      if (isObject(item) && typeof item.path === "string" && item.path) {
        refs.push({ index, ref: item });
      } else if (isObject(item) && FRAME_TYPES.has(item.dataType) && item.data != null) {
        frames.push(frameOf(item.dataType, item.data, item, null, { fromBundle: true, index }));
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
    typeof type === "string" && (FRAME_TYPES.has(type) || (!!opts.bundles && BUNDLE_TYPES.has(type)));

  // A reference that names its type is gated before anything is fetched.
  const declared: string | undefined = isObject(input) && typeof input.dataType === "string"
    ? input.dataType
    : undefined;
  if (declared !== undefined && !accepts(declared)) return refused(declared, opts.label);

  const read = (path: string) => (opts.preview ? fetchPreviewData(path) : fetchData(path));
  const envelope: any = isObject(input) && input.path ? await read(input.path) : input;
  if (envelope == null) return { frames: [] };

  // One restored without its type (a project saved without `data_type`) is
  // gated on what the artifact turns out to be.
  const dataType = declared ?? envelope.dataType;
  if (declared === undefined && !accepts(dataType)) return refused(dataType, opts.label);

  if (FRAME_TYPES.has(dataType)) {
    const payload = envelope.data;
    if (payload == null) return { frames: [] };
    return { frames: [frameOf(dataType, payload, envelope, input, { fromBundle: false, index: 0 })] };
  }

  const found = framesFromPayload(envelope);
  const frames = [...found.frames];
  const skipped = [...found.skipped];
  for (const { index, ref } of found.refs) {
    const fetched = await read(ref.path);
    const type = ref.dataType ?? fetched?.dataType;
    if (FRAME_TYPES.has(type) && fetched?.data != null) {
      frames.push(frameOf(type, fetched.data, fetched, ref, { fromBundle: true, index }));
    } else {
      skipped.push(`${type ?? "an item"} at position ${index}`);
    }
  }
  frames.sort((a, b) => a.index - b.index);

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
