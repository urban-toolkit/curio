import fs from "fs";
import path from "path";

/**
 * No agent stylesheet may declare a colour of its own.
 *
 * The category rules were the first pass. This is the rest of the chrome: 247
 * literals across 13 files, which included three near-identical greys
 * (`#8a8b93`, `#8a8a90`, `#8a8a8e`), two near-identical reds (`#b3423f`,
 * `#b3423a`) and four pale danger tints that differed in the last digit. That
 * is what "the format palette was copied into five stylesheets with five
 * different values" looks like before anyone notices.
 *
 * Colour may only be born in `styles/curioTokens.css`. A literal under any of
 * the agent surfaces means someone reached past the palette again.
 *
 * Comment lines are exempt: a comment that explains why a colour was retired
 * has to be able to name it.
 */

const SRC = path.resolve(__dirname, "../..");

/** Every directory whose stylesheets paint an agent surface. */
const AGENT_DIRS = [
  "components/agents",
  "pages/agents",
  "components/menus/nodes/agentsPalette",
];

function cssFiles(rel: string): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith(".css")) out.push(full);
    }
  };
  walk(path.join(SRC, rel));
  return out;
}

const FILES = AGENT_DIRS.flatMap(cssFiles);
const HEX = /#[0-9a-fA-F]{3,8}\b/;
const COMMENT = /^\s*(\/\*|\*|\/\/)/;

describe("agent stylesheets carry no colour literals", () => {
  it("found the stylesheets it is guarding", () => {
    // A guard on the guard: a moved or renamed directory would make every
    // case below pass vacuously.
    expect(FILES.length).toBeGreaterThan(10);
  });

  it.each(FILES.map((f) => [path.relative(SRC, f).split(path.sep).join("/"), f]))(
    "%s",
    (_name, file) => {
      const offenders = fs
        .readFileSync(file, "utf8")
        .split("\n")
        .filter((line) => !COMMENT.test(line))
        .filter((line) => HEX.test(line));
      expect(offenders).toEqual([]);
    },
  );
});

describe("the palette grew one accent, on purpose", () => {
  const tokens = fs.readFileSync(path.join(SRC, "styles/curioTokens.css"), "utf8");

  it("declares an amber accent behind the advisory role", () => {
    // Status was asymmetric: danger had text + bg + border, while success and
    // warning had text only, so every surface needing an advisory tint reached
    // for a literal. Amber is the fourth raw accent, alongside peach/sky/mint.
    expect(tokens).toMatch(/--curio-accent-amber-bg:/);
    expect(tokens).toMatch(/--curio-accent-amber-fg:/);
  });

  it("keeps every status role an alias, never a literal", () => {
    // The raw accent palette is the one place a status colour has a value.
    for (const role of [
      "--curio-success-text",
      "--curio-success-bg",
      "--curio-warning-text",
      "--curio-warning-bg",
      "--curio-role-running-fg",
      "--curio-role-running-bg",
    ]) {
      expect(tokens).toMatch(new RegExp(role + ":\\s*var\\(--curio-accent-"));
    }
  });

  it("keeps formats and roles as separate names", () => {
    // Amber's values match the Parquet pair deliberately - that tint and text
    // colour are already proven to clear contrast together - but they are
    // separate tokens so Parquet can change without dragging every warning
    // with it.
    expect(tokens).toMatch(/--curio-format-parquet-bg:/);
    expect(tokens).not.toMatch(/--curio-warning-bg:\s*var\(--curio-format-/);
  });
});
