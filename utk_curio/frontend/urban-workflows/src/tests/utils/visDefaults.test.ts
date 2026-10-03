/**
 * The starter ladders and the image column rule follow the generated tables in
 * `src/generated/visDefaults.ts`, which the agents' shared preamble states
 * too: each generated rule has exactly one builder, the ladders try the rules
 * in the generated order, and the image rule uses the generated names and
 * constants. The conditions are read here straight from the generated data, so
 * a ladder that derives one differently disagrees with this file.
 */
import {
  AUTK_STARTER_LADDER,
  COLUMN_ROLES,
  DTYPE_ROLES,
  IMAGE_COLUMNS,
  IMAGE_EXTENSIONS,
  IMAGE_MATCH_THRESHOLD,
  VEGA_SCHEMA_URL,
  VEGA_STARTER_LADDER,
  type ColumnRole,
  type CountRange,
  type RoleCounts,
} from "../../generated/visDefaults";
import {
  AUTK_STARTER_BUILDERS,
  AUTK_STARTER_RULES,
  chooseAutkStarter,
  type StarterLayer,
} from "../../utils/autkDefaultSpec";
import { RECOGNIZED_COLUMNS, resolveImageColumns } from "../../utils/imageColumns";
import { classifyColumns, type ClassifiedColumn } from "../../utils/starterSpec";
import {
  DEFAULT_SPEC_RULES,
  VEGA_STARTER_BUILDERS,
  chooseDefaultSpec,
} from "../../utils/vegaDefaultSpec";

type Counts = Record<ColumnRole, number>;

const holds = (range: CountRange | undefined, n: number) =>
  range === undefined || (n >= range.least && (range.most === undefined || n <= range.most));

const meets = (needs: RoleCounts, counts: Counts) =>
  COLUMN_ROLES.every((role) => holds(needs[role], counts[role]));

/** Every way of having zero, one or two columns of each role. */
const EVERY_COUNTS: Counts[] = COLUMN_ROLES.reduce<Counts[]>(
  (all, role) => all.flatMap((counts) => [0, 1, 2].map((n) => ({ ...counts, [role]: n }))),
  [{ geometry: 0, temporal: 0, quantitative: 0, nominal: 0 }]
);

/** The fewest columns that meet *needs*. */
const fewest = (needs: RoleCounts): Counts => ({
  geometry: needs.geometry?.least ?? 0,
  temporal: needs.temporal?.least ?? 0,
  quantitative: needs.quantitative?.least ?? 0,
  nominal: needs.nominal?.least ?? 0,
});

const names = (counts: Counts, role: ColumnRole) =>
  Array.from({ length: counts[role] }, (_, i) => `${role}_${i}`);

const classified = (counts: Counts): ClassifiedColumn[] =>
  COLUMN_ROLES.flatMap((role) => names(counts, role).map((name) => ({ name, role })));

const grouped = (counts: Counts) =>
  Object.fromEntries(COLUMN_ROLES.map((role) => [role, names(counts, role)])) as Record<
    ColumnRole,
    string[]
  >;

const layersOf = (count: number, counts: Counts): StarterLayer[] =>
  Array.from({ length: count }, (_, i) => ({ name: `table_${i}`, columns: grouped(counts) }));

/** The `"key": "value"` pairs a description quotes, as JSON writes them. */
const quotedPairs = (description: string) =>
  Array.from(
    description.matchAll(/"([^"]+)": "([^"]+)"/g),
    ([, key, value]) => `"${key}":"${value}"`
  );

describe("the Vega-Lite ladder", () => {
  const ids = VEGA_STARTER_LADDER.map((rule) => rule.id);

  test("every generated rule has exactly one builder", () => {
    expect(new Set(ids).size).toBe(ids.length);
    expect(Object.keys(VEGA_STARTER_BUILDERS).sort()).toEqual([...ids].sort());
  });

  test("it tries the rules in the generated order", () => {
    expect(DEFAULT_SPEC_RULES.map((rule) => rule.id)).toEqual(ids);
  });

  test("the first generated rule whose columns are present writes the spec", () => {
    for (const counts of EVERY_COUNTS) {
      const expected = VEGA_STARTER_LADDER.find((rule) => meets(rule.columns, counts));
      const spec = chooseDefaultSpec(classified(counts));
      if (!expected) {
        expect(spec).toBeNull();
        continue;
      }
      const rule = DEFAULT_SPEC_RULES.find((r) => r.id === expected.id);
      expect(spec).toEqual(rule?.build(grouped(counts)));
      expect(spec).toMatchObject({ $schema: VEGA_SCHEMA_URL, mark: expected.produces });
    }
  });

  test("no rule is shadowed by an earlier one", () => {
    for (const rule of VEGA_STARTER_LADDER) {
      const counts = fewest(rule.columns);
      expect(VEGA_STARTER_LADDER.find((r) => meets(r.columns, counts))?.id).toBe(rule.id);
    }
  });

  test("each spec writes what its description quotes", () => {
    for (const rule of VEGA_STARTER_LADDER) {
      const text = JSON.stringify(chooseDefaultSpec(classified(fewest(rule.columns))));
      for (const pair of quotedPairs(rule.description)) expect(text).toContain(pair);
    }
  });
});

