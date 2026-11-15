/**
 * Simple View's player as a selection: what it has played of a video or a
 * recording, from the file's start to where it stands, as a range on a time
 * column. It goes out over Simple View's interaction edges as an interval does
 * from a brush on a chart's time axis, and every view that receives it
 * matches its own rows against it with the code a brush's interval goes
 * through (`selectionMatch`): a row is lit when its time is in the range.
 *
 * The time is in seconds, in `t_s`: the column Curio's media nodes give the
 * time in a video or a recording (Sample Video Frames' frames, Split Audio's
 * windows). A played row that carries `t_s` is a part of a longer file that
 * starts there, such as Track Objects' overlay or Split Audio's clip, so its
 * times are that file's: an overlay that starts 50 s into its video plays the
 * range from 50 s to 50 s plus where it stands.
 */
import { NodeType, VisInteractionType } from "../constants";
import type { SelectDetail } from "./selectionMatch";

/** The column the player's range names: the time in the video, in seconds. */
export const PLAYED_TIME_COLUMN = "t_s";

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

/** Where *row*'s file starts in the file it was cut from: its `t_s`, else 0. */
export function playedFrom(row: Record<string, unknown> | null | undefined): number {
  const start = Number(row?.[PLAYED_TIME_COLUMN]);
  return Number.isFinite(start) ? start : 0;
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
 * The player's select: an interval over `t_s` that holds *range*, or, when
 * the player closed, one that holds nothing, which every view reads as a
 * selection taken away. Its priority is the caller's (`latestSelect`).
 */
export function playerSelect(range: [number, number] | null): SelectDetail & { source: string } {
  return {
    type: VisInteractionType.INTERVAL,
    data: range ? { [PLAYED_TIME_COLUMN]: range } : {},
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
