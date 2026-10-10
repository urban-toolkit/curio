/**
 * "Run stale nodes automatically" (#845) is saved at `dataflow.autoRun`. The
 * canvas save passes it, on or off; a writer that does not (a version
 * snapshot, an agent's view) writes no key, so the backend keeps the saved one.
 */
import { TrillGenerator } from "../TrillGenerator";

describe("dataflow.autoRun", () => {
  beforeEach(() => TrillGenerator.reset());

  test("is written on or off when the save passes it (#845)", () => {
    const on = TrillGenerator.generateTrill([], [], "W", "", [], "", [], {}, [], true);
    expect(on.dataflow.autoRun).toBe(true);
    const off = TrillGenerator.generateTrill([], [], "W", "", [], "", [], {}, [], false);
    expect(off.dataflow.autoRun).toBe(false);
  });

  test("is not written when the writer does not pass it (#845)", () => {
    const spec = TrillGenerator.generateTrill([], [], "W");
    expect("autoRun" in spec.dataflow).toBe(false);
  });
});
