/**
 * Simple View's player as a selection: what it has played of a video or a
 * recording, from the file's start to where it stands, as a range on a time
 * column. It goes out over Simple View's interaction edges as an interval does
 * from a brush on a chart's time axis, and every view that receives it
 * matches its own rows against it with the code a brush's interval goes
 * through (`selectionMatch`): a row is lit when its time is in the range.
 *
 * The range is in seconds, on the view's Time column (`timeColumnOf`): the
 * column the rows of the views linked to it keep their time in. Until the
 * view names another, it is `t_s`, the column Curio's media nodes give the
 * time in a video or a recording (Sample Video Frames' frames, Split Audio's
 * windows). A played row's own start stays its `t_s`, whatever the Time
 * column names: a played row that carries `t_s` is a part of a longer file
 * that starts there, such as Track Objects' overlay or Split Audio's clip, so
 * its times are that file's: an overlay that starts 50 s into its video plays
 * the range from 50 s to 50 s plus where it stands.
 */
import { NodeType, VisInteractionType } from "../constants";
import type { SelectDetail } from "./selectionMatch";

/** The time in a video or a recording, in seconds, as Curio's media nodes
 *  write it: a played row's own start in the file it was cut from, and the
 *  column a Simple View's Time column names until it names another. */
export const PLAYED_TIME_COLUMN = "t_s";

/** The Simple View widget that holds its Time column. */
export const TIME_COLUMN_WIDGET = "time_column";

/**
 * The column a Simple View's player's range names in the views linked to it:
 * the value of its Time column widget among *widgets*, the node's, or `t_s`
 * when the node holds no such widget (one saved before it had the setting)
 * or its value is empty.
 */
export function timeColumnOf(widgets: unknown): string {
  const held = Array.isArray(widgets)
    ? widgets.find((widget) => (widget as { name?: unknown } | null)?.name === TIME_COLUMN_WIDGET)
    : undefined;
  if (!held) return PLAYED_TIME_COLUMN;
  const { value, default: initial } = held as { value?: unknown; default?: unknown };
  const named = value !== undefined ? value : initial;
  return typeof named === "string" && named.trim() ? named.trim() : PLAYED_TIME_COLUMN;
}

/** The name of the player's select among Simple View's selects. */
export const PLAYER_SELECT = "player_time";

/** The name of a click on one of Simple View's cards. */
export const CARD_SELECT = "images_click";

/**
 * At most how often a playing player tells its range, in milliseconds. A
 * seek, a pause and a start tell it at once. Chrome tells a playing element's
 * time every 250 ms, so a player tells at each of those, about four times a
 * second.
 *
 * Measured on three of CI's GPU runners (11-08, tmp/player-linked-measure),
 * a Simple View linked to a Vega-Lite chart and an Autark map of the same
 * points: one update costs the page 20 to 30 ms of main thread with 900
 * points and 37 to 86 ms with 10,000 (the flow's renders, Vega's change and
 * Autark's `syncHighlights`, its read of the drawn rows included), five
 * seconds of play took 7 to 19% and 15 to 30% of the main thread, and no
 * video frame was dropped. The first update after a map draws also reads
 * the layer's rows back from autk-db once: 24 ms with 900 points, 183 ms
 * with 10,000.
 */
export const PLAYER_TELLS_EVERY_MS = 200;

/**
 * Where *row*'s file starts in the file it was cut from, when it is a part of
 * one: its `t_s`. Null for a whole file, whose row carries no `t_s`, or an
 * empty one where a table mixes whole files with parts.
 */
export function partStart(row: Record<string, unknown> | null | undefined): number | null {
  const value = row?.[PLAYED_TIME_COLUMN];
  if (value == null || value === "") return null;
  const start = Number(value);
  return Number.isFinite(start) ? start : null;
}

/** Where *row*'s file starts in the file it was cut from: its `t_s`, else 0. */
export function playedFrom(row: Record<string, unknown> | null | undefined): number {
  return partStart(row) ?? 0;
}

/**
 * A time in a file, in seconds, as a label says it: to the millisecond, as
 * Curio's media nodes round `t_s` (Split Video's blocks, Split Audio's
 * windows, Sample Video Frames' frames), with no trailing zeros: "0", "60",
 * "152.7", "2.345". So two parts of one file that start apart never read
 * alike, however short a block or a window is.
 */
export function secondsText(seconds: number): string {
  return String(Number(seconds.toFixed(3)));
}

/**
 * The range a player standing at *at* seconds into *row*'s file has played,
 * from the file's start to there, in the time of the file it was cut from.
 */
export function playedRange(row: Record<string, unknown> | null | undefined, at: number): [number, number] {
  const from = playedFrom(row);
  return [from, from + Math.max(0, at)];
}

/**
 * The player's select: an interval over *column*, the view's Time column,
 * that holds *range*, or, when the player closed, one that holds nothing,
 * which every view reads as a selection taken away. Its priority is the
 * caller's (`latestSelect`).
 */
export function playerSelect(
  range: [number, number] | null,
  column: string = PLAYED_TIME_COLUMN,
): SelectDetail & { source: string } {
  return {
    type: VisInteractionType.INTERVAL,
    data: range ? { [column]: range } : {},
    source: NodeType.VIS_SIMPLE,
  };
}

/**
 * Simple View's selects with *select* the latest of them, under *name*: as a
 * chart tells its selects, the one that changed has priority 1 and every
 * other keeps what it holds with priority 0.
 */
export function latestSelect(
  selects: Record<string, SelectDetail> | null | undefined,
  name: string,
  select: SelectDetail,
): Record<string, SelectDetail> {
  const next: Record<string, SelectDetail> = {};
  for (const [key, held] of Object.entries(selects ?? {})) next[key] = { ...held, priority: 0 };
  next[name] = { ...select, priority: 1 };
  return next;
}
