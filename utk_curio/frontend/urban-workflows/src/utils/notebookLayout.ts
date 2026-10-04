// The notebook view's geometry: where each cell sits, where its dots sit on
// the cell's right edge, which lane each connection takes in the bar, and the
// path it draws there. Pure, so the view and its tests share one set of numbers.
import { inputSlotOf } from "./inputSlots";

/**
 * Every cell is the size of a dashboard tile's default (`dashboardLayout.ts`):
 * the content of a page rather than a node among fifty.
 */
export const NOTEBOOK_CELL_WIDTH = 880;
export const NOTEBOOK_CELL_HEIGHT = 560;
/** An icon-only node has no body, so it gets a row with room for Merge Flow's five circles. */
export const NOTEBOOK_SLIM_HEIGHT = 120;
export const NOTEBOOK_CELL_GAP = 32;
/** The strip right of the cells where the dots sit and the connections run. */
export const NOTEBOOK_BAR_WIDTH = 176;
/** Clearance from the top bar, the title chips and the palette rail. */
export const NOTEBOOK_MARGIN = 24;
/** Room below the last cell, so it can be scrolled clear of the window's bottom edge. */
export const NOTEBOOK_BOTTOM_SPACE = 160;

// Dots on a cell's right edge: inputs from just under the title band down,
// the interaction dot halfway, the output near the bottom.
const FIRST_INPUT = 52;
const FIRST_INPUT_SLIM = 16;
const OUTPUT_INSET = 36;
const OUTPUT_INSET_SLIM = 16;
const DOT_PITCH = 22;
const DOT_GAP = 16;

// Lanes in the bar: the first clears the dots (20px, drawn just outside the
// cell's edge), the rest step outward.
const LANE_START = 36;
const LANE_PITCH = 14;
const LANE_END_PAD = 12;
const CORNER = 8;

export type XY = { x: number; y: number };

export interface NotebookCell {
  id: string;
  /** An icon-only node, drawn as a short row. */
  slim: boolean;
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
  heights: Map<string, number>;
  rows: Map<string, number>;
  columnX: number;
  /** Left edge of the bar, which is the cells' right edge. */
  barX: number;
  contentHeight: number;
}

/** One column of cells in the given order, centered in the pane and clear of its overlays. */
export function layoutNotebook(cells: readonly NotebookCell[], pane: NotebookPane): NotebookLayout {
  const centered = Math.round((pane.width - (NOTEBOOK_CELL_WIDTH + NOTEBOOK_BAR_WIDTH)) / 2);
  const columnX = Math.max(Math.round(pane.left) + NOTEBOOK_MARGIN, centered);
  const positions = new Map<string, XY>();
  const heights = new Map<string, number>();
  const rows = new Map<string, number>();
  let y = Math.round(pane.top) + NOTEBOOK_MARGIN;
  cells.forEach((cell, row) => {
    const height = cell.slim ? NOTEBOOK_SLIM_HEIGHT : NOTEBOOK_CELL_HEIGHT;
    positions.set(cell.id, { x: columnX, y });
    heights.set(cell.id, height);
    rows.set(cell.id, row);
    y += height + NOTEBOOK_CELL_GAP;
  });
  const bottom = cells.length > 0 ? y - NOTEBOOK_CELL_GAP : y;
  return {
    positions,
    heights,
    rows,
    columnX,
    barX: columnX + NOTEBOOK_CELL_WIDTH,
    contentHeight: bottom + NOTEBOOK_BOTTOM_SPACE,
  };
}

export interface NotebookHandle {
  id: string;
  type: "source" | "target";
}

/**
 * How far below a cell's top each of its dots sits. Inputs keep the order the
 * node lists them in (circle 0 first), closing up when there are more than
 * fit above the interaction dot or the output.
 */
export function notebookHandleOffsets(handles: readonly NotebookHandle[], height: number): Map<string, number> {
  const slim = height < NOTEBOOK_CELL_HEIGHT;
  const inputs = handles.filter((h) => h.type === "target");
  const outputs = handles.filter((h) => h.type === "source" && h.id !== "in/out");
  const interaction = handles.some((h) => h.id === "in/out");
  const first = slim ? FIRST_INPUT_SLIM : FIRST_INPUT;
  const outputTop = height - (slim ? OUTPUT_INSET_SLIM : OUTPUT_INSET);
  const middle = Math.round(height / 2);
  const limit = (interaction ? middle : outputTop - Math.max(0, outputs.length - 1) * DOT_PITCH) - DOT_GAP;
  const pitch = inputs.length > 1 ? Math.min(DOT_PITCH, (limit - first) / (inputs.length - 1)) : 0;

  const offsets = new Map<string, number>();
  inputs.forEach((h, k) => offsets.set(h.id, Math.round(first + k * pitch)));
  if (interaction) offsets.set("in/out", middle);
  outputs.forEach((h, k) => offsets.set(h.id, outputTop - k * DOT_PITCH));
  return offsets;
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
 * With the translate extent equal to the pane, any fit or center call lands
 * back on the identity viewport.
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
  };
}
