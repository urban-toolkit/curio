/**
 * A Data Pool's conflict modes as a spec stores them (#581), and back.
 */
import { ResolutionType } from "../../constants";
import { dataPoolFromSpec, dataPoolMode, dataPoolToSpec } from "../../utils/dataPoolSpec";

describe("dataPoolMode", () => {
  test("a ResolutionType names itself; anything else is OVERWRITE", () => {
    for (const mode of Object.values(ResolutionType)) expect(dataPoolMode(mode)).toBe(mode);
    expect(dataPoolMode("MERGE_(AND)")).toBe(ResolutionType.OVERWRITE);
    expect(dataPoolMode(undefined)).toBe(ResolutionType.OVERWRITE);
    expect(dataPoolMode(3)).toBe(ResolutionType.OVERWRITE);
  });
});

describe("dataPoolToSpec", () => {
  test("writes the modes that are not OVERWRITE", () => {
    expect(dataPoolToSpec({ insideChart: "MERGE_AND", betweenCharts: "MERGE_OR" }))
      .toEqual({ insideChart: "MERGE_AND", betweenCharts: "MERGE_OR" });
    expect(dataPoolToSpec({ insideChart: "OVERWRITE", betweenCharts: "MERGE_AND" }))
      .toEqual({ betweenCharts: "MERGE_AND" });
  });

  test("writes nothing for an untouched pool, the defaults, or junk", () => {
    expect(dataPoolToSpec(undefined)).toBeUndefined();
    expect(dataPoolToSpec({ insideChart: "OVERWRITE", betweenCharts: "OVERWRITE" })).toBeUndefined();
    expect(dataPoolToSpec({ betweenCharts: "MERGE_(AND)" })).toBeUndefined();
    expect(dataPoolToSpec(["MERGE_OR"])).toBeUndefined();
  });
});

describe("dataPoolFromSpec", () => {
  test("puts back the members that name a mode", () => {
    expect(dataPoolFromSpec({ insideChart: "MERGE_OR", betweenCharts: "MERGE_AND" }))
      .toEqual({ insideChart: "MERGE_OR", betweenCharts: "MERGE_AND" });
    expect(dataPoolFromSpec({ betweenCharts: "MERGE_OR", propagate: "MERGE_AND" }))
      .toEqual({ betweenCharts: "MERGE_OR" });
  });

  test("drops what names no mode", () => {
    expect(dataPoolFromSpec({ betweenCharts: "MERGE_(AND)" })).toBeUndefined();
    expect(dataPoolFromSpec("MERGE_OR")).toBeUndefined();
    expect(dataPoolFromSpec(null)).toBeUndefined();
  });

  test("a saved spec loads back to what was saved", () => {
    const saved = dataPoolToSpec({ insideChart: "MERGE_AND", betweenCharts: "OVERWRITE" });
    expect(dataPoolFromSpec(saved)).toEqual({ insideChart: "MERGE_AND" });
  });
});
