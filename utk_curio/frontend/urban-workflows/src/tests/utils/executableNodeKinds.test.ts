import { isExecutableNodeType } from "../../utils/executableNodeKinds";

/** dev/118: the frontend twin of workflow_spec.is_executable_kind. */
describe("isExecutableNodeType", () => {
  it("names the code kinds, versioned or legacy", () => {
    for (const k of ["curio.builtin/data-loading", "curio.builtin/computation-analysis@1", "curio.builtin/js-computation", "DATA_LOADING"])
      expect(isExecutableNodeType(k)).toBe(true);
  });
  it("everything else renders in the browser", () => {
    for (const k of ["curio.builtin/vis-vega", "curio.builtin/autk-grammar@1", "curio.builtin/data-pool", "curio.builtin/merge-flow", "some.pkg/custom@1", "", undefined, 3])
      expect(isExecutableNodeType(k)).toBe(false);
  });
});
