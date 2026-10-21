import fs from "fs";
import path from "path";

import {
  CATEGORY_FALLBACK_FG,
  NODE_CATEGORY_KEY,
  categoryFg,
  colorForCategory,
} from "../../constants/nodeCategoryPalette";
import type { NodeCategory } from "../../registry/types";

/**
 * Node colour means node category, and it has to mean that everywhere.
 *
 * A node shows up in five places: its left border on the canvas, the miniature
 * inside a project card's thumbnail, the category pill in its own title bar,
 * the package card in the Node Catalog browse page, and the package card in
 * the in-canvas Node Catalog drawer. Those used to disagree:
 *
 *  - the canvas and the thumbnail held two hand-kept copies of the same hexes;
 *  - both catalog cards picked a colour by hashing the package's *directory
 *    name*, so three `data` packages rendered orange, violet and blue while a
 *    `computation` package borrowed one of them;
 *  - the filter chips beside those cards used a third palette entirely;
 *  - the title-bar pill was one flat peach for every category.
 *
 * CSS modules resolve through `identity-obj-proxy` under jest, so importing a
 * stylesheet tells you nothing about what a rule contains. The stylesheets are
 * therefore read from disk, the same approach as
 * tests/catalog/datasetFormatStyles.test.ts.
 */

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

/** The four colour buckets every category-keyed surface must cover. */
const KEYS = ["data", "computation", "vis", "package"] as const;

/** Surfaces that resolve a class name from a category at runtime. */
const CATEGORY_SURFACES: { file: string; prefixes: string[] }[] = [
  {
    // Browse card: strip fill and selected border. Not the category tag -
    // chips are plain everywhere since #193; the strip carries the category.
    file: "pages/catalog/PackageBrowseCard.module.css",
    prefixes: ["strip", "cardActive.card"],
  },
  {
    // In-canvas drawer card: the icon tile.
    file: "components/packages/publishing/PackageCard.module.css",
    prefixes: ["cardIcon"],
  },
  {
    // Row badge, shared by the drawer list and the installed list.
    file: "components/catalog/CatalogKindVisuals.module.css",
    prefixes: ["categoryBadge"],
  },
  {
    // The pill in a node's own title bar on the canvas.
    file: "components/packages/editing/PackageMetaHeader.module.css",
    prefixes: ["categoryBadge"],
  },
];

