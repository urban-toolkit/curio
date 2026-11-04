/**
 * A node's one name, its title: a new node starts with its template's label, a
 * note with none, and a saved node is read by its title alone.
 */
import { initialNodeTitle, isNoteType, savedNodeTitle } from "../../utils/nodeTitle";

jest.mock("../../registry/nodeRegistry", () => ({
  tryGetNodeDescriptor: (type: string) =>
    ({
      "curio.builtin/computation-analysis": { label: "Python Computation" },
      "curio.builtin/note": { label: "Note" },
    } as Record<string, { label: string }>)[type.replace(/@[0-9]+$/, "")],
}));

describe("initialNodeTitle", () => {
  test("a given title is kept, trimmed", () => {
    expect(initialNodeTitle("curio.builtin/computation-analysis", "  Clean parcels ")).toBe("Clean parcels");
  });

  test("without one, the template's label", () => {
    expect(initialNodeTitle("curio.builtin/computation-analysis@1")).toBe("Python Computation");
    expect(initialNodeTitle("curio.builtin/computation-analysis", "   ")).toBe("Python Computation");
  });

  test("a note starts with no title, its heading being its author's", () => {
    expect(isNoteType("curio.builtin/note@1")).toBe(true);
    expect(initialNodeTitle("curio.builtin/note@1")).toBeUndefined();
    expect(initialNodeTitle("curio.builtin/note", "Findings")).toBe("Findings");
  });

  test("a template the registry does not know gets none", () => {
    expect(initialNodeTitle("acme.pkg/unknown@1")).toBeUndefined();
  });
});

describe("savedNodeTitle", () => {
  test("the title of a saved node", () => {
    expect(savedNodeTitle({ title: " Shadow study " })).toBe("Shadow study");
    expect(savedNodeTitle({})).toBe("");
  });

  test("a header an older save holds at packageTemplateLabel names nothing: the title does", () => {
    type OlderNode = { title?: string; metadata?: Record<string, unknown>; data?: Record<string, unknown> };
    const renamed: OlderNode = { title: "Shadow study", metadata: { packageTemplateLabel: "Shade at noon" } };
    const older: OlderNode = { title: "Shadow study", data: { packageTemplateLabel: "Old shade" } };
    const untitled: OlderNode = { metadata: { packageTemplateLabel: "Shade at noon" }, data: { packageTemplateLabel: "Old shade" } };
    expect(savedNodeTitle(renamed)).toBe("Shadow study");
    expect(savedNodeTitle(older)).toBe("Shadow study");
    expect(savedNodeTitle(untitled)).toBe("");
  });
});
