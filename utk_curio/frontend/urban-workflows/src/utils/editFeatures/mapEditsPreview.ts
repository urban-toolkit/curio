/**
 * What an Autark map draws when Map Editor nodes feed it (#662), before and
 * after Commit edits: for each of its circles a Map Editor node feeds on a
 * data edge, that node's own input with the edits its code holds, as the
 * node's run hands it on (`curio_edit_features`): every layer under the name
 * the run gives it, edited by `applyFeatureEdits`, the node's new layers after
 * them. Every other circle draws as it came, and so does a circle whose node
 * cannot read its code, or has not been fed. The map still hands on what it
 * was fed: the edits the last Commit ran.
 *
 * Each frame of a circle is what the map reads from that node's output: the
 * output is made here as the run makes it, then read by `framesFromPayload`,
 * as the map reads the output the run stores, so the map's tables keep their
 * names whether it draws the edits made now or those the last run made.
 */
import { inputTableName } from "../../contracts/autkGrammar";
import { autkSourcesFrom } from "../autkInput";
import { framesFromPayload, type GrammarFrame, type GrammarInput } from "../grammarInput";
import { inputSlotOf, wiredInputSlots } from "../inputSlots";
import { editedCollection } from "./applyEdits";
import {
  NEW_LAYER_KEY,
  readEditFeaturesCode,
  type EditFeaturesSettings,
  type FeatureEdit,
  type NewLayerGeometry,
} from "./editFeatures";
import { circlesInto, isInteraction, isInteractionEdge, nodeCode } from "./mapLayerEdits";

/** The Autark layer type a new layer's features are drawn as (`NEW_LAYER_TYPES` in `feature_edits.py`). */
const NEW_LAYER_TYPES: Record<NewLayerGeometry, string> = { Point: "points", LineString: "polylines", Polygon: "polygons" };

/** A Map Editor node feeding one of a map's circles. */
export interface EditFeed {
  nodeId: string;
  /** The circle's place among the map's wired circles. */
  position: number;
  /** Whether the map has more than one wired circle, so its input is their bundle. */
  several: boolean;
  /** What the node is fed. */
  input: unknown;
  /** The edits its code holds. */
  settings: EditFeaturesSettings | undefined;
  /** How many circles its code hands the step (`by_input` with more than one). */
  circles: number;
}

/** Whether a Map Editor node feeds *mapId* on a data edge, whatever its code holds. */
export function fedByInteraction(mapId: string, nodes: readonly any[], edges: readonly any[]): boolean {
  return edges.some((edge) => edge.target === mapId && !isInteractionEdge(edge) && isInteraction(nodes.find((n) => n.id === edge.source)));
}

/**
 * The circles of *mapId* that Map Editor nodes feed, each with what its node
 * holds. A node whose code it cannot read, or that has not been fed, is left
 * out: the map draws what it handed on.
 */
export function editFeedsOf(mapId: string, nodes: readonly any[], edges: readonly any[]): EditFeed[] {
  const wired = wiredInputSlots(edges as any[], mapId);
  const out: EditFeed[] = [];
  for (const edge of edges) {
    if (edge.target !== mapId || isInteractionEdge(edge)) continue;
    const node = nodes.find((n) => n.id === edge.source);
    if (!isInteraction(node)) continue;
    const position = wired.indexOf(inputSlotOf(edge.targetHandle));
    const input = node.data?.input;
    const read = readEditFeaturesCode(nodeCode(node.data));
    if (position < 0 || input == null || input === "" || "problem" in read) continue;
    out.push({
      nodeId: node.id,
      position,
      several: wired.length > 1,
      input,
      settings: read.settings,
      circles: read.circles ?? circlesInto(node.id, edges),
    });
  }
  return out;
}

/** A key for what *feeds* make the map draw: it draws again when it changes. */
export function feedsVersion(feeds: readonly EditFeed[]): string {
  return JSON.stringify(feeds.map((feed) => [feed.nodeId, feed.position, feed.several, feed.circles, feed.input, feed.settings ?? null]));
}

/**
 * The table the map reads the layer *table* of a node's input by (its name
 * there, or `input_<k>` for its k-th unnamed layer), when the node feeds the
 * map's circle *feed*: its own name, and every layer's name when the node
 * hands the step several circles; else an unnamed layer goes by the map's own
 * circle, `input_<position>`, then `input_<position>_<k>`, when the map has
 * several.
 */
export function mapTableName(table: string, ownName: boolean, feed: Pick<EditFeed, "position" | "several" | "circles">): string {
  if (ownName || feed.circles > 1 || !feed.several) return table;
  const place = /^input_(\d+)$/.exec(table);
  if (!place) return table;
  const k = Number(place[1]);
  return k === 0 ? inputTableName(feed.position) : `${inputTableName(feed.position)}_${k}`;
}

