/**
 * Two canvas nodes saved into one package must not share a source file.
 *
 * Every kind is written to `sources/<sourceFilename>` (`toApiPayload`), so a
 * constant fallback meant the second Save-As over a package overwrote the first
 * kind's code. The manifest kept both kinds, which hid it until you ran them:
 * the palette showed two rows executing identical code.
 *
 * Two fallbacks had to agree for that to be fixed, and this pins both:
 *
 *  - `descriptorToTemplateDraft` derives the filename from the template id,
 *    which already carries the suffix that keeps two same-typed nodes apart;
 *  - `canvasTemplateConfigFromDescriptor` must NOT invent one, because
 *    `applyCanvasTemplateConfigToTemplateDraft` lets a non-blank config value win
 *    and the canvas path always runs that merge (the only way into Save-As is the
 *    Node settings modal, which stores a config on the node).
 *
 * The e2e counterpart is
 * `test_package_roundtrip_e2e.py::test_two_kinds_saved_into_one_package_keep_their_own_code`,
 * which proves it through the real archive; this proves it deterministically and
 * in milliseconds.
 */
import {
  applyCanvasTemplateConfigToTemplateDraft,
  canvasTemplateConfigFromDescriptor,
} from "../../utils/canvasTemplateConfig";
import { descriptorToTemplateDraft } from "../../utils/palettePackageFactoryDraft";

const descriptor = (overrides: Record<string, any> = {}) =>
  ({
    id: "curio.builtin/data-transformation@1",
    label: "Data Transformation",
    description: "",
    category: "computation",
    editor: "code",
    hasCode: true,
    hasWidgets: false,
    hasGrammar: false,
    hasProvenance: true,
    inputPorts: [{ types: ["DATAFRAME"], cardinality: "1" }],
    outputPorts: [{ types: ["DATAFRAME"], cardinality: "1" }],
    ...overrides,
  }) as any;

/** What `templateDraftFromCanvasNode` does, which is module-private. */
const canvasDraft = (
  desc: any,
  code: string,
  label: string,
  kindIdOverride?: string,
) => {
  const node = { id: "n1", data: {} };
  const base = descriptorToTemplateDraft(desc, code, kindIdOverride, label);
  const config = canvasTemplateConfigFromDescriptor(desc, node, code);
  return applyCanvasTemplateConfigToTemplateDraft(base, config, label);
};

describe("Save-As source filenames", () => {
  test("a canvas node's filename comes from its template id, not a constant", () => {
    const draft = canvasDraft(descriptor(), "return ['first']", "E2E First");
    expect(draft.sourceFilename).toBe("data-transformation.py");
    expect(draft.sourceFilename).not.toBe("default.py");
  });

  test("two same-typed nodes in one package get different files", () => {
    // The second Save-As into a package passes a suffixed kind id so the two
    // kinds stay distinct; the filename has to follow it.
    const first = canvasDraft(descriptor(), "return ['first']", "E2E First");
    const second = canvasDraft(
      descriptor(),
      "return ['second']",
      "E2E Second",
      "data-transformation-k-abc123",
    );

    expect(second.sourceFilename).toBe("data-transformation-k-abc123.py");
    expect(first.sourceFilename).not.toBe(second.sourceFilename);
    // And each keeps its own body: sharing a filename is what used to lose one.
    expect(first.sourceCode).toContain("first");
    expect(second.sourceCode).toContain("second");
  });

  test("the canvas config does not override the per-kind filename", () => {
    // The regression guard for the second half of the fix: a constant here wins
    // the merge and puts both kinds back on one file.
    const desc = descriptor();
    const config = canvasTemplateConfigFromDescriptor(desc, { id: "n1", data: {} }, "");
    expect(config.sourceFilename).toBe("");

    const base = descriptorToTemplateDraft(desc, "return [1]", "kind-x", "Kind X");
    expect(
      applyCanvasTemplateConfigToTemplateDraft(base, config, "Kind X").sourceFilename,
    ).toBe("kind-x.py");
  });

  test("a template that came from a package keeps its real filename", () => {
    // Only the no-source case changed, so an existing package's templates are
    // preserved and Save-As over one does not orphan its file.
    const desc = descriptor({
      package: { source: "sources/hexbin.py" },
    });
    expect(canvasDraft(desc, "return [1]", "Hexbin").sourceFilename).toBe("hexbin.py");
  });
});
