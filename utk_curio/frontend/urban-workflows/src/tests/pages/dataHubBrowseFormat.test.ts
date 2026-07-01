import { consumeLabel, metaLeft } from "../../pages/dataHub/dataHubBrowseFormat";
import type { DatasetCatalogItem } from "../../services/datasetCatalog";

function makeDataset(overrides: Partial<DatasetCatalogItem>): DatasetCatalogItem {
  return {
    id: "computed.node-x",
    title: "Node Output",
    origin: "computed",
    format: "parquet",
    uri: "curio://datasets/computed.node-x@1",
    consumerNodeIds: [],
    updatedAt: "2026-06-18T00:00:00Z",
    tags: ["computed"],
    ...overrides,
  } as DatasetCatalogItem;
}

describe("consumeLabel (grammar of the 'N nodes consume' meta segment)", () => {
  test("zero → plural noun + plural verb", () => {
    expect(consumeLabel(0)).toBe("0 nodes consume");
  });

  test("one → singular noun + singular verb", () => {
    expect(consumeLabel(1)).toBe("1 node consumes");
  });

  test("many → plural noun + plural verb", () => {
    expect(consumeLabel(2)).toBe("2 nodes consume");
    expect(consumeLabel(42)).toBe("42 nodes consume");
  });

  test("missing / malformed count defaults to 0 (never throws or reads 'undefined')", () => {
    expect(consumeLabel(undefined)).toBe("0 nodes consume");
    expect(consumeLabel(null)).toBe("0 nodes consume");
    expect(consumeLabel(NaN)).toBe("0 nodes consume");
    expect(consumeLabel(-3)).toBe("0 nodes consume");
  });

  test("fractional count is floored", () => {
    expect(consumeLabel(1.9)).toBe("1 node consumes");
  });
});

describe("metaLeft consumer segment", () => {
  test("reads the real consumerNodeCount, not consumerNodeIds.length", () => {
    const dataset = makeDataset({ consumerNodeCount: 3, consumerNodeIds: [] });
    expect(metaLeft(dataset)).toContain("3 nodes consume");
  });

  test("singular agreement for a single consumer", () => {
    expect(metaLeft(makeDataset({ consumerNodeCount: 1 }))).toContain("1 node consumes");
  });

  test("defaults to '0 nodes consume' when the count is absent", () => {
    expect(metaLeft(makeDataset({}))).toContain("0 nodes consume");
  });
});
