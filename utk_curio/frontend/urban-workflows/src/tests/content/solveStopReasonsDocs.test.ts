/**
 * Does docs/ARCHITECTURE.md list every reason a node's repair loop stops, in
 * the words the product says it?
 *
 * "The Solve loop" holds a table of the reasons: the key the loop sends as
 * `stoppedBy`, when it happens, and the phrase every surface shows for it. The
 * keys and phrases are `SOLVE_STOP_REASONS` in contracts.py, read here through
 * the generated solveStopReasons.ts (test_generated_contracts keeps that file
 * equal to contracts.py). A reason added, renamed or reworded there fails here
 * until the table says the same.
 */
import * as fs from "fs";
import * as path from "path";
import { STOPPED_BY_PHRASES, STOP_REASONS } from "../../generated/solveStopReasons";

const REPO_ROOT = path.join(__dirname, "..", "..", "..", "..", "..", "..");
const ARCHITECTURE = path.join(REPO_ROOT, "docs", "ARCHITECTURE.md");
const SECTION = "### The Solve loop";
/** The first cell of the stop reasons table's header row. */
const KEY_HEADER = "`stoppedBy`";

/** "The Solve loop", from its heading to the next section's. */
function solveLoopSection(): string {
  const lines = fs.readFileSync(ARCHITECTURE, "utf-8").split("\n");
  const start = lines.findIndex((line) => line.trim() === SECTION);
  if (start < 0) throw new Error(`docs/ARCHITECTURE.md has no "${SECTION}" heading`);
  const end = lines.findIndex((line, index) => index > start && /^#{2,3} /.test(line));
  return lines.slice(start, end < 0 ? undefined : end).join("\n");
}

/** A table row's cells, trimmed. `\|` is a pipe inside a cell. */
function cellsOf(row: string): string[] {
  const inner = row.trim().replace(/\\\|/g, "\u0000").replace(/^\|/, "").replace(/\|$/, "");
  return inner.split("|").map((cell) => cell.replace(/\u0000/g, "|").trim());
}

/** The cells of each row of the table whose header starts with `stoppedBy`; none without it. */
function stopReasonRows(section: string): string[][] {
  const lines = section.split("\n");
  const header = lines.findIndex(
    (line) => line.trim().startsWith("|") && cellsOf(line)[0] === KEY_HEADER,
  );
  if (header < 0) return [];
  const rows: string[][] = [];
  // The row after the header is the |---| delimiter; the table ends at its first non-row.
  for (const line of lines.slice(header + 2)) {
    if (!line.trim().startsWith("|")) break;
    rows.push(cellsOf(line));
  }
  return rows;
}

const byKey = (a: string[], b: string[]) => a[0].localeCompare(b[0]);

describe("the stop reasons in docs/ARCHITECTURE.md's The Solve loop", () => {
  test("the section is there to read", () => {
    expect(solveLoopSection().startsWith(SECTION)).toBe(true);
  });

  test("its table names every reason once, with the reason's phrase, and no other", () => {
    const documented = stopReasonRows(solveLoopSection()).map((cells) => [cells[0], cells[2]]);
    const generated = STOP_REASONS.map((reason) => [`\`${reason}\``, STOPPED_BY_PHRASES[reason]]);
    expect(documented.sort(byKey)).toEqual(generated.sort(byKey));
  });

  test("every row has three cells and says when its reason happens", () => {
    const rows = stopReasonRows(solveLoopSection());
    expect(rows.length).toBeGreaterThan(0);
    for (const cells of rows) {
      expect(cells).toHaveLength(3);
      expect(cells[1]).not.toBe("");
    }
  });
});
