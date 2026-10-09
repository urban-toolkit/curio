/**
 * The fixture of the keyed-selection tests: units a view picks, and readings
 * of those units another view draws (#847's bug class).
 *
 * Units: unit_id 101 to 106, never a row position, with a name and a height
 * (103 and 106 share one). A map draws them in another order than they came:
 * autk-db stores the rows without geometry first, and Curio hands it a first
 * row without geometry second (utils/autkInput `loadableSource`), so the input
 * row behind a drawn position is not the row at that position. One drawn
 * square, the yard, holds no unit_id.
 *
 * Readings: three per unit, taken in rounds of a shuffled order, so the
 * reading at each unit's row position belongs to another unit, plus one whose
 * unit_id is the text "103". They have no height.
 *
 * `expectDiscriminates` fails when a wrong way of matching a selection marks
 * what the right way marks, so an edit of the fixture cannot quietly stop a
 * test from telling them apart.
 */
import type { FeatureCollection } from "geojson";

/** The units' properties, in input order. Rows 0 and 4 have no geometry. */
export const UNIT_PROPERTIES: Array<Record<string, unknown>> = [
  { name: "Depot", height: 6 },
  { unit_id: 104, name: "Delta", height: 12 },
  { unit_id: 103, name: "Charlie", height: 18 },
  { unit_id: 101, name: "Alpha", height: 30 },
  { name: "Shed", height: 3 },
  { unit_id: 106, name: "Foxtrot", height: 18 },
  { unit_id: 102, name: "Bravo", height: 24 },
  { unit_id: 105, name: "Echo", height: 9 },
  { name: "Yard", height: 15 },
];
const UNDRAWN = new Set([0, 4]);

/** The input row of each unit. */
export const UNIT_ROW: Record<number, number> = { 104: 1, 103: 2, 101: 3, 106: 5, 102: 6, 105: 7 };
/** The drawn square that holds no unit_id. */
export const YARD_ROW = 8;
/** The input row a map draws at each position, as autk-db stores the table. */
export const MAP_ORDER = [0, 4, 1, 2, 3, 5, 6, 7, 8];
/** The input row a plot holds at each position, as Curio loads the table. */
export const LOAD_ORDER = [1, 0, 2, 3, 4, 5, 6, 7, 8];

/** Where the map draws input row *row*. */
export const drawnAt = (row: number): number => MAP_ORDER.indexOf(row);

const square = (column: number, line: number) => {
  const x = -87.64 + column * 0.002;
  const y = 41.87 + line * 0.002;
  return {
    type: "Polygon",
    coordinates: [[[x, y], [x + 0.001, y], [x + 0.001, y + 0.001], [x, y + 0.001], [x, y]]],
  };
};

/** The units as the node's input brings them: a new collection on each call. */
export function unitsCollection(): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: UNIT_PROPERTIES.map((properties, row) => ({
      type: "Feature",
      geometry: UNDRAWN.has(row) ? null : square(row % 3, Math.floor(row / 3)),
      properties: { ...properties },
    })),
  } as FeatureCollection;
}

/** The units as a Vega-Lite chart's input frame: the six units, column by column. */
export function unitsFrame(): { dataType: string; data: Record<string, unknown[]> } {
  const units = UNIT_PROPERTIES.filter((p) => p.unit_id !== undefined);
  return {
    dataType: "dataframe",
    data: {
      unit_id: units.map((p) => p.unit_id),
      name: units.map((p) => p.name),
      height: units.map((p) => p.height),
    },
  };
}

/** The order of each round of readings. */
export const READING_ROUND = [104, 101, 106, 102, 105, 103];

/** The readings, in the order they were taken, then the one whose unit_id is text. */
export const READING_ROWS: Array<Record<string, unknown>> = [
  ...[1, 2, 3].flatMap((t) =>
    READING_ROUND.map((unit) => ({ reading: `${unit}-${t}`, unit_id: unit, level: (unit % 7) + t })),
  ),
  { reading: "103-x", unit_id: "103", level: 1 },
];

/** The readings as a Data Pool holds a frame: column by column. */
export function readingColumns(): Record<string, unknown[]> {
  return {
    reading: READING_ROWS.map((r) => r.reading),
    unit_id: READING_ROWS.map((r) => r.unit_id),
    level: READING_ROWS.map((r) => r.level),
  };
}

/** The rows of the readings of *units*, matched by value as it is. */
export function readingsOf(...units: number[]): number[] {
  return READING_ROWS.flatMap((r, i) => (units.includes(r.unit_id as number) ? [i] : []));
}

/** What the readings at *positions* are: a selection of rows read by position. */
export function atPositions(positions: number[]): number[] {
  return positions.filter((p) => p >= 0 && p < READING_ROWS.length);
}

/** The readings a selection of *units* marks as an interval over their heights,
 * as a brush over the drawn values would send it. Readings have no height. */
export function inHeightRange(units: number[]): number[] {
  const heights = units.map((u) => UNIT_PROPERTIES[UNIT_ROW[u]].height as number);
  const [low, high] = [Math.min(...heights), Math.max(...heights)];
  return READING_ROWS.flatMap((r, i) =>
    typeof r.height === "number" && r.height >= low && r.height <= high ? [i] : [],
  );
}

/** The readings of *units* under loose equality, 103 == "103". */
export function looselyHolding(units: number[]): number[] {
  // eslint-disable-next-line eqeqeq
  return READING_ROWS.flatMap((r, i) => (units.some((u) => r.unit_id == u) ? [i] : []));
}

/** A wrong way to match a selection, by what the test names it. */
export type WrongMethod = "positions" | "range" | "firstField" | "looseEquality";

/**
 * Fails when a wrong way of matching marks the rows *expected*: the fixture
 * then no longer tells that way apart from the right one. Each test passes the
 * ways its selection can be matched wrongly, and the rows each marks.
 */
export function expectDiscriminates(expected: number[], wrong: Partial<Record<WrongMethod, number[]>>): void {
  const methods = Object.entries(wrong) as Array<[WrongMethod, number[]]>;
  if (methods.length === 0) throw new Error("expectDiscriminates needs at least one wrong method");
  const sorted = (rows: number[]) => JSON.stringify([...rows].sort((a, b) => a - b));
  for (const [method, rows] of methods) {
    if (sorted(rows) === sorted(expected)) {
      throw new Error(
        `the fixture does not tell matching by ${method} apart: it marks ${sorted(expected)} either way`,
      );
    }
  }
}
