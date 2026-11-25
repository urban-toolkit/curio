import fs from "fs";
import path from "path";

/**
 * The chat panel's stylesheet and props hold only what the panel draws.
 *
 * The attachment settings cog left with the account-scope settings move, and
 * its `.attachmentSettingsBtn` rule and its prop's doc comment stayed behind: a
 * rule no component draws, and a comment over the next prop, which it does not
 * describe.
 *
 * Source-read: Jest maps CSS modules to `identity-obj-proxy`, so a rendered
 * assertion cannot tell a live class from a dead one.
 */
const COMPONENTS = path.resolve(__dirname, "../../components");
const ATTACH = path.join(COMPONENTS, "agents/attach");
const STYLESHEET = "AgentChatPanel.module.css";

function sourcesUnder(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return sourcesUnder(full);
    return /\.tsx?$/.test(entry.name) ? [full] : [];
  });
}

/** The classes a stylesheet's selectors name, its rules' bodies left out. */
function declaredClasses(css: string): string[] {
  const selectors = css.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\{[^{}]*\}/g, "{}");
  return Array.from(new Set(Array.from(selectors.matchAll(/\.([A-Za-z_][\w-]*)/g), (m) => m[1]))).sort();
}

describe("the chat panel's stylesheet", () => {
  it("declares only classes a component that imports it draws", () => {
    const css = fs.readFileSync(path.join(ATTACH, STYLESHEET), "utf8");
    const importers = sourcesUnder(COMPONENTS)
      .map((file) => fs.readFileSync(file, "utf8"))
      .filter((text) => text.includes(STYLESHEET));
    expect(importers.length).toBeGreaterThan(0);
    const drawn = importers.join("\n");
    const unused = declaredClasses(css).filter((name) => {
      if (new RegExp(`styles\\.${name}(?![\\w-])`).test(drawn)) return false;
      // A family a component picks by key, `styles[\`tint_${key}\`]`.
      const family = /^([A-Za-z]+_)/.exec(name)?.[1];
      return !(family && drawn.includes(`styles[\`${family}`));
    });
    expect(unused).toEqual([]);
  });
});

describe("the chat panel's props", () => {
  it("carry no doc comment that documents nothing", () => {
    // A doc comment followed straight by another describes no prop: the one
    // under it has its own.
    const source = fs.readFileSync(path.join(ATTACH, "AgentChatPanel.tsx"), "utf8");
    const orphans = source.match(/\/\*\*(?:(?!\*\/)[\s\S])*\*\/\s*\/\*\*/g) ?? [];
    expect(orphans).toEqual([]);
  });
});
