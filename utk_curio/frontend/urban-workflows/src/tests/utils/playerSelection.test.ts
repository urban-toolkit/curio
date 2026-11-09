/**
 * Simple View's player as a selection (utils/playerSelection): what it has
 * played, from its file's start to where it stands, as an interval on `t_s`,
 * which a view that receives it matches against its own rows with the code a
 * brush's interval goes through (utils/selectionMatch).
 *
 * The rows are a walk's points, one every 0.1 s, in a shuffled order, so the
 * points at the first row positions are not the first points walked. Each
 * case also checks that a wrong way of reading the player lights other rows
 * than the right way: by row position, only the point where it stands, or
 * everything it ever played.
 */
import { NodeType, VisInteractionType } from '../../constants';
import { isActiveSelect, matchSelections, objectRows } from '../../utils/selectionMatch';
import {
  CARD_SELECT,
  PLAYED_TIME_COLUMN,
  PLAYER_SELECT,
  latestSelect,
  playedFrom,
  playedRange,
  playerSelect,
} from '../../utils/playerSelection';

/** The order the points were handed over in: point k was walked at k / 10 s. */
const ORDER = [7, 2, 9, 0, 5, 10, 3, 8, 1, 6, 4];
const WALK = ORDER.map((k) => ({ label: `w${k}`, t_s: k / 10 }));
/** A row that holds no time, which no range lights. */
const UNTIMED = { label: 'untimed' };
const ROWS = objectRows([...WALK, UNTIMED]);

/** The labels the player's select, standing at *at* in *row*'s file, lights. */
function lit(at: number | null, row: Record<string, unknown> = {}): string[] {
  const details = latestSelect({}, PLAYER_SELECT, playerSelect(at === null ? null : playedRange(row, at)));
  const rows = [...WALK, UNTIMED];
  return matchSelections([{ details, priority: 1 }], ROWS).map((i) => rows[i].label).sort();
}

const walkedUpTo = (at: number) => WALK.filter((p) => p.t_s <= at).map((p) => p.label).sort();

/** The wrong ways: by row position, only the point where it stands, everything it played so far. */
const byPosition = (count: number) => WALK.slice(0, count).map((p) => p.label).sort();
const onlyAt = (at: number) => WALK.filter((p) => p.t_s === at).map((p) => p.label);

describe('the range a player has played', () => {
  test('runs from the start of a file that has no t_s to where it stands', () => {
    expect(playedRange({ name: 'clip.mp4' }, 4.25)).toEqual([0, 4.25]);
  });

  test("runs in the time of the video a part was cut from: an overlay's t_s is where it starts", () => {
    expect(playedFrom({ t_s: 50 })).toBe(50);
    expect(playedRange({ t_s: 50 }, 4)).toEqual([50, 54]);
  });

  test('a t_s that holds no number counts as the start', () => {
    expect(playedFrom({ t_s: null })).toBe(0);
    expect(playedFrom({ t_s: Number.NaN })).toBe(0);
    expect(playedFrom({ t_s: 'soon' })).toBe(0);
  });
});

describe("the player's select", () => {
  test('is an interval over t_s, sent from Simple View', () => {
    expect(playerSelect([0, 4.5])).toEqual({
      type: VisInteractionType.INTERVAL,
      data: { [PLAYED_TIME_COLUMN]: [0, 4.5] },
      source: NodeType.VIS_SIMPLE,
    });
    expect(isActiveSelect(playerSelect([0, 4.5]))).toBe(true);
  });

  test('a player that closed holds nothing, which takes the selection away', () => {
    expect(isActiveSelect(playerSelect(null))).toBe(false);
    expect(lit(null)).toEqual([]);
  });

  test('is the latest of its view\'s selects: the one before keeps what it holds, at priority 0', () => {
    const clicked = latestSelect({}, CARD_SELECT, { type: VisInteractionType.POINT, data: [3] });
    const played = latestSelect(clicked, PLAYER_SELECT, playerSelect([0, 2]));
    expect(played).toEqual({
      [CARD_SELECT]: { type: VisInteractionType.POINT, data: [3], priority: 0 },
      [PLAYER_SELECT]: { ...playerSelect([0, 2]), priority: 1 },
    });
    const clickedAgain = latestSelect(played, CARD_SELECT, { type: VisInteractionType.POINT, data: [1] });
    expect(clickedAgain[PLAYER_SELECT]).toEqual({ ...playerSelect([0, 2]), priority: 0 });
    expect(clickedAgain[CARD_SELECT].priority).toBe(1);
  });
});

describe('a view linked to the player lights the rows walked up to where it stands', () => {
  test('by their time, wherever they sit, the point exactly where it stands included', () => {
    const expected = walkedUpTo(0.4);
    expect(expected).toEqual(['w0', 'w1', 'w2', 'w3', 'w4']);
    expect(lit(0.4)).toEqual(expected);
    // Not the first rows handed over, nor the point where it stands alone.
    expect(byPosition(expected.length)).not.toEqual(expected);
    expect(onlyAt(0.4)).not.toEqual(expected);
  });

  test('a seek back lights fewer rows: what it played before is not kept', () => {
    expect(lit(0.75)).toEqual(walkedUpTo(0.75));
    const back = lit(0.25);
    expect(back).toEqual(['w0', 'w1', 'w2']);
    expect(back).not.toEqual(walkedUpTo(0.75));
  });

  test("an overlay's range starts where the overlay does", () => {
    // An overlay that starts 0.3 s into the walk, standing 0.2 s into itself.
    expect(lit(0.2, { t_s: 0.3 })).toEqual(['w3', 'w4', 'w5']);
  });

  test('a row with no time is never lit', () => {
    expect(lit(10)).toEqual(walkedUpTo(10));
    expect(lit(10)).not.toContain('untimed');
  });
});
