/**
 * The Projects rail's arithmetic: which values a dataflow has in each section,
 * how the sections combine, and what the counts say.
 */
import {
  addHandCategory,
  allCategoryValues,
  facetEntries,
  facetValues,
  knownValues,
  matchesSelection,
  removeHandCategory,
  type DataflowCategories,
} from "../../utils/dataflowCategories";

const item = (categories: DataflowCategories) => ({ categories });

const USE_CASE = item({
  source: "use_case",
  auto: { tags: ["Autark", "Vega-Lite"], data_type: ["Rasters"] },
  hand: { city: ["Milan"], topic: ["Heat and climate"], complexity: ["Advanced"] },
});
const TEST = item({ source: "test", auto: { tags: ["Autark"] }, hand: { complexity: ["Beginner"] } });
const MINE = item({ source: null, auto: { tags: ["Pandas"] }, hand: { tags: ["autark", "Flood"] } });
const ALL = [USE_CASE, TEST, MINE];

describe("facetValues", () => {
  test("source is labelled, and only the account's own are Yours", () => {
    expect(facetValues(USE_CASE.categories, "source")).toEqual(["Use cases"]);
    expect(facetValues(USE_CASE.categories, "owner")).toEqual([]);
    expect(facetValues(MINE.categories, "owner")).toEqual(["yours"]);
  });

  test("tags join the automatic and the hand-set ones, once each", () => {
    // "autark" by hand is the same tag as the automatic "Autark".
    expect(facetValues(MINE.categories, "tags")).toEqual(["Pandas", "autark", "Flood"]);
    expect(facetValues({ auto: { tags: ["Autark"] }, hand: { tags: ["autark"] } }, "tags")).toEqual([
      "Autark",
    ]);
  });

  test("a response without categories has none", () => {
    expect(facetValues(undefined, "tags")).toEqual([]);
    expect(facetValues(undefined, "owner")).toEqual(["yours"]);
  });

  test("search sees every label", () => {
    expect(allCategoryValues(USE_CASE.categories)).toEqual(
      expect.arrayContaining(["Use cases", "Autark", "Rasters", "Milan", "Advanced"]),
    );
  });
});

describe("selection", () => {
  test("sections combine", () => {
    expect(matchesSelection(USE_CASE, { tags: "Autark", city: "Milan" })).toBe(true);
    expect(matchesSelection(TEST, { tags: "Autark", city: "Milan" })).toBe(false);
  });

  test("counts follow the other sections, not their own", () => {
    const selection = { source: "Tests" };
    expect(facetEntries(ALL, "tags", selection)).toEqual([{ value: "Autark", count: 1 }]);
    // Its own section still lists the others, with what clicking would give.
    expect(facetEntries(ALL, "source", selection)).toEqual([
      { value: "Use cases", count: 1 },
      { value: "Tests", count: 1 },
    ]);
  });

  test("tags sort by count; complexity keeps its level order", () => {
    expect(facetEntries(ALL, "tags", {})[0]).toEqual({ value: "Autark", count: 2 });
    expect(facetEntries(ALL, "complexity", {}).map((e) => e.value)).toEqual([
      "Beginner",
      "Advanced",
    ]);
  });
});

describe("editing", () => {
  test("adding trims, skips a duplicate, and complexity keeps one value", () => {
    let hand = addHandCategory({}, "topic", "  Heat   and climate ");
    hand = addHandCategory(hand, "topic", "heat and climate");
    expect(hand).toEqual({ topic: ["Heat and climate"] });
    hand = addHandCategory(hand, "complexity", "Beginner");
    hand = addHandCategory(hand, "complexity", "Advanced");
    expect(hand.complexity).toEqual(["Advanced"]);
  });

  test("removing the last value drops the section", () => {
    expect(removeHandCategory({ city: ["Milan"], topic: ["Greenery"] }, "city", "Milan")).toEqual({
      topic: ["Greenery"],
    });
  });

  test("suggestions come from the account's dataflows; complexity always offers the levels", () => {
    expect(knownValues(ALL, "tags")).toEqual(["Autark", "Flood", "Pandas", "Vega-Lite"]);
    expect(knownValues([], "complexity")).toEqual(["Beginner", "Intermediate", "Advanced"]);
  });
});
