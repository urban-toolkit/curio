/**
 * What differs (#662) lists an Edit Features lever by its edits: the code it
 * runs is written from its edit list, so the list is what a reader compares.
 * A copy with other edits is listed with each scenario's edits, an Edit
 * Features node only one scenario has with its own, and copies with the same
 * list read as alike.
 */
import { compareInputs } from "../../utils/compare/compareInputs";
import { comparedScenarios, whatDiffers } from "../../utils/compare/whatDiffers";
import { editFeaturesCode } from "../../utils/editFeatures/editFeatures";
import type { Scenario } from "../../utils/scenarios/scenarioModel";

jest.mock("../../utils/palettePackageFactoryDraft", () => ({
  resolveNodeDisplayLabel: (data: any) => data.title ?? data.nodeId,
}));

const COMPARE = "compare";

function node(id: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    type: "__curioUniversalNode",
    data: { nodeId: id, nodeType: "curio.builtin/computation-analysis@1", code: "return len(arg)", ...extra },
  } as any;
}

function edit(id: string, edits: unknown[] | undefined, extra: Record<string, unknown> = {}) {
  const editFeatures = edits ? { key: "building_id", edits } : { key: "building_id" };
  return node(id, { nodeType: "curio.builtin/edit-features@1", title: "Edit Features", editFeatures, code: editFeaturesCode(editFeatures as any), ...extra });
}

function edge(source: string, target: string, targetHandle = "in") {
  return { id: `${source}-${target}-${targetHandle}`, source, target, sourceHandle: "out", targetHandle } as any;
}

const scenario = (id: string, name: string, color: string, nodes: string[]): Scenario => ({ id, name, color, nodes });

/** load -> edit -> count in each scenario, the second's nodes copies of the first's. */
function twoScenarios(firstEdits: unknown[] | undefined, secondEdits: unknown[] | undefined) {
  const nodes = [
    node("load", { title: "Buildings", code: "return buildings()" }),
    edit("edit", firstEdits),
    node("count", { title: "Count" }),
    edit("edit-2", secondEdits, { copiedFrom: ["edit"] }),
    node("count-2", { title: "Count", copiedFrom: ["count"] }),
    node(COMPARE, { nodeType: "curio.builtin/compare-scenarios@1", title: "Compare" }),
  ];
  const edges = [
    edge("load", "edit"),
    edge("edit", "count"),
    edge("load", "edit-2"),
    edge("edit-2", "count-2"),
    edge("count", COMPARE, "in"),
    edge("count-2", COMPARE, "in_1"),
  ];
  const scenarios = [
    scenario("s-all", "Every building", "#3567c7", ["edit", "count"]),
    scenario("s-less", "Two removed", "#2f8f4a", ["edit-2", "count-2"]),
  ];
  return { nodes, edges, scenarios };
}

const differs = ({ nodes, edges, scenarios }: ReturnType<typeof twoScenarios>) =>
  whatDiffers(comparedScenarios(compareInputs(COMPARE, nodes, edges, scenarios)), nodes, edges);

test("copies with other edits are listed with each scenario's edits, not their code lines", () => {
  const found = differs(twoScenarios(undefined, [{ op: "remove", ids: [119, 136] }, { op: "set", ids: [7], column: "height", value: 3 }]));
  expect(found.differences).toEqual([
    {
      key: "edit",
      label: "Edit Features",
      widgets: [],
      code: [],
      edits: [
        { scenarioId: "s-all", edits: [] },
        { scenarioId: "s-less", edits: ["Remove building_id 119, 136", "Set height to 3 on building_id 7"] },
      ],
    },
  ]);
  // The counts are one lever, alike.
  expect(found.same).toBe(1);
});

test("copies with the same edits read as alike", () => {
  const same = [{ op: "remove", ids: [119] }];
  const found = differs(twoScenarios(same, same));
  expect(found.differences).toEqual([]);
  expect(found.same).toBe(2);
});

test("an Edit Features node only one scenario has is listed as only in it, with its edits", () => {
  const { nodes, edges, scenarios } = twoScenarios(undefined, undefined);
  // The second scenario reads the loader through an Edit Features node of its own.
  const own = edit("towers", [{ op: "remove", ids: [119, 136] }]);
  const rewired = edges.filter((e: any) => !(e.source === "load" && e.target === "edit-2"));
  rewired.push(edge("load", "towers"), edge("towers", "edit-2"));
  const withOwn = [...nodes, own];
  const third = [scenarios[0], { ...scenarios[1], nodes: ["towers", ...scenarios[1].nodes] }];
  const found = whatDiffers(comparedScenarios(compareInputs(COMPARE, withOwn, rewired, third)), withOwn, rewired);
  const only = found.differences.find((d) => d.key === "towers");
  expect(only).toEqual({
    key: "towers",
    label: "Edit Features",
    onlyIn: ["s-less"],
    widgets: [],
    code: [],
    edits: [{ scenarioId: "s-less", edits: ["Remove building_id 119, 136"] }],
  });
});
