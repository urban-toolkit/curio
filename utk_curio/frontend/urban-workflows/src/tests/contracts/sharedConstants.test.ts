/**
 * The constants the browser and the server share are read from one set of
 * JSON files, src/contracts/*.json, by both. The frontend imports each file
 * and the backend reads it (utk_curio/common/shared_constants.py, held to the
 * same files by backend/tests/test_shared_constants.py). Each test here reads
 * a file and checks that the frontend draws, says or chooses what it holds.
 * No module of the frontend spells a shared sentence or palette color of its
 * own, and no generated copy is left in src/generated/.
 */
import fs from "fs";
import path from "path";

import { stoppedByPhrase } from "../../components/agents/content/AgentSolveAttemptsCard";
import {
  AGENT_CATEGORY_KEYS,
  agentCategoryKey,
} from "../../components/menus/nodes/agentsPalette/agentCategoryStyle";
import { AUTK_STARTER_RULES } from "../../utils/autkDefaultSpec";
import { classifyAutkSpec } from "../../utils/autkSpecKind";
import { RECOGNIZED_COLUMNS, resolveImageColumns } from "../../utils/imageColumns";
import { contrastRatio, noteColors } from "../../utils/noteColors";
import { emptyRenderKind, renderOutcome } from "../../utils/renderOutcome";
import { classifyColumns, groupColumns } from "../../utils/starterSpec";
import { DEFAULT_SPEC_RULES, chooseDefaultSpec } from "../../utils/vegaDefaultSpec";

const SRC = path.resolve(__dirname, "../..");
const CONTRACTS = path.join(SRC, "contracts");
const FILES = [
  "renderCauses",
  "solveStopReasons",
  "agentCategories",
  "noteColors",
  "autkGrammar",
  "visDefaults",
];

/** A shared file, read when a test runs, so a checkout without it fails each test on its own. */
const shared = (name: string): any =>
  JSON.parse(fs.readFileSync(path.join(CONTRACTS, `${name}.json`), "utf8"));

describe("why a render drew nothing", () => {
  test("the node stamps the file's kind and reports exactly the file's causes", () => {
    const data = shared("renderCauses");
    expect(emptyRenderKind(null)).toBe(data.emptyRenderKind);
    for (const cause of Object.keys(data.causes)) {
      expect(emptyRenderKind(cause as never)).toBe(`${data.emptyRenderKind}:${cause}`);
    }
    const reported = [
      renderOutcome({ layersRequested: 1, layersDrawn: 0 }).cause,
      renderOutcome({ sourceRows: 0 }).cause,
      renderOutcome({ rowsIn: 0 }).cause,
      renderOutcome({ rowsIn: 1, drawn: 0 }).cause,
    ];
    expect([...reported].sort()).toEqual(Object.keys(data.causes).sort());
  });
});

describe("why a repair loop stopped", () => {
  test("every reason reads as the file's phrase, and nothing else has one", () => {
    const { phrases } = shared("solveStopReasons");
    expect(Object.keys(phrases).length).toBeGreaterThan(5);
    for (const [reason, phrase] of Object.entries(phrases)) {
      expect(stoppedByPhrase(reason)).toBe(phrase);
    }
    expect(stoppedByPhrase("nonsense")).toBe("");
  });
});

describe("the agent categories", () => {
  test("the palette paints exactly the file's categories", () => {
    const { categories } = shared("agentCategories");
    for (const category of categories) expect(agentCategoryKey(category)).toBe(category);
    expect([...AGENT_CATEGORY_KEYS].sort()).toEqual([...categories].sort());
  });
});

describe("a note's colors", () => {
  test("a note draws the file's palette, default, inks, links and contrast", () => {
    const data = shared("noteColors");
    for (const [name, color] of Object.entries(data.colors)) {
      expect(noteColors(name).background).toBe(color);
    }
    expect(noteColors(undefined).background).toBe(data.colors[data.defaultColor]);
    const light = noteColors(data.defaultColor);
    expect([light.foreground, light.link]).toEqual([data.inks.dark, data.links.onLight]);
    const dark = noteColors("#000000");
    expect([dark.foreground, dark.link]).toEqual([data.inks.light, data.links.onDark]);
    // Around the file's contrast: a color an ink reaches it on is drawn, one
    // no ink reaches it on is not.
    const reaches = (color: string) =>
      Math.max(contrastRatio(color, data.inks.dark), contrastRatio(color, data.inks.light)) >=
      data.minContrast;
    const greys = ["#767676", "#777777"];
    expect(greys.map(reaches)).toEqual([true, false]);
    for (const grey of greys) expect(noteColors(grey).background === grey).toBe(reaches(grey));
  });
});

