import fs from "fs";
import path from "path";

import {
  AGENT_CATEGORY_FALLBACK,
  AGENT_CATEGORY_KEY,
  agentCategoryKey,
} from "../../components/menus/nodes/agentsPalette/agentCategoryStyle";

/**
 * An agent's colour has to come from the palette every other surface uses.
 *
 * This file used to assert the opposite: that each of the five manifest
 * categories had a colour key of its own (`canvas`, `data`, `node`,
 * `evaluate`, `package`), painted with five hues declared in
 * `agentCategoryStyle.ts` and copied into five stylesheets. Each of those hues
 * was a near-miss of a token that already existed - `#4caf72` beside GeoJSON's
 * `#2F8F4A`, `#5b9bd5` beside data's `#3498db`, `#9b7fda` beside computation's
 * `#8e44ad` - which is precisely the drift `styles/curioTokens.css` exists to
 * prevent.
 *
 * So the assertions now run the other way: categories fold onto buckets that
 * already have meaning, and no agent surface may declare a colour of its own.
 */

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

/** Every stylesheet that paints an agent by category. */
const AGENT_CATEGORY_SURFACES = [
  "components/agents/catalog/AgentsCatalogDrawer.module.css",
  "components/menus/nodes/agentsPalette/AgentPaletteRow.module.css",
  "components/agents/attach/AgentAvatarBadge.module.css",
  "components/agents/attach/AgentChatPanel.module.css",
  "components/agents/content/AgentDelegationEntry.module.css",
];

/** The buckets an agent may resolve to, all of them pre-existing. */
const ALLOWED_KEYS = ["data", "computation", "vis", "package", "dataflow"];

describe("agentCategoryKey", () => {
  it("folds every manifest category onto an existing palette bucket", () => {
    expect(agentCategoryKey("data")).toBe("data");
    expect(agentCategoryKey("evaluate")).toBe("computation");
    expect(agentCategoryKey("canvas")).toBe("dataflow");
    expect(agentCategoryKey("node")).toBe("package");
    expect(agentCategoryKey("package")).toBe("package");
  });

  it("never invents a bucket outside the node-category / kind palettes", () => {
    for (const key of Object.values(AGENT_CATEGORY_KEY)) {
      expect(ALLOWED_KEYS).toContain(key);
    }
  });

  it("is case-insensitive", () => {
    expect(agentCategoryKey("Canvas")).toBe("dataflow");
    expect(agentCategoryKey("EVALUATE")).toBe("computation");
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

describe("agent category stylesheets", () => {
  it.each(AGENT_CATEGORY_SURFACES)("%s declares a rule for every bucket", (file) => {
    const css = read(file);
    // Whichever family the surface uses, every reachable bucket needs a rule -
    // a missing one renders that category unstyled, which is how `.strip_bundle`
    // once shipped white-on-transparent.
    const reachable = [...new Set(Object.values(AGENT_CATEGORY_KEY))];
    const prefix = css.includes(".tint_") ? "tint" : css.includes(".chip_") ? "chip" : "avatar";
    for (const key of reachable) {
      expect(css).toMatch(new RegExp("\\." + prefix + "_" + key + "(?![\\w-])"));
    }
  });

  it.each(AGENT_CATEGORY_SURFACES)("%s uses no literal hex in a category rule", (file) => {
    const categoryRules = read(file)
      .split("\n")
      .filter((line) => /^\.(avatar|chip|tint|accent)_/.test(line));
    expect(categoryRules.join("\n")).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
  });

  it("no surface declares an agent-specific colour token", () => {
    // The token file is the one place a colour may be born. A
    // `--curio-category-agent-*` (or an agent-named hue) would be the five
    // bespoke shades coming back under a different name.
    for (const file of AGENT_CATEGORY_SURFACES) {
      expect(read(file)).not.toMatch(/--curio-(category-agent|agent)-/);
    }
    expect(read("styles/curioTokens.css")).not.toMatch(/--curio-(category-agent|agent)-/);
  });

  it("the retired accent stripe is gone from the drawer", () => {
    // PackageCard.module.css no longer defines `.cardAccent`; the family that
    // coloured it would only have painted a stray div in the grid's first slot.
    expect(read("components/agents/catalog/AgentsCatalogDrawer.module.css")).not.toContain(
      ".accent_",
    );
    expect(read("components/packages/publishing/PackageCard.module.css")).not.toContain(
      ".cardAccent",
    );
  });
});
