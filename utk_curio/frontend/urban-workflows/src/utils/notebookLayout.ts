// The notebook view's geometry: where each cell sits, where its dots sit on
// the cell's right edge, which lane each connection takes in the bar, the
// path it draws there, and how tall a cell's output is. Pure, so the view and
// its tests share one set of numbers.
import { NodeType } from "../constants";
import { unversionedNodeType } from "./flowNodeCanonicalType";
import { inputSlotOf } from "./inputSlots";

/**
 * Cells span the page from its left margin to the bar on its right, as a
 * notebook's do; a cell's height is its content's, as React Flow measures it.
 * On a pane too narrow for that, a cell keeps this width and the page scrolls.
 */
export const NOTEBOOK_MIN_CELL_WIDTH = 480;
/** Room between two cells. */
export const NOTEBOOK_CELL_GAP = 24;
/** What a cell counts as until React Flow has measured it, a frame after it mounts. */
export const NOTEBOOK_UNMEASURED_HEIGHT = 240;
/** The strip right of the cells where the dots sit and the connections run. */
export const NOTEBOOK_BAR_WIDTH = 176;
/** Clearance from the top bar, the title chips and the palette rail. */
export const NOTEBOOK_MARGIN = 24;
/** Room below the last cell, so it can be scrolled clear of the window's bottom edge. */
export const NOTEBOOK_BOTTOM_SPACE = 160;
/** A dot's size (`.react-flow__handle-right` in Node.css). */
export const NOTEBOOK_DOT_SIZE = 20;

// Dots on a cell's right edge: inputs from just under the header down, the
// interaction dot halfway, the output near the bottom. Centers, in pixels from
// the cell's top or bottom edge.
const FIRST_INPUT = 52;
const OUTPUT_INSET = 36;
const DOT_PITCH = 22;
/** Clearance between two stacks of dots, center to center, more than a dot. */
const DOT_GAP = 22;

// Lanes in the bar: the first clears the dots (20px, drawn just outside the
// cell's edge), the rest step outward.
const LANE_START = 36;
const LANE_PITCH = 14;
const LANE_END_PAD = 12;
const CORNER = 8;

export type XY = { x: number; y: number };

export interface NotebookCell {
  id: string;
  /** The cell's height as React Flow measured it; none until it has. */
  height?: number | null;
}

/** The scrolling pane the cells live in, in its own pixels. */
export interface NotebookPane {
  width: number;
  /** Bottom of the overlays fixed along the pane's top (bar, title, chips). */
  top: number;
  /** Right edge of the palette rail along the pane's left. */
  left: number;
}

export interface NotebookLayout {
  positions: Map<string, XY>;
  rows: Map<string, number>;
  columnX: number;
  cellWidth: number;
  /** Left edge of the bar, which is the cells' right edge. */
  barX: number;
  contentHeight: number;
}

/**
 * One column of cells in the given order, each as tall as it was measured and
 * a gap below the one above, spanning the pane from its left margin to the bar
 * at its right edge, clear of its overlays.
 */
export function layoutNotebook(cells: readonly NotebookCell[], pane: NotebookPane): NotebookLayout {
  const columnX = Math.round(pane.left) + NOTEBOOK_MARGIN;
  const barX = Math.max(columnX + NOTEBOOK_MIN_CELL_WIDTH, Math.round(pane.width) - NOTEBOOK_BAR_WIDTH);
  const positions = new Map<string, XY>();
  const rows = new Map<string, number>();
  let y = Math.round(pane.top) + NOTEBOOK_MARGIN;
  cells.forEach((cell, row) => {
    const height = cell.height && cell.height > 0 ? cell.height : NOTEBOOK_UNMEASURED_HEIGHT;
    positions.set(cell.id, { x: columnX, y });
    rows.set(cell.id, row);
    y += height + NOTEBOOK_CELL_GAP;
  });
  const bottom = cells.length > 0 ? y - NOTEBOOK_CELL_GAP : y;
  return {
    positions,
    rows,
    columnX,
    cellWidth: barX - columnX,
    barX,
    contentHeight: bottom + NOTEBOOK_BOTTOM_SPACE,
  };
}

/**
 * What a viewer may change in the graph: nodes are added (dropped from the
 * rail, a catalog or a scenario), connected and deleted, and connections
 * removed, on the canvas only. The notebook view edits and runs cells and
 * changes no graph; a shared viewer changes nothing.
 */
