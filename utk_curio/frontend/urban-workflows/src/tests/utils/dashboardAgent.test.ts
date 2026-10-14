import { applyAgentChanges, controlId, dashboardControls } from "../../utils/dashboardAgent";
import { PARAMETER_NODE_TYPE } from "../../utils/references/sharedParameters";

const season = (value: string) => ({
  name: "season",
  type: "choice" as const,
  label: "Season",
  default: "summer",
  value,
  options: { choices: ["spring", "summer", "winter"] },
});

const nodes = [
  { id: "a", type: "x", data: { title: "Simulate Shadows", widgets: [season("winter")] } },
  { id: "b", type: "x", data: { title: "Simulate Shadows", widgets: [season("summer")] } },
  {
    id: "p",
    type: PARAMETER_NODE_TYPE,
    data: { title: "Height", widgets: [{ name: "height", type: "slider", default: 550, options: { min: 0, max: 550 } }] },
  },
  { id: "hidden", type: "x", data: { title: "Not pinned", widgets: [season("spring")] } },
];
const pins = { a: true, b: true, p: true };
const scenarios = [
  { id: "s1", name: "Winter", color: "#112233", nodes: ["a"] },
  { id: "s2", name: "Summer", color: "#445566", nodes: ["b"] },
] as any;

describe("dashboardControls", () => {
  it("lists the pinned tiles' widgets, each with its scenario", () => {
    const controls = dashboardControls(nodes, pins, scenarios);
    expect(controls.map((c) => [c.id, c.scenario, c.value])).toEqual([
      ["a:season", "Winter", "winter"],
      ["b:season", "Summer", "summer"],
      ["p:height", null, 550],
    ]);
    expect(controls[0]).toMatchObject({ node: "Simulate Shadows", label: "Season", type: "choice" });
  });
});

describe("applyAgentChanges", () => {
  const controls = dashboardControls(nodes, pins, scenarios);

  it("changes several widgets at once and says what each was", () => {
    const out = applyAgentChanges(nodes, controls, [
      { id: controlId("a", "season"), value: "spring" },
      { id: "p:height", value: 300 },
    ]);
    expect(out.skipped).toEqual([]);
    expect(out.widgetsByNode.get("a")?.[0].value).toBe("spring");
    expect(out.widgetsByNode.get("p")?.[0].value).toBe(300);
    expect(out.widgetsByNode.has("b")).toBe(false);
    expect(out.applied.map((a) => [a.label, a.scenario, a.from, a.to])).toEqual([
      ["Season", "Winter", "winter", "spring"],
      // A widget with no label is named by its name.
      ["height", null, 550, 300],
    ]);
  });

  it("skips a value its widget does not take, and a control that is not there", () => {
    const out = applyAgentChanges(nodes, controls, [
      { id: "a:season", value: "autumn" },
      { id: "p:height", value: 900 },
      { id: "hidden:season", value: "winter" },
    ]);
    expect(out.widgetsByNode.size).toBe(0);
    expect(out.skipped.map((s) => s.id)).toEqual(["a:season", "p:height", "hidden:season"]);
  });
});
