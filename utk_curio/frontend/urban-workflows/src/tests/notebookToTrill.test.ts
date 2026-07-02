import { modified_wireCode } from "../NotebookConvertor";
import type { CellEdge } from '../NotebookConvertor';

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeIncomingSources(edges: CellEdge[]): Map<number, number[]> {
  const map = new Map<number, number[]>();
  for (const { source, target } of edges) {
    if (!map.has(target)) map.set(target, []);
    map.get(target)!.push(source);
  }
  return map;
}

function makeHasOutgoing(edges: CellEdge[]): Set<number> {
  return new Set(edges.map((e) => e.source));
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("modified_wireCode", () => {

  // ── No edges ─────────────────────────────────────────────────────────────

  test("cell with no incoming or outgoing edges is returned unchanged", () => {
    const code = 'print("Hello World")';
    const edges: CellEdge[] = [];
    const result = modified_wireCode(
      code,
      0,
      edges,
      makeHasOutgoing(edges),
      makeIncomingSources(edges),
    );
    expect(result).toBe(code);
  });

  // ── Incoming edge ─────────────────────────────────────────────────────────

  test("cell with one incoming edge prepends {parent_var} = arg", () => {
    const code = 'HS_only_data = df[df["col"] == "HS"]';
    const edges: CellEdge[] = [{ source: 0, target: 1, parent_var: "df" }];
    const result = modified_wireCode(
      code,
      1,
      edges,
      makeHasOutgoing(edges),
      makeIncomingSources(edges),
    );
    expect(result).toBe(`df = arg\n${code}`);
  });

  test("cell with one incoming edge but no parent_var falls back to arg = arg", () => {
    const code = "result = process(x)";
    const edges: CellEdge[] = [{ source: 0, target: 1 }];
    const result = modified_wireCode(
      code,
      1,
      edges,
      makeHasOutgoing(edges),
      makeIncomingSources(edges),
    );
    expect(result).toBe(`arg = arg\n${code}`);
  });

  // ── Outgoing edge ─────────────────────────────────────────────────────────

  test("cell with one outgoing edge appends return {parent_var}", () => {
    const code = "df = pd.read_csv('data.csv')";
    const edges: CellEdge[] = [{ source: 0, target: 1, parent_var: "df" }];
    const result = modified_wireCode(
      code,
      0,
      edges,
      makeHasOutgoing(edges),
      makeIncomingSources(edges),
    );
    expect(result).toBe(`${code}\nreturn df`);
  });

  test("cell with outgoing edge but no parent_var does not append return", () => {
    const code = "x = 1";
    const edges: CellEdge[] = [{ source: 0, target: 1 }];
    const result = modified_wireCode(
      code,
      0,
      edges,
      makeHasOutgoing(edges),
      makeIncomingSources(edges),
    );
    expect(result).toBe(code);
  });

  // ── Both incoming and outgoing ────────────────────────────────────────────

  test("middle cell gets both prepend and append", () => {
    const code = 'HS_only = df[df["type"] == "HS"]';
    const edges: CellEdge[] = [
      { source: 0, target: 1, parent_var: "df" },
      { source: 1, target: 2, parent_var: "HS_only" },
    ];
    const result = modified_wireCode(
      code,
      1,
      edges,
      makeHasOutgoing(edges),
      makeIncomingSources(edges),
    );
    expect(result).toBe(`df = arg\n${code}\nreturn HS_only`);
  });

  // ── Multiple incoming sources ─────────────────────────────────────────────

  test("cell with multiple incoming sources gets comment instead of prepend", () => {
    const code = "merged = pd.merge(df1, df2)";
    const edges: CellEdge[] = [
      { source: 0, target: 2, parent_var: "df1" },
      { source: 1, target: 2, parent_var: "df2" },
    ];
    const result = modified_wireCode(
      code,
      2,
      edges,
      makeHasOutgoing(edges),
      makeIncomingSources(edges),
    );
    expect(result).toBe(`# multiple inputs available via arg\n${code}`);
  });

  // ── Fallback linear chain (no parent_var) ─────────────────────────────────

  test("fallback linear chain edge with lastVar prepends correctly", () => {
    const code = "summary = df.describe()";
    const edges: CellEdge[] = [{ source: 0, target: 1, parent_var: "df" }];
    const result = modified_wireCode(
      code,
      1,
      edges,
      makeHasOutgoing(edges),
      makeIncomingSources(edges),
    );
    expect(result).toBe(`df = arg\n${code}`);
  });

  test("fallback linear chain edge with no parent_var falls back to arg", () => {
    const code = "summary = x.describe()";
    const edges: CellEdge[] = [{ source: 0, target: 1 }];
    const result = modified_wireCode(
      code,
      1,
      edges,
      makeHasOutgoing(edges),
      makeIncomingSources(edges),
    );
    expect(result).toBe(`arg = arg\n${code}`);
  });
});