export function graphEditGates({ notebookOn, sharedView }: { notebookOn: boolean; sharedView: boolean }) {
  const canvasEditor = !notebookOn && !sharedView;
  return { connect: canvasEditor, drop: canvasEditor, delete: canvasEditor };
}

export interface NotebookHandle {
  id: string;
  type: "source" | "target";
}

/**
 * A dot's place on a cell's right edge, as its style: a number of pixels from
 * the top, halfway, or from the bottom. `top: "auto"` goes inline with
 * `bottom`, because React Flow's right-handle rule sets `top: 50%`.
 */
export type NotebookDotPlace = { top: number } | { top: "50%" } | { top: "auto"; bottom: number };

function splitHandles(handles: readonly NotebookHandle[]) {
  return {
    inputs: handles.filter((h) => h.type === "target"),
    outputs: handles.filter((h) => h.type === "source" && h.id !== "in/out"),
    interaction: handles.some((h) => h.id === "in/out"),
  };
}

/**
 * Where each of a cell's dots sits, so it follows the cell as it grows. Inputs
 * keep the order the node lists them in (circle 0 first) at fixed offsets from
 * the top, the interaction dot is halfway down, and outputs go up from the
 * bottom. React Flow centers a right-side dot on its `top`, so a dot anchored
 * to the bottom sits one dot higher than its `bottom` says.
 */
export function notebookHandlePlaces(handles: readonly NotebookHandle[]): Map<string, NotebookDotPlace> {
  const { inputs, outputs, interaction } = splitHandles(handles);
  const places = new Map<string, NotebookDotPlace>();
  inputs.forEach((h, k) => places.set(h.id, { top: FIRST_INPUT + k * DOT_PITCH }));
  if (interaction) places.set("in/out", { top: "50%" });
  outputs.forEach((h, k) =>
    places.set(h.id, { top: "auto", bottom: OUTPUT_INSET + k * DOT_PITCH - NOTEBOOK_DOT_SIZE }));
  return places;
}

/** The least a cell can be: tall enough for its dots, none over another. */
export function notebookCellMinHeight(handles: readonly NotebookHandle[]): number {
  const { inputs, outputs, interaction } = splitHandles(handles);
  // From the top edge to just under the last input, and from the bottom edge
  // to just over the highest output.
  const above = inputs.length > 0 ? FIRST_INPUT + (inputs.length - 1) * DOT_PITCH + DOT_GAP : DOT_GAP;
  const below = outputs.length > 0 ? OUTPUT_INSET + (outputs.length - 1) * DOT_PITCH + DOT_GAP : DOT_GAP;
  // The interaction dot sits halfway, so each half holds one of the stacks.
  return interaction ? 2 * Math.max(above, below) : above + below;
}

/** A cell's box: the page's cell width, and at least tall enough for its dots. */
export function notebookCellBox(
  handles: readonly NotebookHandle[],
  cellWidth: number,
): { width: number; minHeight: number } {
  return { width: cellWidth, minHeight: notebookCellMinHeight(handles) };
}

// How tall a cell's output is. A chart or a map has no height of its own, so
// it gets a definite one to draw in; a table, a summary or a control takes its
// own, up to a cap, and scrolls inside past it.
const CHART_HEIGHT = 320;
const MAP_HEIGHT = 400;
const OUTPUT_CAP = 360;
// Built-ins NodeType does not list are named here as the registry ids they are.
const NATURAL_HEIGHT_KINDS: ReadonlySet<string> = new Set([
  NodeType.DATA_POOL,
  NodeType.VIS_SIMPLE,
  NodeType.DATA_SUMMARY,
  NodeType.DATA_EXPORT,
  "curio.builtin/parameter",
  "curio.builtin/spatial-join",
]);
const MAP_KINDS: ReadonlySet<string> = new Set([NodeType.AUTK_GRAMMAR, "curio.builtin/compare-scenarios"]);

export interface NotebookOutputBox {
  height?: number;
  maxHeight?: number;
  overflow?: "auto";
}

/**
 * The box a cell's output goes in, by the node's kind: a Vega-Lite chart's
 * mount is 320px, an Autark map or plot (and a Compare Scenarios chart or
 * difference map) 400px. Kinds whose body has a height of its own take it, up
 * to 360px. Anything else, a package's body made to fill a node, is 360px.
 */
export function notebookOutputBox(nodeType: string): NotebookOutputBox {
  const kind = unversionedNodeType(nodeType);
  if (kind === NodeType.VIS_VEGA) return { height: CHART_HEIGHT, overflow: "auto" };
  if (MAP_KINDS.has(kind)) return { height: MAP_HEIGHT };
  if (NATURAL_HEIGHT_KINDS.has(kind)) return { maxHeight: OUTPUT_CAP, overflow: "auto" };
  return { height: OUTPUT_CAP, overflow: "auto" };
}

