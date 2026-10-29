/**
 * Does docs/COLLABORATION.md list the events a dataflow's room answers, and
 * no other?
 *
 * "The room's events" holds a table of them: the event a tab sends, and what
 * the server does with it. The same list is `ROOM_EVENTS` in the backend's
 * test_room_events.py, which holds it to the handlers the server has on the
 * room's namespace (the unit tests' image ships no guides). An event the room
 * starts or stops answering fails there until that list says so, and here
 * until the table does.
 */
import { read } from "../../_support/workflowPaths";

const GUIDE = "docs/COLLABORATION.md";
const SECTION = "### The room's events";
const ROOM_EVENTS_TEST = "utk_curio/backend/tests/test_collaboration/test_room_events.py";

/** "The room's events", from its heading to the next section's. */
function roomEventsSection(): string {
  const lines = read(GUIDE).split("\n");
  const start = lines.findIndex((line) => line.trim() === SECTION);
  if (start < 0) throw new Error(`${GUIDE} has no "${SECTION}" heading`);
  const end = lines.findIndex((line, index) => index > start && /^#{2,3} /.test(line));
  return lines.slice(start, end < 0 ? undefined : end).join("\n");
}

/** A table row's cells, trimmed. */
function cellsOf(row: string): string[] {
  return row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

/** The cells of each row of the section's table, its header and delimiter left out. */
function eventRows(section: string): string[][] {
  const rows = section.split("\n").filter((line) => line.trim().startsWith("|"));
  return rows.slice(2).map(cellsOf);
}

/** `ROOM_EVENTS` as the backend's test writes it: a tuple of quoted names. */
function roomEvents(): string[] {
  const tuple = /^ROOM_EVENTS = \(([^)]*)\)/m.exec(read(ROOM_EVENTS_TEST));
  if (!tuple) throw new Error(`${ROOM_EVENTS_TEST} has no ROOM_EVENTS tuple`);
  return Array.from(tuple[1].matchAll(/"([^"]+)"/g), (name) => name[1]);
}

describe("the room's events in docs/COLLABORATION.md", () => {
  test("the backend's test names the events the room answers", () => {
    expect(roomEvents().length).toBeGreaterThan(0);
  });

  test("its table names each event the room answers once, and no other", () => {
    const documented = eventRows(roomEventsSection()).map((cells) => cells[0]);
    const answered = roomEvents().map((event) => `\`${event}\``);
    expect([...documented].sort()).toEqual([...answered].sort());
  });

  test("every row says what the server does", () => {
    const rows = eventRows(roomEventsSection());
    expect(rows.length).toBeGreaterThan(0);
    for (const cells of rows) {
      expect(cells).toHaveLength(2);
      expect(cells[1]).not.toBe("");
    }
  });
});