describe("the Autark grammar", () => {
  test("the node routes every family the file lists, and no other key", () => {
    const { families } = shared("autkGrammar");
    expect(families.length).toBeGreaterThan(1);
    for (const family of families) expect(classifyAutkSpec({ [family]: [{}] })).not.toBe("unknown");
    expect(classifyAutkSpec({ title: [{}] })).toBe("unknown");
  });
});

describe("what a visualization node does by itself", () => {
  test("its column roles, dtype roles and ladders are the file's", () => {
    const data = shared("visDefaults");
    expect(Object.keys(groupColumns([]))).toEqual(data.columnRoles);
    for (const { role, names, prefixes } of data.dtypeRoles) {
      for (const dtype of names) expect(classifyColumns({ c: dtype }, [])).toEqual([{ name: "c", role }]);
      for (const prefix of prefixes) {
        expect(classifyColumns({ c: `${prefix}64` }, [])).toEqual([{ name: "c", role }]);
      }
    }
    expect(DEFAULT_SPEC_RULES.map((rule) => rule.id)).toEqual(
      data.vegaStarterLadder.map((rule: { id: string }) => rule.id),
    );
    expect(AUTK_STARTER_RULES.map((rule) => rule.id)).toEqual(
      data.autkStarterLadder.map((rule: { id: string }) => rule.id),
    );
    const spec = chooseDefaultSpec(classifyColumns({ v: "float64" }, []));
    expect(spec).toMatchObject({ $schema: data.vegaSchemaUrl });
  });

  test("Simple View's image columns are the file's names, extensions and share", () => {
    const data = shared("visDefaults");
    expect(RECOGNIZED_COLUMNS).toEqual(data.imageColumns);
    for (const extension of data.imageExtensions) {
      expect(resolveImageColumns([{ photo: `https://example.test/a.${extension}` }])).toEqual(["photo"]);
    }
    const size = 10;
    const least = Array.from({ length: size + 1 }, (_, i) => i).find(
      (i) => i / size >= data.imageMatchThreshold,
    ) as number;
    expect(least).toBeGreaterThan(0);
    const rows = (images: number) =>
      Array.from({ length: size }, (_, i) => ({
        photo: i < images ? "https://example.test/a.png" : "not an image",
      }));
    expect(resolveImageColumns(rows(least))).toEqual(["photo"]);
    expect(resolveImageColumns(rows(least - 1))).toEqual([]);
  });
});

/** Every value of the shared files with a space in it, and every palette color. */
function sentencesAndColors(): string[] {
  const found = new Set<string>();
  const walk = (value: unknown) => {
    if (Array.isArray(value)) value.forEach(walk);
    else if (value && typeof value === "object") Object.values(value).forEach(walk);
    else if (typeof value === "string" && value.includes(" ")) found.add(value);
  };
  FILES.forEach((name) => walk(shared(name)));
  for (const color of Object.values(shared("noteColors").colors) as string[]) found.add(color);
  return [...found];
}

function sources(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (full !== path.join(SRC, "tests")) sources(full, out);
    } else if (/\.(ts|tsx)$/.test(entry.name)) out.push(full);
  }
  return out;
}

describe("one copy of each value", () => {
  test("no module of the frontend spells a shared sentence or palette color", () => {
    const values = sentencesAndColors();
    expect(values.length).toBeGreaterThan(20);
    const copies: string[] = [];
    for (const file of sources(SRC)) {
      const text = fs.readFileSync(file, "utf8");
      for (const value of values) {
        if (['"', "'", "`"].some((quote) => text.includes(`${quote}${value}${quote}`))) {
          copies.push(`${path.relative(SRC, file)}: ${value}`);
        }
      }
    }
    expect(copies).toEqual([]);
  });

  test("no generated copy is left", () => {
    expect(FILES.every((name) => fs.existsSync(path.join(CONTRACTS, `${name}.json`)))).toBe(true);
    expect(fs.existsSync(path.join(SRC, "generated"))).toBe(false);
  });
});
