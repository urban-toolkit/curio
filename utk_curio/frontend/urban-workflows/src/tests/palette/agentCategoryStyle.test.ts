import fs from "fs";
import path from "path";

import {
  AGENT_CATEGORY_FALLBACK,
  AGENT_CATEGORY_ICON,
  AGENT_CATEGORY_KEYS,
  AGENT_KIND_ICON,
  agentCategoryIcon,
  agentCategoryKey,
} from "../../components/menus/nodes/agentsPalette/agentCategoryStyle";

/**
 * How an agent is drawn by category: one colour and one glyph each.
 *
 * This file has asserted three different things, and the history is the point.
 *
 * 1. Originally: five hues declared in `agentCategoryStyle.ts` and copied into
 *    five stylesheets. Each was a near-miss of an existing token (`#4caf72`
 *    beside GeoJSON's `#2F8F4A`, `#5b9bd5` beside data's `#3498db`), which is
 *    the drift `curioTokens.css` exists to prevent. So the assertions were
 *    inverted to ban a colour of one's own.
 * 2. Then: every category folded onto a node bucket, and this file asserted
 *    that `--curio-category-agent-*` must NOT exist. That held the palette
 *    invariant and broke the drawer - `node` and `package` both painted the
 *    neutral grey and `canvas` the dataflow slate, so 16 of 21 built-ins came
 *    out grey and the tile carried no information.
 * 3. Now: an agent family in the token file, plus a glyph per category. The
 *    ban moves from "no agent token" to "no agent token *outside the token
 *    file*", which is what the original rule was actually protecting: colours
 *    are born in one place. Three of the five still alias an existing colour
 *    because the tie is honest; only canvas and node are new.
 *
 * The glyph half exists because colour was never the whole problem: every
 * surface drew the same `faRobot`.
 */

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

const TOKENS = "styles/curioTokens.css";

/** Every stylesheet that paints an agent by category. */
const AGENT_CATEGORY_SURFACES = [
  "components/agents/catalog/AgentCatalogDrawer.module.css",
  "components/menus/nodes/agentsPalette/AgentPaletteRow.module.css",
  "components/agents/attach/AgentAvatarBadge.module.css",
  "components/agents/attach/AgentChatPanel.module.css",
  "components/agents/content/AgentDelegationEntry.module.css",
  "pages/agents/AgentCatalogBrowseCard.module.css",
];

/** The manifest's category vocabulary, which is now also the palette's. */
const MANIFEST_CATEGORIES = ["data", "node", "canvas", "package", "evaluate"];

describe("agentCategoryKey", () => {
  it("keeps every manifest category distinct", () => {
    // The regression this guards: `node` and `package` both resolving to one
    // key, which is what made three quarters of the roster the same grey.
    const resolved = MANIFEST_CATEGORIES.map((c) => agentCategoryKey(c));
    expect(new Set(resolved).size).toBe(MANIFEST_CATEGORIES.length);
    for (const c of MANIFEST_CATEGORIES) {
      expect(agentCategoryKey(c)).toBe(c);
    }
  });

  it("declares exactly the manifest vocabulary, no more", () => {
    expect([...AGENT_CATEGORY_KEYS].sort()).toEqual([...MANIFEST_CATEGORIES].sort());
  });

  it("is case-insensitive", () => {
    expect(agentCategoryKey("Canvas")).toBe("canvas");
    expect(agentCategoryKey("EVALUATE")).toBe("evaluate");
  });

  it("falls back to the neutral for absent or unknown categories", () => {
    // The neutral, not a `default` key with no rule behind it: an unknown
    // category must still paint, the way the canvas falls back to its neutral
    // border rather than rendering a node unstyled.
    for (const input of [undefined, null, "", "mystery"]) {
      expect(agentCategoryKey(input as string | null | undefined)).toBe(
        AGENT_CATEGORY_FALLBACK,
      );
    }
    expect(AGENT_CATEGORY_FALLBACK).toBe("package");
  });
});