describe("the Autark ladder", () => {
  const ids = AUTK_STARTER_LADDER.map((rule) => rule.id);

  test("every generated rule has exactly one builder", () => {
    expect(new Set(ids).size).toBe(ids.length);
    expect(Object.keys(AUTK_STARTER_BUILDERS).sort()).toEqual([...ids].sort());
  });

  test("it tries the rules in the generated order", () => {
    expect(AUTK_STARTER_RULES.map((rule) => rule.id)).toEqual(ids);
  });

  test("the first generated rule whose layers and columns are present writes the document", () => {
    for (const count of [0, 1, 2, 3]) {
      for (const counts of EVERY_COUNTS) {
        const layers = layersOf(count, counts);
        const expected = AUTK_STARTER_LADDER.find(
          (rule) => holds(rule.layers, count) && layers.every(() => meets(rule.columns, counts))
        );
        const doc = chooseAutkStarter(layers);
        if (!expected) {
          expect(doc).toBeNull();
          continue;
        }
        const rule = AUTK_STARTER_RULES.find((r) => r.id === expected.id);
        expect(doc).toEqual(rule?.build(layers));
        expect(Object.keys(doc ?? {})).toEqual([expected.produces]);
      }
    }
  });

  test("no rule is shadowed by an earlier one", () => {
    for (const rule of AUTK_STARTER_LADDER) {
      const counts = fewest(rule.columns);
      const found = AUTK_STARTER_LADDER.find(
        (r) => holds(r.layers, rule.layers.least) && meets(r.columns, counts)
      );
      expect(found?.id).toBe(rule.id);
    }
  });

  test("each document writes what its description quotes", () => {
    for (const rule of AUTK_STARTER_LADDER) {
      const layers = layersOf(rule.layers.least, fewest(rule.columns));
      const text = JSON.stringify(chooseAutkStarter(layers));
      for (const pair of quotedPairs(rule.description)) expect(text).toContain(pair);
    }
  });
});

describe("the dtype table", () => {
  test("each dtype it names, or that starts with a prefix it names, gets its role", () => {
    for (const { role, names: dtypes, prefixes } of DTYPE_ROLES) {
      for (const dtype of dtypes) {
        expect(classifyColumns({ c: dtype }, [])).toEqual([{ name: "c", role }]);
      }
      for (const prefix of prefixes) {
        expect(classifyColumns({ c: `${prefix.toUpperCase()}64` }, [])).toEqual([
          { name: "c", role },
        ]);
      }
    }
  });
});

describe("the image column rule", () => {
  test("Simple View checks the generated names, in the generated order", () => {
    expect(RECOGNIZED_COLUMNS).toEqual(IMAGE_COLUMNS);
  });

  test("a column counts once the generated share of its values are images", () => {
    const size = 10;
    const least = Array.from({ length: size + 1 }, (_, i) => i).find(
      (i) => i / size >= IMAGE_MATCH_THRESHOLD
    );
    const rows = (images: number) =>
      Array.from({ length: size }, (_, i) => ({
        photo: i < images ? "https://example.test/a.png" : "not an image",
      }));
    expect(least).toBeGreaterThan(0);
    expect(resolveImageColumns(rows(least as number))).toEqual(["photo"]);
    expect(resolveImageColumns(rows((least as number) - 1))).toEqual([]);
  });

  test("an unnamed column's URLs count only with a generated extension", () => {
    for (const extension of IMAGE_EXTENSIONS) {
      expect(resolveImageColumns([{ photo: `https://example.test/a.${extension}` }])).toEqual([
        "photo",
      ]);
      expect(
        resolveImageColumns([{ photo: `https://example.test/a.${extension.toUpperCase()}?s=2` }])
      ).toEqual(["photo"]);
    }
    expect(resolveImageColumns([{ photo: "https://example.test/a.txt" }])).toEqual([]);
  });
});
