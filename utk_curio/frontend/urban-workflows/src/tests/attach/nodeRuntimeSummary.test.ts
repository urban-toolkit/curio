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

  it("names a merge input slot by slot", () => {
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