describe("node category palette", () => {
  describe.each(CATEGORY_SURFACES)("$file", ({ file, prefixes }) => {
    const css = read(file);

    it.each(
      prefixes.flatMap((prefix) => KEYS.map((key) => [prefix, key] as const))
    )("declares .%s_%s", (prefix, key) => {
      expect(css).toMatch(new RegExp("\\." + prefix + "_" + key + "(?![\\w-])"));
    });

    it("resolves every category colour to a token, never a literal", () => {
      for (const prefix of prefixes) {
        for (const key of KEYS) {
          const rule = css.match(
            new RegExp("\\." + prefix + "_" + key + "(?![\\w-])\\s*\\{([^}]*)\\}")
          );
          expect(rule).not.toBeNull();
          const body = (rule as RegExpMatchArray)[1];
          expect(body).toContain("var(--curio-category-" + key + "-");
          // A hex here means this surface has started keeping its own copy.
          expect(body).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
        }
      }
    });
  });

  it("keys the Node Catalog rail's category dots to the same palette", () => {
    // The filter chips carried these dots until the chip row was removed; the
    // rail's category rows carry them now, beside the card strips they key.
    const css = read("pages/catalog/CatalogBrowseLayout.module.css");
    for (const key of KEYS) {
      const rule = css.match(new RegExp("\\.categoryDot_" + key + "\\s*\\{([^}]*)\\}"));
      expect(rule).not.toBeNull();
      expect((rule as RegExpMatchArray)[1]).toContain(
        "var(--curio-category-" + key + "-fg)"
      );
    }
  });

  it("paints the canvas node border from the palette, not from its own hexes", () => {
    const tsx = read("components/styles.tsx");
    // The descriptor's category, through the palette's one helper (#524).
    // styles.tsx used to keep a third copy of a type map, and later fell back
    // to the palette's; the palette holds none now.
    expect(tsx).toContain("colorForCategory(");
    expect(tsx).not.toContain("colorForNodeType");
    expect(tsx).not.toMatch(/const nodeTypeBorderColor/);
  });

  it("gives each built-in kind the colour of the category its manifest declares", () => {
    // A map of built-in kinds had drifted from curio.builtin@1: Data Pool
    // painted as computation beside a DATA pill, Data Summary the other way
    // round, and Spatial Join was missing, so it fell back to grey (#524).
    // Colour now comes from the category the manifest declares itself.
    const manifest = JSON.parse(
      fs.readFileSync(
        path.resolve(__dirname, "../../../../../../packages/curio.builtin@1/manifest.json"),
        "utf8",
      ),
    );
    expect(manifest.templates.length).toBeGreaterThan(0);
    for (const template of manifest.templates) {
      const key = NODE_CATEGORY_KEY[template.category as NodeCategory];
      expect([template.id, key]).toEqual([template.id, expect.stringMatching(/^(data|computation|vis|package)$/)]);
      expect([template.id, colorForCategory(template.category)]).toEqual([template.id, categoryFg(key)]);
    }
  });

  it("paints the projects-list thumbnail from the same helper as the canvas", () => {
    const tsx = read("components/DataflowThumbnail.tsx");
    // The thumbnail kept "a static mirror" of the canvas map, then the
    // palette's shared type map. A mirror is a copy, and this one is what
    // drifted: the bar now reads the node's own category.
    expect(tsx).toContain("colorForCategory(");
    expect(read("components/styles.tsx")).toContain("colorForCategory(");
    expect(tsx).not.toContain("NODE_TYPE_CATEGORY");
    expect(tsx).not.toContain("colorForNodeType");
    const bar = tsx.match(/const color = [^;]*;/s);
    expect(bar).not.toBeNull();
    expect(bar![0]).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
  });

  it.each([
    "components/DataflowThumbnail.tsx",
    "constants/nodeCategoryPalette.ts",
    "utils/graphPreviewCategories.ts",
    "components/scenarios/catalog/inProjectRows.ts",
    "components/provenance/DataflowProvenance.tsx",
    "utils/dataflowVersions.ts",
  ])("%s names no package, node type or template id", (file) => {
    // A node's colour comes from the category its template declares, so no
    // thumbnail or palette file keeps a list of node types of its own.
    const text = read(file);
    const packages = path.resolve(__dirname, "../../../../../../packages");
    const named: string[] = [];
    for (const dir of fs.readdirSync(packages).sort()) {
      const manifestFile = path.join(packages, dir, "manifest.json");
      if (!fs.existsSync(manifestFile)) continue;
      const manifest = JSON.parse(fs.readFileSync(manifestFile, "utf8"));
      if (text.includes(manifest.id)) named.push(manifest.id);
      for (const template of manifest.templates) {
        if (text.includes(`${manifest.id}/${template.id}`)) named.push(`${manifest.id}/${template.id}`);
        if (new RegExp(`["'\`]${template.id}["'\`]`).test(text)) named.push(template.id);
      }
    }
    expect(named).toEqual([]);
  });

  it("has no hash-of-the-directory-name left in either catalog card", () => {
    // The specific defect: a colour picked from `pkg.dirName`, which carries no
    // information about the package at all.
    for (const file of [
      "pages/catalog/PackageBrowseCard.tsx",
      "components/packages/publishing/PackageCard.tsx",
    ]) {
      const tsx = read(file);
      expect(tsx).not.toContain("charCodeAt");
      expect(tsx).toContain("primaryCategory");
    }
  });

  it("maps every NodeCategory onto a colour bucket", () => {
    // NodeCategory has five members and the palette has four buckets: both
    // vis_* share one, and `flow` rides with the neutral. A new category with
    // no mapping would silently fall through to an empty class name.
    for (const key of Object.values(NODE_CATEGORY_KEY)) {
      expect(KEYS).toContain(key);
    }
    expect(Object.keys(NODE_CATEGORY_KEY).sort()).toEqual(
      ["computation", "data", "flow", "vis_grammar", "vis_simple"].sort()
    );
  });

  it("returns token references, not literals, from the helpers", () => {
    expect(categoryFg("data")).toBe("var(--curio-category-data-fg)");
    expect(CATEGORY_FALLBACK_FG).toBe("var(--curio-category-package-fg)");
    for (const category of Object.keys(NODE_CATEGORY_KEY) as NodeCategory[]) {
      expect(colorForCategory(category)).toMatch(/^var\(--curio-category-[a-z]+-fg\)$/);
      expect(colorForCategory(category)).toBe(categoryFg(NODE_CATEGORY_KEY[category]));
    }
    // A category the palette has no bucket for, or none: the neutral. A
    // manifest in an account's store is read as written, so an
    // Object.prototype key must not reach the lookup.
    for (const other of ["someone.else/unknown-node", "weird", "vis", "", "constructor", "__proto__", null, undefined]) {
      expect(colorForCategory(other)).toBe(CATEGORY_FALLBACK_FG);
    }
  });
});