/** What an input dot is called: the number `[!! input k !!]` uses, or a named input's name. */
export function notebookInputLabel(handleId: string): string {
  const slot = inputSlotOf(handleId);
  return slot >= 0 ? String(slot) : handleId.replace(/^in_/, "");
}

export interface NotebookEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
}

/** Where along its row an end of a connection sits, in rows, for telling spans apart. */
function rowPoint(row: number, handle: string | null | undefined, end: "source" | "target"): number {
  if (handle === "in/out") return row + 0.5;
  if (end === "source") return row + 0.9;
  return row + 0.1 + Math.max(0, inputSlotOf(handle)) * 0.001;
}

/**
 * A lane in the bar for every connection whose two cells are both laid out.
 * Shorter connections take the inner lanes; two that overlap vertically never
 * share one, so their vertical runs stay apart.
 */
export function assignNotebookLanes(
  edges: readonly NotebookEdge[],
  rows: ReadonlyMap<string, number>,
): { lanes: Map<string, number>; count: number } {
  const spans = edges
    .filter((e) => rows.has(e.source) && rows.has(e.target))
    .map((e) => {
      const a = rowPoint(rows.get(e.source)!, e.sourceHandle, "source");
      const b = rowPoint(rows.get(e.target)!, e.targetHandle, "target");
      return { id: e.id, from: Math.min(a, b), to: Math.max(a, b) };
    })
    .sort((p, q) =>
      (p.to - p.from) - (q.to - q.from) || p.from - q.from || (p.id < q.id ? -1 : p.id > q.id ? 1 : 0));

  const taken: { from: number; to: number }[][] = [];
  const lanes = new Map<string, number>();
  for (const span of spans) {
    let lane = 0;
    while (taken[lane]?.some((t) => t.from <= span.to && span.from <= t.to)) lane += 1;
    (taken[lane] ??= []).push(span);
    lanes.set(span.id, lane);
  }
  return { lanes, count: taken.length };
}

/** The x of a lane: inner lanes first, every lane inside the bar however many there are. */
export function notebookLaneX(barX: number, lane: number, count: number): number {
  const room = NOTEBOOK_BAR_WIDTH - LANE_START - LANE_END_PAD;
  const pitch = count > 1 ? Math.min(LANE_PITCH, room / (count - 1)) : LANE_PITCH;
  return Math.round(barX + LANE_START + lane * pitch);
}

/**
 * A connection in the bar: out from the source dot to its lane, along the lane,
 * and back in to the target dot, with rounded corners. Returns the path and the
 * point halfway along the lane, where labels and badges go.
 */
export function notebookArcPath(
  sourceX: number,
  sourceY: number,
  targetX: number,
  targetY: number,
  laneX: number,
): [string, number, number] {
  const dir = targetY >= sourceY ? 1 : -1;
  const r = Math.max(0, Math.min(CORNER, Math.abs(targetY - sourceY) / 2, laneX - Math.max(sourceX, targetX)));
  const path = [
    `M ${sourceX},${sourceY}`,
    `L ${laneX - r},${sourceY}`,
    `Q ${laneX},${sourceY} ${laneX},${sourceY + dir * r}`,
    `L ${laneX},${targetY - dir * r}`,
    `Q ${laneX},${targetY} ${laneX - r},${targetY}`,
    `L ${targetX},${targetY}`,
  ].join(" ");
  return [path, laneX, (sourceY + targetY) / 2];
}

/**
 * The React Flow settings that turn the canvas into a page: zoom held at 1,
 * no gesture moves the view, and the wheel is left to the page so it scrolls.
 * These hold gestures only; a call that sets the view directly (a fit) is put
 * back by MainCanvas. The connections are there to be read: none takes the
 * keyboard's focus (nor a click, MainCanvas.css), since one is selected only
 * to be deleted, which happens on the canvas.
 */
export function notebookFlowProps(paneWidth: number, paneHeight: number) {
  return {
    minZoom: 1,
    maxZoom: 1,
    translateExtent: [[0, 0], [paneWidth, paneHeight]] as [[number, number], [number, number]],
    zoomOnScroll: false,
    zoomOnPinch: false,
    zoomOnDoubleClick: false,
    panOnScroll: false,
    panOnDrag: false,
    preventScrolling: false,
    nodesDraggable: false,
    edgesFocusable: false,
  };
}