/** *crs*, a CRS the node's code names (`EPSG:4326`), as the GeoJSON `crs` a layer names. */
function geojsonCrs(crs: string | undefined): unknown {
  const code = crs ? /^EPSG:(\d+)$/.exec(crs) : null;
  return code ? { type: "name", properties: { name: `urn:ogc:def:crs:EPSG::${code[1]}` } } : undefined;
}

/** The layer each edit applies to: the one it names, else the node's, else the only one there is. */
function targetOf(edit: FeatureEdit, settings: EditFeaturesSettings, only: string | undefined): string | undefined {
  return edit.layer ?? settings.layer ?? only;
}

/**
 * The value the node's run hands on (`curio_edit_features`), from its input
 * as read: null when it hands the input on as it came, which the map reads as
 * it is.
 */
export function editedOutput(read: GrammarInput, feed: Pick<EditFeed, "settings" | "circles">): unknown {
  const settings = feed.settings ?? {};
  const edits = settings.edits ?? [];
  const newLayers = settings.newLayers ?? [];
  const byInput = feed.circles > 1;
  if (edits.length === 0 && newLayers.length === 0 && !byInput) return null;
  const named = new Set(read.frames.map((frame) => frame.name).filter((name): name is string => !!name));
  const { sources } = autkSourcesFrom(read, {}, { alias: false });
  const only = sources.length === 1 ? sources[0].outputTableName : undefined;
  const envelopes: any[] = sources.map((source) => {
    const name = source.outputTableName;
    const mine = edits.filter((edit) => targetOf(edit, settings, only) === name);
    const key = settings.keys?.[name] ?? settings.key;
    const fc = mine.length > 0 && key ? editedCollection(source.geojsonObject, mine, key) : source.geojsonObject;
    const layerName = byInput || named.has(name) ? name : undefined;
    return {
      dataType: "geodataframe",
      data: fc,
      ...(layerName ? { layerName } : {}),
      ...(source.layerType ? { layerType: source.layerType } : {}),
    };
  });
  const crs = geojsonCrs(settings.crs) ?? (sources.find((source) => (source.geojsonObject as any)?.crs)?.geojsonObject as any)?.crs;
  for (const def of newLayers) {
    const mine = edits.filter((edit) => targetOf(edit, settings, only) === def.name);
    const fc = editedCollection({ type: "FeatureCollection", features: [] as any[] }, mine, NEW_LAYER_KEY);
    envelopes.push({
      dataType: "geodataframe",
      data: { ...fc, ...(crs ? { crs } : {}) },
      layerName: def.name,
      layerType: NEW_LAYER_TYPES[def.geometry],
    });
  }
  return envelopes.length === 1 ? envelopes[0] : { dataType: "outputs", data: envelopes };
}

/** The frames the map reads from the circle *feed* when its node hands on *value* (null: its input as it came). */
function circleFrames(value: unknown, read: GrammarInput, feed: EditFeed): GrammarFrame[] {
  const frames = value === null ? read.frames : framesFromPayload(value, { rasters: true }).frames;
  return feed.several ? frames.map((frame) => ({ ...frame, fromBundle: true, index: feed.position, circle: feed.position })) : frames;
}

/**
 * The map's input as it draws it: *own*, its input as read, with each circle
 * *feeds* names drawn from its node's input with the edits its code holds
 * (`readFed` reads a node's input). A circle whose node's input cannot be
 * read, or whose edits cannot apply (a run refuses them), draws as it came.
 */
export async function drawnInput(
  own: GrammarInput,
  feeds: readonly EditFeed[],
  readFed: (input: unknown) => Promise<GrammarInput>,
): Promise<GrammarInput> {
  if (feeds.length === 0) return own;
  let frames = [...own.frames];
  let drew = false;
  for (const feed of feeds) {
    let read: GrammarInput;
    try {
      read = await readFed(feed.input);
    } catch {
      continue;
    }
    if (read.emptyReason) continue;
    let made: GrammarFrame[];
    try {
      made = circleFrames(editedOutput(read, feed), read, feed);
    } catch {
      continue;
    }
    frames = feed.several ? frames.filter((frame) => frame.circle !== feed.position) : [];
    frames.push(...made);
    drew = true;
  }
  if (!drew) return own;
  frames.sort((a, b) => a.circle - b.circle || a.index - b.index);
  const { emptyReason: _reason, detail: _detail, ...rest } = own;
  return frames.length > 0 ? { ...rest, frames } : { ...own, frames };
}

/** The new layers *feeds* make, by the table the map reads each by. */
export function newLayerTables(feeds: readonly EditFeed[]): string[] {
  return feeds.flatMap((feed) => (feed.settings?.newLayers ?? []).map((def) => def.name));
}
