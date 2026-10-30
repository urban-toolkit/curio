/**
 * What a scenario's box and details call a node: its title, the one name its
 * header shows, else its template's label. Its kind tag is always the
 * template's own label.
 */
import { nodeKind, nodeLabel } from "../../components/scenarios/scenarioLabels";

jest.mock("../../utils/palettePackageFactoryDraft", () => ({
  resolveNodeDisplayLabel: (data: { title?: string }) => data.title || "Autark",
}));

const node = (data: Record<string, unknown>) => ({ id: "3c2ed10c-06aa", data: { nodeType: "x", ...data } });

test("the title names it; without one, the template's label", () => {
  expect(nodeLabel(node({ title: "Shadow study" }), "id")).toBe("Shadow study");
  expect(nodeLabel(node({}), "id")).toBe("Autark");
  expect(nodeLabel(undefined, "3c2ed10c-06aa")).toBe("3c2ed10c");
});

test("the kind tag is the template's label, whatever the title", () => {
  expect(nodeKind(node({ title: "Shade at noon" }))).toBe("Autark");
});
