/**
 * What a scenario's box and details call a node: the name its header was
 * renamed to on the canvas, then its title (an agent's or an example's), then
 * its template's label. Its kind tag is always the template's own label.
 */
import { nodeKind, nodeLabel } from "../../components/scenarios/scenarioLabels";

jest.mock("../../utils/palettePackageFactoryDraft", () => ({
  resolveNodeDisplayLabel: (data: { packageTemplateLabel?: string }) => data.packageTemplateLabel || "Autark",
}));

const node = (data: Record<string, unknown>) => ({ id: "3c2ed10c-06aa", data: { nodeType: "x", ...data } });

test("a header renamed on the canvas comes before the title", () => {
  expect(nodeLabel(node({ title: "Shadow study", packageTemplateLabel: "Shade at noon" }), "id")).toBe("Shade at noon");
});

test("without a rename, the title; without either, the template's label", () => {
  expect(nodeLabel(node({ title: "Shadow study" }), "id")).toBe("Shadow study");
  expect(nodeLabel(node({}), "id")).toBe("Autark");
  expect(nodeLabel(undefined, "3c2ed10c-06aa")).toBe("3c2ed10c");
});

test("the kind tag is the template's label, whatever the header was renamed to", () => {
  expect(nodeKind(node({ packageTemplateLabel: "Shade at noon" }))).toBe("Autark");
});
