/**
 * The circles under a set's shared nodes: one per scenario of the set, filled
 * when that scenario uses the node. A set of one scenario draws none, and
 * neither does a node inside a box.
 */
import { membershipDots, scenarioCanvasView } from "../../utils/scenarios/scenarioCanvasView";
import type { Node } from "reactflow";
import type { Scenario } from "../../utils/scenarios/scenarioModel";

const s = (id: string, color: string, nodes: string[], context: string[], outcomes: string[], set = "park"): Scenario => ({
  id, name: id, color, nodes, set, context, outcomes,
});

const EXISTING = s("existing", "#2a9d8f", ["e"], ["load"], ["chart", "changeT"]);
const TOWERS = s("towers", "#e76f51", ["t"], ["load", "around"], ["chart", "changeT"]);
const CAP = s("cap", "#6a4c93", ["c"], ["load", "around"], ["chart"]);
const LIVE = new Set(["load", "around", "e", "t", "c", "chart", "changeT"]);

const fill = (rows: ReturnType<typeof membershipDots>, node: string) =>
  rows.find((r) => r.node === node)?.dots.map((d) => (d.member ? d.scenario : `(${d.scenario})`));

test("each shared node gets its set's circles, filled for the scenarios that use it", () => {
  const rows = membershipDots([EXISTING, TOWERS, CAP], LIVE);
  expect(fill(rows, "load")).toEqual(["existing", "towers", "cap"]);
  expect(fill(rows, "around")).toEqual(["(existing)", "towers", "cap"]);
  expect(fill(rows, "changeT")).toEqual(["existing", "towers", "(cap)"]);
  expect(rows.find((r) => r.node === "around")!.dots[1].color).toBe("#e76f51");
});

test("a set of one scenario draws none", () => {
  expect(membershipDots([EXISTING], LIVE)).toEqual([]);
});

test("a node not on the canvas draws none", () => {
  expect(fill(membershipDots([EXISTING, TOWERS], new Set(["chart"])), "load")).toBeUndefined();
});

test("two sets draw their own circles", () => {
  const other = [s("a", "#111111", ["x"], ["k"], [], "other"), s("b", "#222222", ["y"], ["k"], [], "other")];
  const rows = membershipDots([EXISTING, TOWERS, ...other], new Set([...LIVE, "k", "x", "y"]));
  expect(fill(rows, "k")).toEqual(["a", "b"]);
  expect(fill(rows, "load")).toEqual(["existing", "towers"]);
});

test("the canvas view carries them, and marks a scenario being defined", () => {
  const nodes: Node[] = [...LIVE].map((id) => ({ id, position: { x: 0, y: 0 }, data: {} }));
  const view = scenarioCanvasView(nodes, [], [EXISTING, TOWERS], { preview: { context: ["load"], outcomes: ["chart"] } });
  expect(view.dots.map((d) => d.node).sort()).toEqual(["around", "changeT", "chart", "load"]);
  expect(view.nodes.find((n) => n.id === "load")!.className).toContain("curio-scenario-fixed");
  expect(view.nodes.find((n) => n.id === "chart")!.className).toContain("curio-scenario-outcome");
});
