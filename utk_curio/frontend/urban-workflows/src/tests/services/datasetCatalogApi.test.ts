import { encodeLiveOutputsParam } from "../../services/datasetCatalog/datasetCatalogApi";

/**
 * Regression for issue #139: the liveOutputs query param must be encoded as
 * UTF-8-safe base64 so the backend's ``base64.b64decode(raw).decode("utf-8")``
 * round-trips. downloadDataset previously used raw ``btoa``, which throws (or
 * mis-encodes) on non-Latin1 filenames/data_types and 404s.
 */
describe("encodeLiveOutputsParam", () => {
  const decodeUtf8 = (b64: string) => Buffer.from(b64, "base64").toString("utf-8");

  test("round-trips non-Latin1 filenames (CJK + accents + emoji) as UTF-8", () => {
    const outputs = [
      { node_id: "n1", filename: "café_\u6570\u636e_\uD83C\uDF0D.csv", data_type: "dataframe" },
    ];
    const encoded = encodeLiveOutputsParam(outputs);
    expect(JSON.parse(decodeUtf8(encoded))).toEqual(outputs);
  });

  test("does not throw on code points > 0xFF (the raw btoa bug)", () => {
    const outputs = [{ node_id: "n", filename: "\uD83C\uDF0D" }];
    expect(() => encodeLiveOutputsParam(outputs)).not.toThrow();
    // Contrast: the previous implementation would have thrown here.
    expect(() => btoa(JSON.stringify(outputs))).toThrow();
  });

  test("still encodes the original ASCII export case", () => {
    const outputs = [{ node_id: "n1", filename: "data.csv", data_type: "dataframe" }];
    expect(decodeUtf8(encodeLiveOutputsParam(outputs))).toBe(JSON.stringify(outputs));
  });
});
