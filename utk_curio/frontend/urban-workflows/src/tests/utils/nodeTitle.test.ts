/**
 * A node's one name, its title: a new node starts with its template's label, a
 * note with none, and a dataflow saved before `title` was the one name is read
 * with its renamed header first.
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

  test("an older save's renamed header wins over the title beside it", () => {
    expect(savedNodeTitle({ title: "Shadow study", metadata: { packageTemplateLabel: "Shade at noon" } })).toBe("Shade at noon");
    expect(savedNodeTitle({ title: "Shadow study", data: { packageTemplateLabel: "Old shade" } })).toBe("Old shade");
    expect(
      savedNodeTitle({ metadata: { packageTemplateLabel: "Shade at noon" }, data: { packageTemplateLabel: "Old shade" } }),
    ).toBe("Shade at noon");
  });
});
