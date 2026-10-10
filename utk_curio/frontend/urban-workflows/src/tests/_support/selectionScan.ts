/**
 * The oracle of the point-value matcher's tests: the rows a point selection
 * over fields picks, found by comparing every point with every row, as
 * utils/selectionMatch did before it looked values up. Strict equality, a Date
 * compared by its time, and a bin, [start, end), holding the numbers inside it.
 */
import type { PointValue, SelectionRows } from "../../utils/selectionMatch";

const comparable = (value: unknown) => (value instanceof Date ? value.getTime() : value);

function holdsValue(held: unknown, value: unknown): boolean {
  if (Array.isArray(held) && held.length === 2) {
    const [start, end, at] = [comparable(held[0]), comparable(held[1]), comparable(value)];
    return typeof at === "number" && typeof start === "number" && typeof end === "number"
      && start <= at && at < end;
  }
  return comparable(held) === comparable(value);
}

/** Positions of the rows that hold every field value of one of *points*. */
export function scanRowsHolding(points: PointValue[], rows: SelectionRows): number[] {
  const wanted = points.map((point) => Object.entries(point)).filter((fields) => fields.length > 0);
  const indices: number[] = [];
  for (let i = 0; i < rows.count; i++) {
    if (wanted.some((fields) => fields.every(([field, held]) => holdsValue(held, rows.value(i, field))))) {
      indices.push(i);
    }
  }
  return indices;
}
