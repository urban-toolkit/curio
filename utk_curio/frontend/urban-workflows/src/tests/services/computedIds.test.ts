// TS mirror of the backend computed-id grammar — cases ported from
// backend/tests/test_datasets/test_computed_namespacing_and_lineage.py so the
// two parsers stay in lockstep (#175).
import {
  dataflowSegmentFromComputedId,
  nodeSegmentFromComputedId,
  sanitizeNodeIdSegment,
} from "../../services/datasetCatalog/computedIds";

describe("sanitizeNodeIdSegment", () => {
  test("lowercases and collapses punctuation to dashes", () => {
    expect(sanitizeNodeIdSegment("Node_1!x")).toBe("node-1-x");
  });

  test("prefixes non-alpha-initial ids with n (UUIDs starting with a digit)", () => {
    expect(sanitizeNodeIdSegment("13ab40cd")).toBe("n13ab40cd");
    expect(sanitizeNodeIdSegment("c8077fbd-010d")).toBe("c8077fbd-010d");
  });

  test("falls back to 'node' when nothing survives", () => {
    expect(sanitizeNodeIdSegment("!!!")).toBe("n");
    expect(sanitizeNodeIdSegment("")).toBe("n");
  });
});

describe("segment extraction round-trips both id forms", () => {
  test("namespaced form", () => {
    expect(nodeSegmentFromComputedId("computed.proj-xyz.node-5")).toBe("node-5");
    expect(dataflowSegmentFromComputedId("computed.proj-xyz.node-5")).toBe("proj-xyz");
  });

  test("legacy form has no dataflow segment", () => {
    expect(nodeSegmentFromComputedId("computed.node-5")).toBe("node-5");
    expect(dataflowSegmentFromComputedId("computed.node-5")).toBeNull();
  });

  test("tolerates the @major suffix", () => {
    expect(nodeSegmentFromComputedId("computed.proj-xyz.node-5@1")).toBe("node-5");
    expect(dataflowSegmentFromComputedId("computed.proj-xyz.node-5@1")).toBe("proj-xyz");
  });

  test("non-computed inputs", () => {
    expect(nodeSegmentFromComputedId("it.urbanlab.milan")).toBeNull();
    expect(dataflowSegmentFromComputedId(null)).toBeNull();
    expect(nodeSegmentFromComputedId(undefined)).toBeNull();
  });
});
