import fs from "fs";
import path from "path";

import {
  CATEGORY_FALLBACK_FG,
  NODE_CATEGORY_KEY,
  NODE_TYPE_CATEGORY,
  categoryFg,
  colorForNodeType,
} from "../../constants/nodeCategoryPalette";

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
    // The descriptor's category first, the shared type map for a node with
    // none (#524). styles.tsx used to keep a third copy of that map.
    expect(tsx).toContain("categoryFg(NODE_CATEGORY_KEY[");
    expect(tsx).toContain("colorForNodeType(");
    expect(tsx).not.toMatch(/const nodeTypeBorderColor/);
  });

  it("gives each built-in kind the category its manifest declares", () => {
    // The map had drifted from curio.builtin@1: Data Pool painted as
    // computation beside a DATA pill, Data Summary the other way round, and
    // Spatial Join was missing, so it fell back to grey (#524).
    const manifest = JSON.parse(
      fs.readFileSync(
        path.resolve(__dirname, "../../../../../../packages/curio.builtin@1/manifest.json"),
        "utf8",
      ),
    );
    const fromManifest: Record<string, string> = {};
    for (const template of manifest.templates) {
      fromManifest[`curio.builtin/${template.id}`] =
        NODE_CATEGORY_KEY[template.category as keyof typeof NODE_CATEGORY_KEY];
    }
    expect(NODE_TYPE_CATEGORY).toEqual(fromManifest);
  });

  it("paints the projects-list thumbnail from the same map as the canvas", () => {
    const tsx = read("components/DataflowThumbnail.tsx");
    // The file's own comment used to call its copy "a static mirror" of the
    // canvas map. A mirror is a copy, and this one is what drifted.
    expect(tsx).toContain("NODE_TYPE_CATEGORY");
    expect(tsx).toContain("colorForNodeType");
    const map = tsx.match(/const NODE_COLORS[^;]*;/s);
    expect(map).not.toBeNull();
    expect(map![0]).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
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
    for (const type of Object.keys(NODE_TYPE_CATEGORY)) {
      expect(colorForNodeType(type)).toMatch(/^var\(--curio-category-[a-z]+-fg\)$/);
    }
    expect(colorForNodeType("someone.else/unknown-node")).toBe(CATEGORY_FALLBACK_FG);
  });
});
