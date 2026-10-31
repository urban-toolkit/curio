/**
 * dev/129 (porting dev/111): the runtime summary that `nodeContext`'s
 * current_input / current_output carry. The owner asked whether the failures
 * had to do with those being sent empty — they were, on this branch, because
 * dev/111 shipped only on feat/agentscatalog.
 */
import {
  NEVER_EXECUTED,
  storeOutputFor,
  summarizeNodeInput,
  summarizeNodeOutput,
} from "../../utils/nodeRuntimeSummary";

describe("summarizeNodeInput", () => {
  it("names an artifact input by type and id", () => {
    expect(
      summarizeNodeInput({ input: { dataType: "geodataframe", path: "art-77" } }),
    ).toBe("geodataframe from artifact art-77");
  });

  it("names a list input slot by slot", () => {
    const text = summarizeNodeInput({
      input: [
        { dataType: "geodataframe", path: "art-b" },
        { dataType: "dataframe", path: "art-p" },
        undefined,
      ],
    });
    expect(text).toContain("MULTIPLE (3 slots)");
    expect(text).toContain("[0] geodataframe from artifact art-b");
    expect(text).toContain("[1] dataframe from artifact art-p");
    expect(text).toContain("[2] empty");
  });

  it("says so when there is no upstream input, with the declared type", () => {
    expect(summarizeNodeInput({ in: "DATAFRAME" })).toBe(
      "no upstream input (declared: DATAFRAME)",
    );
  });

  // 10-30, step 44's live runs: a chart wired to a loader that had not run was
  // told "no upstream input", took itself for a chart nothing feeds, and the
  // agent built it a new loader instead of changing the one wired in.
  it("says a node wired to one that has not run waits for input from it", () => {
    expect(
      summarizeNodeInput({ in: "DEFAULT" }, [
        { id: "loader", type: "curio.builtin/data-loading", data: {} },
      ]),
    ).toBe(
      "waiting for input (declared: DEFAULT): wired from node loader " +
        "(curio.builtin/data-loading), which has not run",
    );
  });

  it("says of each node wired in whether it ran, failed or is running, and nothing of its output", () => {
    const text = summarizeNodeInput({}, [
      { id: "a", type: "CODE", data: { output: { code: "success", dataType: "dataframe" } } },
      { id: "b", type: "CODE", data: { output: { code: "error", content: "KeyError: 'tract_id'" } } },
      { id: "c", type: "CODE", data: { output: { code: "exec" } } },
      { id: "d", type: "CODE", data: {}, storeOutput: { dataType: "dataframe", path: "art-d" } },
      { id: "e", type: "CODE" },
    ]);
    expect(text).toBe(
      "waiting for input: wired from node a (CODE), which ran; node b (CODE), which failed; " +
        "node c (CODE), which is running; node d (CODE), which ran; node e (CODE), which has not run",
    );
    expect(text).not.toContain("tract_id");
    expect(text).not.toContain("art-d");
  });

  it("names the first six nodes wired in and counts the rest", () => {
    const feeders = Array.from({ length: 8 }, (_, i) => ({ id: `n${i}`, type: "CODE" }));
    expect(summarizeNodeInput({}, feeders)).toBe(
      "waiting for input: wired from " +
        [0, 1, 2, 3, 4, 5].map((i) => `node n${i} (CODE), which has not run`).join("; ") +
        "; and 2 more",
    );
  });

  it("keeps saying no upstream input when no edge feeds the node", () => {
    expect(summarizeNodeInput({ in: "DATAFRAME" }, [])).toBe(
      "no upstream input (declared: DATAFRAME)",
    );
  });

  it("says what arrived, whatever is wired in", () => {
    expect(
      summarizeNodeInput(
        { input: { dataType: "dataframe", path: "art-1" }, in: "DEFAULT" },
        [{ id: "loader", type: "curio.builtin/data-loading" }],
      ),
    ).toBe("dataframe from artifact art-1 (declared: DEFAULT)");
  });

  it("is empty without live data at all", () => {
    expect(summarizeNodeInput(undefined)).toBe("");
  });
});

describe("summarizeNodeOutput", () => {
  it("names a success with its type and artifact", () => {
    expect(
      summarizeNodeOutput(
        { output: { code: "success", dataType: "dataframe" } },
        { dataType: "dataframe", path: "art-9" },
      ),
    ).toBe("success: dataframe artifact art-9");
  });

  it("forwards an error MESSAGE and nothing else", () => {
    const text = summarizeNodeOutput({
      output: { code: "error", content: "KeyError: 'tract_id'" },
    });
    expect(text).toBe("error: KeyError: 'tract_id'");
  });

  it("truncates a long error", () => {
    const text = summarizeNodeOutput({
      output: { code: "error", content: "x".repeat(400) },
    });
    expect(text.length).toBeLessThan(260);
    expect(text.endsWith("…")).toBe(true);
  });

  it("says never-executed rather than empty, with the declared type", () => {
    expect(summarizeNodeOutput({ out: "GEODATAFRAME" })).toBe(
      `${NEVER_EXECUTED} (declared: GEODATAFRAME)`,
    );
  });

  it("reports a restored artifact honestly", () => {
    expect(
      summarizeNodeOutput({}, { dataType: "geodataframe", dataset: "ds-1" }),
    ).toBe("success (restored): geodataframe artifact ds-1");
  });

  it("reports a running node", () => {
    expect(summarizeNodeOutput({ output: { code: "exec" } })).toBe("running");
  });

  it("never forwards the output's data content", () => {
    const text = summarizeNodeOutput(
      { output: { code: "success", dataType: "dataframe", content: [{ secret: "value" }] } },
      { dataType: "dataframe", path: "art-1" },
    );
    expect(text).not.toContain("secret");
    expect(text).not.toContain("value");
  });
});

describe("storeOutputFor", () => {
  it("finds a node's artifact and tolerates absence", () => {
    const outputs = [{ nodeId: "n1", output: { path: "art-1" } }];
    expect(storeOutputFor(outputs, "n1")).toEqual({ path: "art-1" });
    expect(storeOutputFor(outputs, "n2")).toBeUndefined();
    expect(storeOutputFor(undefined, "n1")).toBeUndefined();
  });
});