describe("agent category glyphs", () => {
  it("gives every category its own icon", () => {
    // 21 built-ins once rendered 21 identical robots; a tint alone could not
    // fix that, and for the grey categories it was not fixing anything.
    const icons = MANIFEST_CATEGORIES.map((c) => agentCategoryIcon(c).iconName);
    expect(new Set(icons).size).toBe(MANIFEST_CATEGORIES.length);
  });

  it("reuses the catalog's own glyph vocabulary where a tie exists", () => {
    // An icon means one thing too: these three are already the dataset, the
    // package and the dataflow across every catalog surface.
    expect(AGENT_CATEGORY_ICON.data.iconName).toBe("database");
    expect(AGENT_CATEGORY_ICON.package.iconName).toBe("cube");
    expect(AGENT_CATEGORY_ICON.canvas.iconName).toBe("diagram-project");
  });

  it("keeps the robot as the kind icon, not a category icon", () => {
    // `faRobot` still means "an agent" in CatalogKindVisuals and the chat
    // surfaces, where the subject is one known agent.
    expect(AGENT_KIND_ICON.iconName).toBe("robot");
    for (const c of MANIFEST_CATEGORIES) {
      expect(agentCategoryIcon(c).iconName).not.toBe("robot");
    }
  });

  it("an unknown category still gets a glyph", () => {
    expect(agentCategoryIcon("mystery").iconName).toBe(
      AGENT_CATEGORY_ICON[AGENT_CATEGORY_FALLBACK].iconName,
    );
  });
});

describe("the agent colour family", () => {
  it("is declared in the token file, for every category and every part", () => {
    const css = read(TOKENS);
    for (const key of MANIFEST_CATEGORIES) {
      for (const part of ["fg", "bg", "on-tint"]) {
        expect(css).toContain(`--curio-category-agent-${key}-${part}:`);
      }
    }
  });

  it("aliases an existing colour wherever the tie is honest", () => {
    // data means data, analysis means analysis, a package is a package. Only
    // canvas and node are new, and only because nothing already meant "the
    // whole canvas" or "one node" without meaning something else too.
    const css = read(TOKENS);
    expect(css).toContain(
      "--curio-category-agent-data-fg: var(--curio-category-data-fg);",
    );
    expect(css).toContain(
      "--curio-category-agent-evaluate-fg: var(--curio-category-computation-fg);",
    );
    expect(css).toContain(
      "--curio-category-agent-package-fg: var(--curio-category-package-fg);",
    );
  });

  it("never borrows a hue the semantic roles already claim", () => {
    // peach = update, sky = published, mint = installed, amber = warning.
    // Reusing one would recreate the collision the role split ended.
    const css = read(TOKENS);
    const family = css
      .split("\n")
      .filter((l) => l.includes("--curio-category-agent-"))
      .join("\n");
    expect(family).not.toMatch(/--curio-accent-(peach|sky|mint|amber)/);
  });
});

describe("agent category stylesheets", () => {
  it.each(AGENT_CATEGORY_SURFACES)("%s declares a rule for every category", (file) => {
    const css = read(file);
    // A missing rule renders that category unstyled, which is how
    // `.strip_bundle` once shipped white-on-transparent.
    const prefixes = ["tint", "chip", "avatar", "strip", "tagAccent"].filter((p) =>
      css.includes(`.${p}_`),
    );
    expect(prefixes.length).toBeGreaterThan(0);
    for (const prefix of prefixes) {
      for (const key of MANIFEST_CATEGORIES) {
        expect(css).toMatch(new RegExp("\\." + prefix + "_" + key + "(?![\\w-])"));
      }
    }
  });

  it.each(AGENT_CATEGORY_SURFACES)("%s uses no literal hex in a category rule", (file) => {
    const categoryRules = read(file)
      .split("\n")
      .filter((line) => /^\.(avatar|chip|tint|accent|strip|tagAccent)_/.test(line));
    expect(categoryRules.join("\n")).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
  });

  it("no surface declares a colour of its own", () => {
    // The rule the original ban was protecting: a colour is born in the token
    // file or not at all. A surface *referencing* the agent family is the
    // point; a surface *defining* a token is the drift.
    for (const file of AGENT_CATEGORY_SURFACES) {
      const defines = read(file)
        .split("\n")
        .filter((l) => /^\s*--curio-[\w-]+\s*:/.test(l))
        .filter((l) => !l.includes("--curio-drawer-z"));
      expect(defines).toEqual([]);
    }
  });

  it("the retired accent stripe is gone from the drawer", () => {
    // PackageCard.module.css no longer defines `.cardAccent`; the family that
    // coloured it would only have painted a stray div in the grid's first slot.
    expect(read("components/agents/catalog/AgentCatalogDrawer.module.css")).not.toContain(
      ".accent_",
    );
    expect(read("components/packages/publishing/PackageCard.module.css")).not.toContain(
      ".cardAccent",
    );
  });
});
