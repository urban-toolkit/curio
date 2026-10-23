/**
 * A Data Pool's conflict modes as a spec stores them (#581), and back.
 *
 * The cases in utils/dataPoolSpec.cases.json are run here through the pool's
 * own rule; backend/tests/test_agents/test_node_settings.py runs the same file
 * through the agents' check, so a mode an agent sets is stored as the pool
 * writes it, and one the pool would read as OVERWRITE is refused.
 */
import fs from "fs";
import path from "path";

import { ResolutionType } from "../../constants";
import { dataPoolFromSpec, dataPoolMode, dataPoolToSpec } from "../../utils/dataPoolSpec";

interface PoolCase {
  name: string;
  given: unknown;
  written: Record<string, string> | null;
  loaded: Record<string, string> | null;
  read: Record<string, string> | null;
  agent: { stores?: Record<string, string> | null; refuses?: string | null };
}

const CASES: PoolCase[] = JSON.parse(
  fs.readFileSync(path.join(__dirname, "../../utils/dataPoolSpec.cases.json"), "utf8"),
).cases;

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

describe("the cases the pool and the agents' check share (dataPoolSpec.cases.json)", () => {
  test("they hold each kind of row the two sides must agree on", () => {
    const names = CASES.map((c) => c.name);
    expect(new Set(names).size).toBe(names.length);
    expect(CASES.some((c) => c.agent.stores === null)).toBe(true);
    expect(CASES.some((c) => c.agent.stores && Object.keys(c.agent.stores).length === 2)).toBe(true);
    expect(CASES.some((c) => typeof c.agent.refuses === "string")).toBe(true);
    expect(CASES.some((c) => c.agent.refuses === null)).toBe(true);
    // An agent stores exactly what the pool writes, whenever it stores at all.
    for (const c of CASES) if ("stores" in c.agent) expect(c.agent.stores).toEqual(c.written);
  });

  test.each(CASES.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(dataPoolToSpec(c.given) ?? null).toEqual(c.written);
    expect(dataPoolFromSpec(c.given) ?? null).toEqual(c.loaded);
    if (c.read === null) return;
    const given = c.given as Record<string, unknown>;
    for (const key of ["insideChart", "betweenCharts"]) {
      expect(dataPoolMode(given[key])).toBe(c.read[key]);
    }
    // A member the agents refuse names no mode: the pool would read it as
    // OVERWRITE without a word.
    if (c.agent.refuses === "insideChart" || c.agent.refuses === "betweenCharts") {
      expect(c.read[c.agent.refuses]).toBe(ResolutionType.OVERWRITE);
      expect(given[c.agent.refuses]).not.toBe(ResolutionType.OVERWRITE);
    }
  });
});
